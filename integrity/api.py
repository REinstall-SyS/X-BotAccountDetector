from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
from threading import Lock
import time
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, Field
from psycopg.types.json import Jsonb

from .analysis import DETECTOR_VERSION
from .collector import load_fixture
from .config import DID, NewWatchlist, Policy, Settings
from .fixtures import FIXTURE_NAME, FIXTURE_TOPIC
from .store import connect, enqueue, purge_watchlist

Outcome = Literal["pending", "confirmed", "dismissed", "inconclusive"]


class Review(BaseModel):
    status: Outcome
    expected_status: Outcome
    note: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class WatchlistUpdate(BaseModel):
    enabled: bool
    policy: Policy


class RollingLimit:
    def __init__(self, maximum, keys=1024):
        self.hits = defaultdict(deque)
        self.lock = Lock()
        self.maximum = maximum
        self.keys = keys

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            if key not in self.hits and len(self.hits) >= self.keys:
                for old_key in list(self.hits):
                    if self.hits[old_key][-1] <= now - 60:
                        del self.hits[old_key]
                if len(self.hits) >= self.keys:
                    raise HTTPException(429, "Request limit reached")
            hits = self.hits[key]
            while hits and hits[0] <= now - 60:
                hits.popleft()
            if len(hits) >= self.maximum:
                raise HTTPException(429, "Request limit reached", headers={"Retry-After": "60"})
            hits.append(now)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = FastAPI(title="Signal Desk", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    auth = HTTPBearer(auto_error=False)
    failed_auth = RollingLimit(25)
    requests = RollingLimit(150)

    @app.middleware("http")
    async def limits(request: Request, call_next):
        # Bound actual bytes, including chunked requests.
        if request.method in {"POST", "PATCH", "DELETE"}:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 64 * 1024:
                    return JSONResponse({"detail": "Request body is too large"}, status_code=413)
                body.extend(chunk)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        return response

    def reviewer(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        supplied = credentials.credentials if credentials and credentials.credentials.isascii() else ""
        found = None
        for name, token in (settings.reviewers or {}).items():
            if hmac.compare_digest(supplied, token):
                found = name
        if found is None:
            failed_auth.check(request.client.host if request.client else "unknown")
            raise HTTPException(401, "Valid reviewer token required", headers={"WWW-Authenticate": "Bearer"})
        requests.check(found)
        return found

    def database():
        with connect(settings.database_url) as db:
            yield db

    @app.exception_handler(psycopg.OperationalError)
    async def database_unavailable(_request, _exc):
        return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/api/health")
    def health(db=Depends(database)):
        db.execute("SELECT 1 FROM schema_migrations LIMIT 1")
        return {"status": "ready"}

    @app.get("/api/session")
    def session(name=Depends(reviewer)):
        return {"reviewer": name, "mode": settings.mode, "topic_stream": settings.allow_topic_stream}

    @app.get("/api/watchlists", dependencies=[Depends(reviewer)])
    def watchlists(db=Depends(database)):
        return db.execute(
            """SELECT w.*, h.state, h.matched, h.scanned, h.invalid, h.updated_at AS heartbeat,
               c.observed_at AS cursor_time, coalesce(q.failures, 0) AS analysis_failures
               FROM watchlists w LEFT JOIN ingestion_health h ON h.watchlist_id=w.id
               LEFT JOIN analysis_queue q ON q.watchlist_id=w.id
               LEFT JOIN LATERAL (SELECT observed_at FROM checkpoints WHERE watchlist_id=w.id
                                 ORDER BY updated_at DESC LIMIT 1) c ON true ORDER BY w.id"""
        ).fetchall()

    @app.post("/api/watchlists", status_code=201, dependencies=[Depends(reviewer)])
    def create_watchlist(body: NewWatchlist, db=Depends(database)):
        if settings.mode == "bluesky" and not (body.scope.dids or settings.allow_topic_stream):
            raise HTTPException(422, "Add a public DID. Network-wide topical scanning is disabled.")
        db.execute("SELECT pg_advisory_xact_lock(926241)")
        if db.execute("SELECT count(*) AS n FROM watchlists").fetchone()["n"] >= 12:
            raise HTTPException(409, "This workspace supports up to 12 watchlists")
        row = db.execute(
            """INSERT INTO watchlists (name, scope, policy, source) VALUES (%s,%s,%s,%s)
               ON CONFLICT DO NOTHING RETURNING *""",
            (body.name.strip(), Jsonb(body.scope.model_dump()), Jsonb(body.policy.model_dump()), settings.mode),
        ).fetchone()
        if not row:
            raise HTTPException(409, "A watchlist with this name already exists")
        return row

    @app.patch("/api/watchlists/{watchlist_id}", dependencies=[Depends(reviewer)])
    def update_watchlist(watchlist_id: int, body: WatchlistUpdate, db=Depends(database)):
        row = db.execute("SELECT * FROM watchlists WHERE id=%s FOR UPDATE", (watchlist_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Watchlist not found")
        result = db.execute(
            "UPDATE watchlists SET enabled=%s, policy=%s WHERE id=%s RETURNING *",
            (body.enabled, Jsonb(body.policy.model_dump()), watchlist_id),
        ).fetchone()
        if body.policy.retention_days < row["policy"]["retention_days"]:
            purge_watchlist(db, watchlist_id, body.policy.retention_days, datetime.now(timezone.utc))
        enqueue(db, watchlist_id)
        return result

    @app.delete("/api/watchlists/{watchlist_id}", status_code=204, dependencies=[Depends(reviewer)])
    def delete_watchlist(watchlist_id: int, db=Depends(database)):
        if not db.execute("DELETE FROM watchlists WHERE id=%s", (watchlist_id,)).rowcount:
            raise HTTPException(404, "Watchlist not found")
        return Response(status_code=204)

    @app.post("/api/fixtures", status_code=202, dependencies=[Depends(reviewer)])
    def fixture(watchlist_id: int | None = None, db=Depends(database)):
        if settings.mode != "fixture":
            raise HTTPException(409, "Fixture loading is available in fixture mode")
        if watchlist_id is not None:
            if not load_fixture(settings, watchlist_id):
                raise HTTPException(409, "Choose an enabled fixture watchlist")
            return {"watchlist_id": watchlist_id}
        db.execute("SELECT pg_advisory_xact_lock(926241)")
        row = db.execute("SELECT id, source FROM watchlists WHERE name=%s", (FIXTURE_NAME,)).fetchone()
        if not row:
            if db.execute("SELECT count(*) AS n FROM watchlists").fetchone()["n"] >= 12:
                raise HTTPException(409, "This workspace supports up to 12 watchlists")
            row = db.execute(
                """INSERT INTO watchlists (name, scope, policy, source) VALUES (%s,%s,%s,'fixture')
                   RETURNING id, source""",
                (FIXTURE_NAME, Jsonb(NewWatchlist(name=FIXTURE_NAME, scope={"keywords": [FIXTURE_TOPIC]}).scope.model_dump()),
                 Jsonb(Policy().model_dump())),
            ).fetchone()
        if row["source"] != "fixture":
            raise HTTPException(409, "The sample watchlist name is already in use")
        db.commit()
        if not load_fixture(settings, row["id"]):
            raise HTTPException(409, "Enable the fixture watchlist first")
        return {"watchlist_id": row["id"]}

    @app.get("/api/alerts", dependencies=[Depends(reviewer)])
    def alerts(
        watchlist_id: int | None = None, status: Outcome | None = None,
        source: Literal["bluesky", "fixture"] | None = None,
        priority: Literal["routine", "high"] | None = None,
        since: AwareDatetime | None = None, until: AwareDatetime | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        db=Depends(database),
    ):
        return db.execute(
            """SELECT a.id, a.watchlist_id, w.name AS topic, w.source, a.status, a.priority, a.created_at,
               a.updated_at, a.first_at, a.last_at, jsonb_array_length(a.evidence->'accounts') AS accounts,
               jsonb_array_length(a.evidence->'edges') AS edges, a.evidence->'records'->0->>'text' AS preview,
               coalesce(a.evidence->'signals', '[]'::jsonb) AS signals
               FROM alerts a JOIN watchlists w ON a.watchlist_id=w.id
               WHERE (%s::bigint IS NULL OR w.id=%s) AND (%s::text IS NULL OR a.status=%s)
               AND (%s::text IS NULL OR a.priority=%s)
               AND (%s::text IS NULL OR w.source=%s)
               AND (%s::timestamptz IS NULL OR a.last_at >= %s)
               AND (%s::timestamptz IS NULL OR a.first_at <= %s)
               ORDER BY CASE a.priority WHEN 'high' THEN 0 ELSE 1 END, a.created_at DESC, a.id DESC
               LIMIT %s OFFSET %s""",
            (watchlist_id, watchlist_id, status, status, priority, priority, source, source, since, since, until, until, limit, offset),
        ).fetchall()

    def fetch_alert(db, alert_id):
        alert = db.execute(
            """SELECT a.id, a.watchlist_id, w.name AS topic, w.source, a.status, a.priority,
                      a.created_at, a.first_at, a.last_at, a.evidence
               FROM alerts a JOIN watchlists w ON w.id=a.watchlist_id WHERE a.id=%s""",
            (alert_id,),
        ).fetchone()
        if not alert:
            raise HTTPException(404, "Investigation not found")
        alert["reviews"] = db.execute(
            "SELECT reviewer, status, note, reviewed_at FROM reviews WHERE alert_id=%s ORDER BY id", (alert_id,),
        ).fetchall()
        return alert

    @app.get("/api/alerts/{alert_id}", dependencies=[Depends(reviewer)])
    def alert(alert_id: int, db=Depends(database)):
        return fetch_alert(db, alert_id)

    @app.get("/api/alerts/{alert_id}/export", dependencies=[Depends(reviewer)])
    def export(alert_id: int, db=Depends(database)):
        report = fetch_alert(db, alert_id)
        report["scope_note"] = "Observed coordination evidence warrants human review. It does not identify automation or intent."
        return Response(json.dumps(report, default=str, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="investigation-{alert_id}.json"'})

    @app.post("/api/alerts/{alert_id}/reviews", status_code=201)
    def review(alert_id: int, body: Review, name=Depends(reviewer), db=Depends(database)):
        row = db.execute("SELECT status FROM alerts WHERE id=%s FOR UPDATE", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Investigation not found")
        current = row["status"]
        if current != body.expected_status:
            raise HTTPException(409, "Status changed. Reload the investigation before reviewing.")
        if (current == "pending") == (body.status == "pending"):
            raise HTTPException(409, "Resolve a pending alert or reopen a reviewed alert first")
        db.execute("UPDATE alerts SET status=%s, updated_at=now() WHERE id=%s", (body.status, alert_id))
        return db.execute(
            """INSERT INTO reviews (alert_id, reviewer, status, note) VALUES (%s,%s,%s,%s)
               RETURNING reviewer, status, note, reviewed_at""",
            (alert_id, name, body.status, body.note.strip()),
        ).fetchone()

    @app.get("/api/watchlists/{watchlist_id}/account", dependencies=[Depends(reviewer)])
    def account(watchlist_id: int, did: Annotated[str, Query(max_length=255)], db=Depends(database)):
        if not DID.fullmatch(did):
            raise HTTPException(422, "Provide an AT Protocol DID")
        watch = db.execute("SELECT name, source FROM watchlists WHERE id=%s", (watchlist_id,)).fetchone()
        if not watch:
            raise HTTPException(404, "Watchlist not found")
        snapshot = db.execute(
            "SELECT as_of, features FROM account_features WHERE watchlist_id=%s AND did=%s", (watchlist_id, did)
        ).fetchone()
        timeline = db.execute(
            """SELECT record FROM records WHERE watchlist_id=%s AND did=%s AND NOT deleted
               ORDER BY event_at DESC LIMIT 100""", (watchlist_id, did),
        ).fetchall()
        related = db.execute(
            """SELECT id, status, priority, last_at FROM alerts
               WHERE watchlist_id=%s AND (evidence->'accounts') ? %s
               ORDER BY last_at DESC, id DESC LIMIT 12""", (watchlist_id, did),
        ).fetchall()
        return {"did": did, "watchlist": watch, "snapshot": snapshot, "records": [r["record"] for r in timeline], "investigations": related}

    @app.get("/api/metrics", dependencies=[Depends(reviewer)])
    def metrics(source: Literal["bluesky", "fixture"] = "bluesky", db=Depends(database)):
        summary = db.execute(
            """SELECT count(*) AS alert_volume, count(*) FILTER (WHERE status='pending') AS pending,
               count(*) FILTER (WHERE status='confirmed') AS confirmed,
               count(*) FILTER (WHERE status='dismissed') AS dismissed,
               count(*) FILTER (WHERE status='inconclusive') AS inconclusive
               FROM alerts JOIN watchlists w ON w.id=watchlist_id
               WHERE w.source=%s AND alerts.created_at >= now() - interval '7 days'""", (source,),
        ).fetchone()
        processing = db.execute(
            """SELECT sum(candidates) AS candidates, sum(duplicates) AS duplicates,
               percentile_cont(0.5) WITHIN GROUP(ORDER BY latency_seconds) AS median_lag_seconds,
               percentile_cont(0.5) WITHIN GROUP(ORDER BY duration_seconds) AS median_processing_seconds,
               count(*) FILTER (WHERE truncated) AS truncated_runs, count(*) AS runs
               FROM analysis_runs JOIN watchlists w ON w.id=watchlist_id
               WHERE w.source=%s AND analyzed_at >= now() - interval '7 days'""", (source,),
        ).fetchone()
        top = db.execute(
            """SELECT alerts.status, latest.reviewer FROM alerts JOIN watchlists w ON w.id=watchlist_id
               LEFT JOIN LATERAL (SELECT reviewer FROM reviews WHERE alert_id=alerts.id
                                  ORDER BY id DESC LIMIT 1) latest ON true
               WHERE w.source=%s AND alerts.created_at >= now() - interval '7 days'
               ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, alerts.created_at DESC, alerts.id DESC LIMIT 10""",
            (source,),
        ).fetchall()
        actions = db.execute(
            """SELECT count(*) AS actions, count(DISTINCT reviewer) AS reviewers FROM reviews r
               JOIN alerts a ON a.id=r.alert_id JOIN watchlists w ON w.id=a.watchlist_id
               WHERE w.source=%s AND r.reviewed_at >= now() - interval '7 days'""", (source,),
        ).fetchone()
        decisive = summary["confirmed"] + summary["dismissed"]
        adjudicated = sum(
            r["status"] in {"confirmed", "dismissed"} and r["reviewer"] in settings.evaluation_reviewers
            for r in top
        )
        return {
            **summary, **processing, **actions, "source": source, "decisive": decisive,
            "dismissal_rate": summary["dismissed"] / decisive if decisive else None,
            "duplicate_rate": processing["duplicates"] / processing["candidates"] if processing["candidates"] else None,
            "top_10_count": len(top), "top_10_adjudicated": adjudicated,
            "precision_at_10": sum(r["status"] == "confirmed" for r in top) / 10 if adjudicated == 10 else None,
        }

    @app.get("/api/drift", dependencies=[Depends(reviewer)])
    def drift(db=Depends(database)):
        rows = db.execute(
            """SELECT w.id, w.name, period, count(*) AS n,
               avg((jsonb_array_length(record->'urls') > 0)::integer) AS url_fraction
               FROM watchlists w CROSS JOIN (VALUES ('current'), ('reference')) AS periods(period)
               CROSS JOIN LATERAL (
                   SELECT record FROM records r WHERE r.watchlist_id = w.id AND NOT deleted
                   AND record->>'collection' = 'app.bsky.feed.post'
                   AND r.observed_at >= CASE period WHEN 'current' THEN now()-interval '1 day' ELSE now()-interval '7 days' END
                   AND r.observed_at < CASE period WHEN 'current' THEN now() ELSE now()-interval '1 day' END
                   ORDER BY r.observed_at DESC LIMIT 5000
               ) sampled WHERE w.source='bluesky' GROUP BY w.id, w.name, period ORDER BY w.id, period"""
        ).fetchall()
        grouped = {}
        for row in rows:
            item = grouped.setdefault(row["id"], {"watchlist_id": row["id"], "name": row["name"]})
            item[row["period"]] = {"n": row["n"], "url_fraction": float(row["url_fraction"])}
        for item in grouped.values():
            current, reference = item.get("current"), item.get("reference")
            item["shift"] = (
                current["url_fraction"] - reference["url_fraction"]
                if current and reference and min(current["n"], reference["n"]) >= 100 else None
            )
        return list(grouped.values())

    @app.get("/api/models", dependencies=[Depends(reviewer)])
    def models():
        report = Path(os.getenv("INTEGRITY_MODEL_REPORT", "artifacts/twibot22/report.json"))
        benchmarks = []
        if report.is_file():
            benchmarks.append(json.loads(report.read_text(encoding="utf-8")))
        return {
            "detector": DETECTOR_VERSION, "semantic_enabled": bool(settings.semantic_model),
            "research": benchmarks, "supervised_deployed": False,
        }

    return app


app = create_app()
