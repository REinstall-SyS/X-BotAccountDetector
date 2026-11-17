from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
from time import monotonic

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .analysis import MAX_EVENTS, detect, features
from .config import Policy, Scope
from .events import Record, match_record


def connect(url):
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5, options="-c timezone=UTC")


def migrate(url):
    with connect(url) as db:
        db.execute("SELECT pg_advisory_xact_lock(926240)")
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
            if db.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (path.name,)).fetchone():
                continue
            db.execute(path.read_text(encoding="utf-8"), prepare=False)
            db.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))


def enqueue(db, watchlist_id):
    db.execute("INSERT INTO analysis_queue (watchlist_id) VALUES (%s) ON CONFLICT DO NOTHING", (watchlist_id,))


def set_health(db, watchlist_id, state, scanned=0, matched=0, invalid=0):
    db.execute(
        """INSERT INTO ingestion_health (watchlist_id, state, scanned, matched, invalid)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (watchlist_id) DO UPDATE SET state = excluded.state, updated_at = now(),
           scanned = ingestion_health.scanned + excluded.scanned,
           matched = ingestion_health.matched + excluded.matched,
           invalid = ingestion_health.invalid + excluded.invalid""",
        (watchlist_id, state, scanned, matched, invalid),
    )


def write_batch(db, watchlist_id, stream, batch, invalid=0):
    watchlist = db.execute("SELECT * FROM watchlists WHERE id = %s FOR UPDATE", (watchlist_id,)).fetchone()
    if not watchlist or not watchlist["enabled"]:
        return False
    scope = Scope.model_validate(watchlist["scope"])
    policy = Policy.model_validate(watchlist["policy"])
    gate = db.execute(
        "SELECT seq FROM checkpoints WHERE watchlist_id = %s AND stream = %s", (watchlist_id, stream)
    ).fetchone()
    previous = gate["seq"] if gate else 0
    now = datetime.now(timezone.utc)
    accepted = db.execute(
        "SELECT count(*) AS n FROM records WHERE watchlist_id = %s AND NOT deleted AND ingested_at > %s",
        (watchlist_id, now - timedelta(minutes=1)),
    ).fetchone()["n"]
    changed = matched = 0
    for seq, observed_at, record in sorted(batch, key=lambda item: item[0]):
        if seq <= previous:
            continue
        previous = seq
        db.execute(
            """INSERT INTO checkpoints (watchlist_id, stream, seq, observed_at) VALUES (%s, %s, %s, %s)
               ON CONFLICT (watchlist_id, stream) DO UPDATE
               SET seq = excluded.seq, observed_at = excluded.observed_at, updated_at = now()""",
            (watchlist_id, stream, seq, observed_at),
        )
        if record is None:
            continue
        if record.account_event:
            if record.deleted:
                uris = [
                    row["uri"] for row in db.execute(
                        """UPDATE records SET deleted = true, record = NULL, seq = %s
                           WHERE watchlist_id = %s AND did = %s AND NOT deleted AND seq < %s RETURNING uri""",
                        (seq, watchlist_id, record.did, seq),
                    )
                ]
                if uris:
                    db.execute("DELETE FROM alerts WHERE watchlist_id = %s AND evidence_uris && %s", (watchlist_id, uris))
                    changed += len(uris)
            continue
        existing = db.execute(
            "SELECT deleted, seq FROM records WHERE watchlist_id = %s AND uri = %s",
            (watchlist_id, record.uri),
        ).fetchone()
        if existing and seq <= existing["seq"]:
            continue
        keep = (
            not record.deleted
            and record.observed_at >= now - timedelta(days=policy.retention_days)
            and match_record(record, scope)
        )
        if not keep and (not existing or existing["deleted"]):
            continue
        if keep and (not existing or existing["deleted"]):
            if accepted >= policy.max_per_minute:
                continue
            matched += 1
            accepted += 1
        changed += 1
        if existing and not existing["deleted"]:
            db.execute(
                "DELETE FROM alerts WHERE watchlist_id = %s AND evidence_uris @> %s",
                (watchlist_id, [record.uri]),
            )
        db.execute(
            """INSERT INTO records
               (watchlist_id, uri, did, seq, event_at, observed_at, deleted, record)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (watchlist_id, uri) DO UPDATE SET seq = excluded.seq,
               event_at = excluded.event_at, observed_at = excluded.observed_at,
               deleted = excluded.deleted, record = excluded.record,
               ingested_at = CASE WHEN records.deleted THEN now() ELSE records.ingested_at END""",
            (watchlist_id, record.uri, record.did, seq, record.event_at, record.observed_at,
             not keep, Jsonb(record.model_dump(mode="json")) if keep else None),
        )
    if changed:
        enqueue(db, watchlist_id)
    set_health(db, watchlist_id, "fixture loaded" if watchlist["source"] == "fixture" else "streaming",
               len(batch) + invalid, matched, invalid)
    return True


def analyze_one(db, now=None, semantic_model=""):
    now = now or datetime.now(timezone.utc)
    row = db.execute(
        """SELECT w.id, w.policy, q.queued_at FROM analysis_queue q JOIN watchlists w ON w.id=q.watchlist_id
           WHERE q.available_at <= clock_timestamp()
           ORDER BY q.queued_at, w.id LIMIT 1 FOR UPDATE OF w SKIP LOCKED"""
    ).fetchone()
    if not row:
        return False
    try:
        with db.transaction():
            _analyze_watchlist(db, row, now, semantic_model)
    except Exception as exc:
        logging.getLogger(__name__).error("analysis_retry watchlist=%s reason=%s", row["id"], type(exc).__name__)
        db.execute(
            """UPDATE analysis_queue SET failures = failures + 1,
               available_at = clock_timestamp() + make_interval(secs => least(300, power(2, least(failures, 9))))
               WHERE watchlist_id = %s""", (row["id"],),
        )
    return True


def _analyze_watchlist(db, row, now, semantic_model):
    started = monotonic()
    watchlist_id = row["id"]
    policy = Policy.model_validate(row["policy"])
    data = db.execute(
        """SELECT record FROM records WHERE watchlist_id = %s AND NOT deleted
           AND event_at BETWEEN %s AND %s AND observed_at >= %s
           ORDER BY event_at DESC, uri LIMIT %s""",
        (watchlist_id, now - timedelta(days=7), now, now - timedelta(days=policy.retention_days), MAX_EVENTS + 1),
    ).fetchall()
    records = [Record.model_validate(item["record"]) for item in data[:MAX_EVENTS]]
    snapshots = features(records, now)
    db.execute("DELETE FROM account_features WHERE watchlist_id = %s", (watchlist_id,))
    with db.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO account_features VALUES (%s, %s, %s, %s)",
            [(watchlist_id, did, now, Jsonb(snapshot)) for did, snapshot in snapshots.items()],
        )
    alerts = detect(records, policy, now, semantic_model)
    duplicates = 0
    for alert in alerts:
        params = (
            watchlist_id, alert["fingerprint"], alert["episode"], alert["first_at"], alert["last_at"],
            alert["priority"], Jsonb(alert["evidence"]), alert["uris"],
        )
        created = db.execute(
            """INSERT INTO alerts (watchlist_id, fingerprint, episode, first_at, last_at,
                                   priority, evidence, evidence_uris)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""", params,
        ).fetchone()
        if created is None:
            duplicates += 1
            db.execute(
                """UPDATE alerts SET last_at=%s, priority=%s, evidence=%s, evidence_uris=%s, updated_at=now()
                   WHERE watchlist_id=%s AND fingerprint=%s AND episode=%s
                   AND status='pending' AND last_at < %s""",
                (alert["last_at"], alert["priority"], Jsonb(alert["evidence"]), alert["uris"],
                 watchlist_id, alert["fingerprint"], alert["episode"], alert["last_at"]),
            )
    db.execute(
        """INSERT INTO analysis_runs
           (watchlist_id, candidates, duplicates, latency_seconds, sample_size, truncated, duration_seconds)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (watchlist_id, len(alerts), duplicates, max(0, (now - row["queued_at"]).total_seconds()),
         len(records), len(data) > MAX_EVENTS, monotonic() - started),
    )
    db.execute("DELETE FROM analysis_queue WHERE watchlist_id = %s", (watchlist_id,))


def purge_watchlist(db, watchlist_id, days, now):
    cut = now - timedelta(days=days)
    deleted = db.execute(
        """WITH expired AS (
               DELETE FROM records WHERE watchlist_id = %s AND observed_at < %s RETURNING uri
           ) DELETE FROM alerts WHERE watchlist_id = %s AND (
               last_at < %s OR evidence_uris && ARRAY(SELECT uri FROM expired)
           )""",
        (watchlist_id, cut, watchlist_id, cut),
    ).rowcount
    db.execute("DELETE FROM account_features WHERE watchlist_id = %s", (watchlist_id,))
    db.execute("DELETE FROM analysis_runs WHERE watchlist_id = %s AND analyzed_at < %s", (watchlist_id, cut))
    enqueue(db, watchlist_id)
    return deleted


def purge(db, now):
    # Lock watchlists in the same order as ingestion and analysis for single-list writes.
    for row in db.execute("SELECT id, policy FROM watchlists ORDER BY id FOR UPDATE SKIP LOCKED"):
        purge_watchlist(db, row["id"], row["policy"]["retention_days"], now)
