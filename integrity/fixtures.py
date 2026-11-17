from datetime import datetime, timedelta, timezone
import json

from .events import POST, PREFIX

FIXTURE_NAME = "Community giveaway watch"
FIXTURE_TOPIC = "community"
START = datetime(2025, 2, 11, 14, tzinfo=timezone.utc)


def frames(start=START):
    posts = []
    campaigns = [
        ("giveaway", 0, 3, "Community grant opens today. Claim your application slot before registration closes.", "claim.example"),
        ("giveaway", 18, 3, "Community grant deadline extended. Use this application form to reserve your slot.", "claim.example"),
        ("viral", 32, 6, "Community library releases its new schedule. Please share with your neighbors.", "library.example"),
    ]
    for group, minute, count, text, host in campaigns:
        for i in range(count):
            at = start + timedelta(minutes=minute, seconds=i * 17)
            posts.append((group, i, at, f"{text} https://{host}/{'form' if group == 'giveaway' else 'schedule'}"))
    for i in range(4):
        posts.append(("discussion", i, start + timedelta(minutes=40 + i), f"Community discussion update {i}."))
    for seq, (group, i, at, text) in enumerate(posts, 1):
        yield json.dumps({
            "$type": "message", "payload": {
                "$type": f"{PREFIX}#commit", "seq": seq, "time": at.isoformat(),
                "did": f"did:plc:fixture{group}{i}", "cid": f"fixture-cid-{seq}",
                "collection": POST, "operation": "create", "rkey": f"p{seq}",
                "record": {"$type": POST, "text": text, "createdAt": at.isoformat()},
            },
        })
