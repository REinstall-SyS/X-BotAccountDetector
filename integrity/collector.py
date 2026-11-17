import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import random
import time
from urllib.parse import urlencode

from pydantic import ValidationError
from websockets.asyncio.client import connect as websocket
from websockets.exceptions import InvalidStatus, WebSocketException

from .config import Settings
from .events import COLLECTIONS, POST, decode
from .fixtures import frames
from .store import connect, set_health, write_batch

BATCH_SIZE = 128
BATCH_SECONDS = 1
MAX_FRAME_BYTES = 64 * 1024
SCAN_PER_SECOND = 250
LOG = logging.getLogger(__name__)


class CursorUnavailable(OSError):
    pass


def subscription_url(endpoint, dids, cursor):
    collections = COLLECTIONS if dids else (POST,)
    params = [("collections", collection) for collection in collections]
    params.extend([("kinds", "commit"), ("kinds", "account"), ("maxMessageSizeBytes", str(MAX_FRAME_BYTES))])
    params.extend(("dids", did) for did in dids)
    if cursor is not None:
        params.append(("cursor", str(cursor)))
    return f"{endpoint}?{urlencode(params)}"


def unpack(frame):
    # XRPC sends explicit errors as frames. Reconnect from the durable checkpoint.
    envelope = json.loads(frame)
    if envelope.get("$type") == "error":
        raise ConnectionError("Jetstream returned an error frame")
    payload = envelope.get("payload")
    if isinstance(payload, dict) and payload.get("$type") == "network.bsky.jetstream.subscribeEvents#info":
        if payload.get("name") in {"OutdatedCursor", "FutureCursor"}:
            raise CursorUnavailable("Jetstream cannot resume from the last sequence")
    payload, record = decode(frame)
    return payload.seq, payload.witnessed_at or payload.time, record


def persisted_cursor(settings, watchlist_id, stream):
    with connect(settings.database_url) as db:
        row = db.execute(
            "SELECT seq FROM checkpoints WHERE watchlist_id = %s AND stream = %s", (watchlist_id, stream)
        ).fetchone()
        return row["seq"] if row else None


def persist(settings, watchlist_id, stream, batch, invalid=0):
    with connect(settings.database_url) as db:
        return write_batch(db, watchlist_id, stream, batch, invalid)


def status(settings, watchlist_id, state):
    with connect(settings.database_url) as db:
        if db.execute("SELECT 1 FROM watchlists WHERE id=%s AND enabled FOR UPDATE", (watchlist_id,)).fetchone():
            set_health(db, watchlist_id, state)


async def receive(ws, flush):
    batch = []
    invalid = 0
    deadline = time.monotonic() + BATCH_SECONDS
    last_frame = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if len(batch) + invalid >= BATCH_SIZE or now >= deadline:
                if batch or invalid:
                    if not await flush(batch, invalid):
                        return
                    batch, invalid = [], 0
                deadline = time.monotonic() + BATCH_SECONDS
            if now - last_frame > 120:
                raise TimeoutError("Jetstream went quiet")
            try:
                async with asyncio.timeout(max(0.01, deadline - time.monotonic())):
                    frame = await ws.recv()
            except asyncio.TimeoutError:
                continue
            last_frame = time.monotonic()
            try:
                event = unpack(frame)
                batch.append(event)
            except (ValidationError, ValueError, AttributeError, UnicodeError):
                invalid += 1
            await asyncio.sleep(1 / SCAN_PER_SECOND)
    except (WebSocketException, OSError):
        if batch or invalid:
            await flush(batch, invalid)
        raise


async def stream_watchlist(settings, row):
    watchlist_id = row["id"]
    stream = settings.endpoint
    delay = 1
    while True:
        opened = time.monotonic()
        try:
            cursor = await asyncio.to_thread(persisted_cursor, settings, watchlist_id, stream)
            url = subscription_url(stream, row["scope"]["dids"], cursor)
            async with websocket(url, subprotocols=["xrpc.v1.json"], max_size=MAX_FRAME_BYTES,
                                 max_queue=8, open_timeout=12, close_timeout=2) as ws:
                await asyncio.to_thread(status, settings, watchlist_id, "connected")

                async def flush(batch, invalid):
                    return await asyncio.to_thread(persist, settings, watchlist_id, stream, batch, invalid)

                await receive(ws, flush)
                return
        except Exception as exc:
            LOG.warning("stream_retry watchlist=%s reason=%s", watchlist_id, type(exc).__name__)
            cursor_unavailable = isinstance(exc, CursorUnavailable)
            if isinstance(exc, InvalidStatus) and exc.response.status_code == 400:
                try:
                    cursor_unavailable = json.loads(exc.response.body or b"{}").get("error") == "CursorTooOld"
                except (ValueError, AttributeError):
                    pass
            try:
                await asyncio.to_thread(status, settings, watchlist_id,
                                        "cursor outside replay window" if cursor_unavailable else "reconnecting")
            except Exception:
                LOG.warning("stream_health_unavailable watchlist=%s", watchlist_id)
            if time.monotonic() - opened > 30:
                delay = 1
            await asyncio.sleep(delay + random.random())
            delay = min(60, delay * 2)


def watchlists(settings):
    with connect(settings.database_url) as db:
        return db.execute(
            "SELECT * FROM watchlists WHERE source = 'bluesky' AND enabled ORDER BY id LIMIT 12"
        ).fetchall()


async def collect(settings):
    tasks = {}
    try:
        while True:
            try:
                rows = {
                    row["id"]: row for row in await asyncio.to_thread(watchlists, settings)
                    if row["scope"]["dids"] or settings.allow_topic_stream
                }
                for watchlist_id in list(tasks):
                    if watchlist_id not in rows or tasks[watchlist_id].done():
                        tasks.pop(watchlist_id).cancel()
                for watchlist_id, row in rows.items():
                    if watchlist_id not in tasks:
                        tasks[watchlist_id] = asyncio.create_task(stream_watchlist(settings, row))
            except Exception as exc:
                LOG.warning("collector_retry reason=%s", type(exc).__name__)
            await asyncio.sleep(3)
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


def load_fixture(settings, watchlist_id, now=None):
    with connect(settings.database_url) as db:
        row = db.execute("SELECT * FROM watchlists WHERE id = %s FOR UPDATE", (watchlist_id,)).fetchone()
        if not row or row["source"] != "fixture" or not row["enabled"]:
            return False
        if db.execute("SELECT 1 FROM checkpoints WHERE watchlist_id = %s AND stream = 'fixture'", (watchlist_id,)).fetchone():
            return True
        start = (now or datetime.now(timezone.utc)) - timedelta(minutes=48)
        return write_batch(db, watchlist_id, "fixture", [unpack(frame) for frame in frames(start)])


async def probe(settings, did, seconds=15):
    # Verify the wire contract without storing or printing any public content.
    observed = []
    url = subscription_url(settings.endpoint, [did] if did else [], None)
    async with websocket(url, subprotocols=["xrpc.v1.json"], max_size=MAX_FRAME_BYTES, open_timeout=12) as ws:
        async with asyncio.timeout(seconds):
            while len(observed) < 3:
                seq, _, record = unpack(await ws.recv())
                if record is not None:
                    observed.append(seq)
    if observed != sorted(set(observed)):
        raise RuntimeError("Unexpected sequence order")
    async with websocket(subscription_url(settings.endpoint, [did] if did else [], observed[0]),
                         subprotocols=["xrpc.v1.json"], max_size=MAX_FRAME_BYTES, open_timeout=12) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=seconds)
        resumed, _, _ = unpack(raw)
    if resumed != observed[0]:
        raise RuntimeError("Expected inclusive sequence replay")
    print(f"Jetstream v2 validated: {len(observed)} commits; inclusive resume sequence={resumed}")
