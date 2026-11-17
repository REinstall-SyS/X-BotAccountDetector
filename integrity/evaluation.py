"""Reproduce detector behavior on the deterministic synthetic scenario."""
from datetime import timedelta
from itertools import combinations
import json

from .analysis import DETECTOR_VERSION, detect
from .collector import unpack
from .config import Policy
from .fixtures import START, frames


def report():
    records = [unpack(frame)[2] for frame in frames()]
    policy = Policy()
    labels = {
        "repeated_demo": {r.did for r in records if "giveaway" in r.did},
        "one_shot_viral_demo": {r.did for r in records if "viral" in r.did},
    }
    results = {}
    for name, members in labels.items():
        sample = [record for record in records if record.did in members]
        pairs = [
            (a, b) for a, b in combinations(sample, 2)
            if a.did != b.did and abs((a.event_at - b.event_at).total_seconds()) <= policy.sync_seconds
            and set(a.urls).intersection(b.urls)
        ]
        alerts = detect(sample, policy, START + timedelta(hours=1))
        results[name] = {
            "accounts": len(members), "records": len(sample),
            "shared_url_rule_matches": len(pairs), "coordination_alerts": len(alerts),
            "evidence_records": sum(len(a["uris"]) for a in alerts),
        }
    return {"evaluation_kind": "deterministic_synthetic_scenario", "detector": DETECTOR_VERSION,
            "policy": policy.model_dump(), "cases": results}


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
