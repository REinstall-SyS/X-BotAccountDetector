"""Bounded live Jetstream integration check for a dedicated PostgreSQL database."""
import argparse
import asyncio
from contextlib import suppress
from dataclasses import replace
from secrets import token_urlsafe
import time

from fastapi.testclient import TestClient

from .api import create_app
from .collector import stream_watchlist
from .config import Settings
from .store import analyze_one, connect, migrate


async def check(settings, watchlist):
    task = asyncio.create_task(stream_watchlist(settings, watchlist))
    watchlist_id = watchlist["id"]
    started = time.monotonic()
    try:
        while time.monotonic() - started < 30:
            await asyncio.sleep(1)
            with connect(settings.database_url) as db:
                result = db.execute(
                    """SELECT (SELECT count(*) FROM records WHERE watchlist_id=%s AND NOT deleted) AS records,
                              (SELECT seq FROM checkpoints WHERE watchlist_id=%s) AS seq""",
                    (watchlist_id, watchlist_id),
                ).fetchone()
                if result["records"] >= 3:
                    analyze_one(db)
                    snapshots = db.execute(
                        "SELECT count(*) AS n FROM account_features WHERE watchlist_id=%s", (watchlist_id,)
                    ).fetchone()["n"]
                    if snapshots:
                        print(f"Live smoke passed: {result['records']} retained records, {snapshots} account snapshots, cursor present.", flush=True)
                        return
        raise RuntimeError("No matching live records within the test window")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", help="Explicitly permit a bounded topical scan for this keyword")
    parser.add_argument("--did", help="Use a public DID to filter the upstream stream")
    args = parser.parse_args()
    if not args.keyword and not args.did:
        parser.error("Supply --did or --keyword")
    scope = {}
    if args.did:
        scope["dids"] = [args.did]
    if args.keyword:
        scope["keywords"] = [args.keyword]
    token = token_urlsafe(32)
    settings = replace(Settings.from_env(), mode="bluesky", allow_topic_stream=bool(args.keyword),
                       reviewers={"live-smoke": token}, evaluation_reviewers=())
    migrate(settings.database_url)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/watchlists", headers=headers, json={
                "name": f"Live smoke {token_urlsafe(6)}", "scope": scope, "policy": {"max_per_minute": 10, "retention_days": 1},
            },
        )
        response.raise_for_status()
        watchlist = response.json()
        try:
            asyncio.run(check(settings, watchlist))
        finally:
            client.delete(f"/api/watchlists/{watchlist['id']}", headers=headers).raise_for_status()


if __name__ == "__main__":
    main()
