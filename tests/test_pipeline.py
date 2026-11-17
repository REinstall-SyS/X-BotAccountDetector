import asyncio
from datetime import timedelta
import json
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError
import pytest

from integrity.analysis import detect, features, simhash
from integrity.collector import receive, subscription_url, unpack
from integrity.config import ENDPOINT, Policy, Scope
from integrity.events import POST, match_record
from integrity.fixtures import START, frames


def test_documented_xrpc_contract_and_scope():
    queries = parse_qs(urlsplit(subscription_url(ENDPOINT, ["did:plc:known"], 23)).query)
    assert queries == {
        "collections": [POST, "app.bsky.feed.repost", "app.bsky.feed.like"],
        "kinds": ["commit", "account"], "dids": ["did:plc:known"], "cursor": ["23"], "maxMessageSizeBytes": ["65536"],
    }
    raw = json.loads(next(frames()))
    raw["payload"]["record"].update({
        "text": "Visit #BookClub", "createdAt": "not-a-date",
        "facets": [{"features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://NEWS.example.org/club#foo"}]}],
    })
    _, _, record = unpack(json.dumps(raw))
    assert record.time_source == "stream"
    assert record.urls == ["https://news.example.org/club"]
    assert match_record(record, Scope(hashtags=["#bookclub"]))
    assert match_record(record, Scope(domains=["example.org"]))
    assert not match_record(record, Scope(domains=["example.com"]))
    assert not match_record(record, Scope(keywords=["sit"]))
    with pytest.raises(ValidationError):
        Scope()
    with pytest.raises(ValidationError):
        Scope(urls=["javascript:alert(1)"])


def test_interruption_flushes_inflight_batch():
    class BrokenStream:
        def __init__(self):
            self.frames = iter(frames())

        async def recv(self):
            raw = next(self.frames)
            if json.loads(raw)["payload"]["seq"] == 3:
                raise ConnectionError("connection lost")
            return raw

    async def run():
        recorded = []

        async def flush(batch, invalid):
            assert invalid == 0
            recorded.extend(item[0] for item in batch)
            return True

        with pytest.raises(ConnectionError, match="lost"):
            await receive(BrokenStream(), flush)
        assert recorded == [1, 2]

    asyncio.run(run())


def test_fixture_replay_rejects_one_shot_viral_overlap_and_orders_event_time():
    records = [unpack(raw)[2] for raw in frames()]
    as_of = START + timedelta(hours=1)
    result = detect(list(reversed(records)), Policy(), as_of)
    assert len(result) == 1
    assert len(result[0]["evidence"]["accounts"]) == 3
    assert all("giveaway" in record["did"] for record in result[0]["evidence"]["records"])
    assert len(result[0]["evidence"]["edges"]) == 3
    assert all(len(edge["matches"]) == 2 for edge in result[0]["evidence"]["edges"])
    assert all(0 <= m["interval_seconds"] <= 90 for edge in result[0]["evidence"]["edges"] for m in edge["matches"])
    assert detect(records, Policy(min_rounds=3), as_of) == []
    assert detect(records, Policy(sync_seconds=10), as_of) == []


def test_missing_features_and_short_text():
    as_of = START + timedelta(hours=1)
    record = unpack(list(frames())[-1])[2]
    obs = features([record], as_of)[record.did]["24h"]
    assert obs["median_interval_seconds"] is None
    assert obs["interaction_concentration"] is None
    assert obs["posts"] == 1
    assert sum(obs["utc_hour_counts"]) == 1
    assert simhash("too short") is None
