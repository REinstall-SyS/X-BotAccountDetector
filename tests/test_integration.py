from datetime import datetime, timedelta, timezone
import json
import os

from fastapi.testclient import TestClient
import pytest

from integrity.api import create_app
from integrity.collector import persisted_cursor, unpack
from integrity.config import Settings
from integrity.fixtures import FIXTURE_NAME, frames
from integrity.store import analyze_one, connect, migrate, purge, write_batch

TOKEN = "test-reviewer-" + "k" * 36
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")


@pytest.fixture
def system():
    settings = Settings(database_url=URL, reviewers={"caseworker": TOKEN})
    migrate(URL)
    with connect(URL) as db:
        db.execute("TRUNCATE watchlists RESTART IDENTITY CASCADE")
    with TestClient(create_app(settings)) as client:
        yield settings, client
    with connect(URL) as db:
        db.execute("TRUNCATE watchlists RESTART IDENTITY CASCADE")


def new_watchlist(client):
    response = client.post("/api/watchlists", json={"name": "Integration test", "scope": {"keywords": ["community"]}}, headers=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def analyze():
    with connect(URL) as db:
        return analyze_one(db)


def test_watchlist_batch_cursor_review_export_and_metrics(system):
    settings, client = system
    watch = new_watchlist(client)
    watch_id = watch["id"]
    now = datetime.now(timezone.utc)
    batch = [unpack(raw) for raw in frames(now - timedelta(hours=1))]
    # A late event has a newer stream sequence but an earlier authored timestamp.
    seq, observed, last = batch[-1]
    last = last.model_copy(update={"event_at": now - timedelta(minutes=75)})
    batch[-1] = (seq, observed, last)
    with connect(URL) as db:
        assert write_batch(db, watch_id, "test", batch[:7])
    assert persisted_cursor(settings, watch_id, "test") == 7
    with connect(URL) as db:
        write_batch(db, watch_id, "test", batch[6:])
        write_batch(db, watch_id, "test", batch)
        assert db.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == len(batch)
        assert db.execute("SELECT count(*) AS n FROM analysis_queue").fetchone()["n"] == 1
    assert persisted_cursor(settings, watch_id, "test") == len(batch)
    assert analyze() and not analyze()
    assert client.get("/api/alerts").status_code == 401
    listing = client.get("/api/alerts", headers=AUTH).json()
    assert len(listing) == 1
    alert_id = listing[0]["id"]
    root = f"/api/alerts/{alert_id}"
    outcome = {"status": "confirmed", "expected_status": "pending", "note": "Repeated link across independent rounds"}
    assert client.post(root + "/reviews", json=outcome, headers=AUTH).status_code == 201
    assert client.post(root + "/reviews", json=outcome, headers=AUTH).status_code == 409
    export = client.get(root + "/export", headers=AUTH)
    assert export.status_code == 200
    assert export.json()["reviews"][0]["reviewer"] == "caseworker"
    assert len(export.json()["evidence"]["records"]) == 6
    assert all(r["cid"] for r in export.json()["evidence"]["records"])
    metrics = client.get("/api/metrics?source=fixture", headers=AUTH).json()
    assert metrics["confirmed"] == metrics["actions"] == 1
    assert metrics["precision_at_10"] is None
    assert client.get("/api/metrics?source=bluesky", headers=AUTH).json()["alert_volume"] == 0
    assert client.post(root + "/reviews", json={
        "status": "pending", "expected_status": "confirmed", "note": "New context arrived",
    }, headers=AUTH).status_code == 201
    assert client.get(root, headers=AUTH).json()["status"] == "pending"


def test_threshold_changes_and_retention(system):
    _, client = system
    watch = new_watchlist(client)
    route = f'/api/watchlists/{watch["id"]}'
    policy = {**watch["policy"], "min_rounds": 3}
    assert client.patch(route, json={"enabled": True, "policy": policy}, headers=AUTH).status_code == 200
    with connect(URL) as db:
        write_batch(db, watch["id"], "test", [unpack(f) for f in frames(datetime.now(timezone.utc) - timedelta(hours=1))])
    assert analyze()
    assert client.get("/api/alerts", headers=AUTH).json() == []
    policy["min_rounds"] = 2
    assert client.patch(route, json={"enabled": True, "policy": policy}, headers=AUTH).status_code == 200
    assert analyze()
    assert len(client.get("/api/alerts", headers=AUTH).json()) == 1
    with connect(URL) as db:
        purge(db, datetime.now(timezone.utc) + timedelta(days=15))
        assert db.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        assert db.execute("SELECT count(*) AS n FROM alerts").fetchone()["n"] == 0


def test_source_deletion_and_failed_batch_recovery(system):
    settings, client = system
    watch_id = new_watchlist(client)["id"]
    batch_frames = list(frames(datetime.now(timezone.utc) - timedelta(hours=1)))
    batch = list(map(unpack, batch_frames))
    with pytest.raises(RuntimeError):
        with connect(URL) as db:
            write_batch(db, watch_id, "test", batch)
            raise RuntimeError("Interrupted transaction")
    assert persisted_cursor(settings, watch_id, "test") is None
    with connect(URL) as db:
        assert db.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        write_batch(db, watch_id, "test", batch)
    assert analyze()
    frame = json.loads(batch_frames[0])
    frame["payload"].update(seq=len(batch) + 1, operation="delete")
    del frame["payload"]["record"]
    del frame["payload"]["cid"]
    with connect(URL) as db:
        write_batch(db, watch_id, "test", [unpack(json.dumps(frame))])
        assert db.execute("SELECT record, deleted FROM records WHERE seq=%s", (len(batch) + 1,)).fetchone() == {
            "record": None, "deleted": True,
        }
    assert client.get("/api/alerts", headers=AUTH).json() == []


def test_account_deactivation_removes_evidence(system):
    _, client = system
    watch_id = new_watchlist(client)["id"]
    batch = [unpack(frame) for frame in frames(datetime.now(timezone.utc) - timedelta(hours=1))]
    with connect(URL) as db:
        write_batch(db, watch_id, "test", batch)
    assert analyze()
    author = batch[0][2].did
    event = {"$type": "message", "payload": {
        "$type": "network.bsky.jetstream.subscribeEvents#account",
        "did": author, "time": datetime.now(timezone.utc).isoformat(), "seq": len(batch) + 1,
        "account": {"did": author, "active": False, "status": "deactivated"},
    }}
    with connect(URL) as db:
        write_batch(db, watch_id, "test", [unpack(json.dumps(event))])
        assert not db.execute("SELECT 1 FROM records WHERE did=%s AND NOT deleted", (author,)).fetchone()
    assert client.get("/api/alerts", headers=AUTH).json() == []


def test_analysis_retry_rolls_back_and_unblocks_other_watchlists(system, monkeypatch):
    _, client = system
    existing = new_watchlist(client)
    sample = client.post("/api/fixtures", headers=AUTH).json()["watchlist_id"]
    records = [unpack(frame) for frame in frames(datetime.now(timezone.utc) - timedelta(hours=1))]
    with connect(URL) as db:
        write_batch(db, existing["id"], "test", records)
        db.execute("UPDATE analysis_queue SET queued_at=now()-interval '5 seconds' WHERE watchlist_id=%s", (existing["id"],))
    from integrity import store

    real_detect = store.detect

    def fail(*args, **kwargs):
        raise ValueError("simulated model failure")

    monkeypatch.setattr(store, "detect", fail)
    assert analyze()
    monkeypatch.setattr(store, "detect", real_detect)
    with connect(URL) as db:
        job = db.execute("SELECT failures FROM analysis_queue WHERE watchlist_id=%s", (existing["id"],)).fetchone()
        assert job["failures"] == 1
        assert not db.execute("SELECT 1 FROM account_features WHERE watchlist_id=%s", (existing["id"],)).fetchone()
        # Preserve the backoff regardless of test-machine execution speed.
        db.execute("UPDATE analysis_queue SET available_at=now()+interval '1 minute' WHERE watchlist_id=%s", (existing["id"],))
    assert analyze()
    assert client.get("/api/alerts", headers=AUTH).json()[0]["watchlist_id"] == sample
    assert client.get("/api/drift", headers=AUTH).json() == []


def test_fixture_endpoint_is_idempotent(system):
    _, client = system
    first = client.post("/api/fixtures", headers=AUTH)
    assert first.status_code == 202, first.text
    assert client.post("/api/fixtures", headers=AUTH).json() == first.json()
    assert analyze() and not analyze()
    assert client.get("/api/watchlists", headers=AUTH).json()[0]["name"] == FIXTURE_NAME
