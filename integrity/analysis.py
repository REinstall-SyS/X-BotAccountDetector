from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import blake2b, sha256
from itertools import combinations
from pathlib import Path
import re
from statistics import median, pstdev

import networkx as nx

from .config import Policy
from .events import AT_POST, HTTP, POST, Record

DETECTOR_VERSION = "coordination-v1"
MAX_EVENTS = 5000
MAX_BUCKET = 36
MIN_EPISODE_GAP = 5 * 60


@lru_cache(maxsize=8192)
def canonical_text(text):
    return " ".join(re.findall(r"\w+", HTTP.sub("", text).casefold()))


@lru_cache(maxsize=8192)
def simhash(text):
    words = text.split()
    if len(words) < 5:
        return None
    weights = [0] * 64
    for left, right in set(zip(words, words[1:])):
        value = int.from_bytes(blake2b(f"{left} {right}".encode(), digest_size=8).digest(), "big")
        for index in range(64):
            weights[index] += 1 if (value >> index) & 1 else -1
    return sum((weight > 0) << index for index, weight in enumerate(weights))


@lru_cache(maxsize=1)
def encoder(model_path):
    from sentence_transformers import SentenceTransformer

    if not Path(model_path).is_dir():
        raise ValueError("SEMANTIC_MODEL must point to an installed local model snapshot")
    return SentenceTransformer(model_path, device="cpu", local_files_only=True)


def candidates(posts, policy, semantic_model=""):
    texts = [canonical_text(post.text) for post in posts]
    hashes = [simhash(text) for text in texts]
    embeddings = (
        encoder(semantic_model).encode(texts, batch_size=32, normalize_embeddings=True)
        if semantic_model and posts else None
    )
    buckets = defaultdict(deque)
    pairs = defaultdict(list)
    for index, post in enumerate(posts):
        if hashes[index] is None and not post.urls:
            continue
        stamp = post.event_at.timestamp()
        time_bucket = int(stamp // policy.sync_seconds)
        keys = [("url", url) for url in post.urls]
        if hashes[index] is not None:
            keys.extend((band, (hashes[index] >> (8 * band)) & 255) for band in range(8))
        if embeddings is not None and len(texts[index].split()) >= 5:
            keys.append(("semantic-time", 0))
        prior = set()
        for kind, value in keys:
            for bucket in (time_bucket - 1, time_bucket):
                prior.update(buckets.get((kind, value, bucket), ()))
            members = buckets[(kind, value, time_bucket)]
            if len(members) == MAX_BUCKET:
                members.popleft()
            members.append(index)
        for previous in sorted(prior):
            other = posts[previous]
            delta = stamp - other.event_at.timestamp()
            if other.did == post.did or delta > policy.sync_seconds:
                continue
            shared = sorted(set(post.urls).intersection(other.urls))
            distance = (
                (hashes[index] ^ hashes[previous]).bit_count()
                if hashes[index] is not None and hashes[previous] is not None else None
            )
            similar = distance is not None and distance <= 9
            cosine = (
                float(embeddings[index] @ embeddings[previous])
                if embeddings is not None and min(len(texts[index].split()), len(texts[previous].split())) >= 5
                else None
            )
            if not (shared or similar or (cosine is not None and cosine >= 0.88)):
                continue
            key = tuple(sorted((other.did, post.did)))
            rounds = pairs[key]
            if rounds and (
                stamp - rounds[-1]["stamp"] < MIN_EPISODE_GAP
                or other.uri in {rounds[-1]["left"], rounds[-1]["right"]}
            ):
                continue
            rounds.append({
                "stamp": stamp, "left": other.uri, "right": post.uri,
                "interval_seconds": round(delta, 3), "shared_urls": shared,
                "shared_domains": sorted(set(post.domains).intersection(other.domains)),
                "simhash_distance": distance if similar else None,
                "cosine": round(cosine, 3) if cosine is not None and cosine >= 0.88 else None,
            })
    return pairs


def detect(records: list[Record], policy: Policy, now: datetime, semantic_model=""):
    posts = sorted(
        (r for r in records if r.collection == POST and r.event_at >= now - timedelta(hours=24)),
        key=lambda r: (r.event_at, r.uri),
    )
    by_uri = {r.uri: r for r in records}
    graph = nx.Graph()
    for (left, right), rounds in candidates(posts, policy, semantic_model).items():
        if len(rounds) >= policy.min_rounds:
            graph.add_edge(left, right, rounds=rounds[-12:])
    interactions = defaultdict(list)
    for record in records:
        for kind, ref in record.refs.items():
            peer = AT_POST.fullmatch(ref)[1]
            pair = tuple(sorted((record.did, peer)))
            if kind != "thread" and peer != record.did and record.event_at >= now - timedelta(hours=24):
                if len(interactions[pair]) < 6:
                    interactions[pair].append({"kind": kind, "record": record.uri, "target": ref})

    alerts = []
    for members in nx.connected_components(graph):
        if len(members) < policy.min_accounts:
            continue
        subgraph = graph.subgraph(members)
        edges = []
        cited = set()
        coordination_pairs = {tuple(sorted(edge)) for edge in subgraph.edges}
        member_pairs = (pair for pair in interactions if set(pair) <= members)
        for left, right in sorted(coordination_pairs.union(member_pairs)):
            rounds = subgraph[left][right]["rounds"] if subgraph.has_edge(left, right) else []
            direct = interactions[(left, right)]
            for item in rounds:
                cited.update((item["left"], item["right"]))
            for item in direct:
                cited.add(item["record"])
                if item["target"] in by_uri:
                    cited.add(item["target"])
            edges.append({"source": left, "target": right, "matches": rounds, "interactions": direct})
        evidence_records = sorted((by_uri[uri] for uri in cited), key=lambda r: (r.event_at, r.uri))
        coordinated = [by_uri[m[key]].event_at for edge in edges for m in edge["matches"] for key in ("left", "right")]
        first, last = min(coordinated), max(coordinated)
        fingerprint = sha256("|".join(sorted(members)).encode()).hexdigest()
        signal_types = set()
        for edge in edges:
            if edge["interactions"]:
                signal_types.add("Public interactions")
            for match in edge["matches"]:
                if match["shared_urls"]:
                    signal_types.add("Shared destinations")
                if match["simhash_distance"] is not None or match["cosine"] is not None:
                    signal_types.add("Similar content")
        alerts.append({
            "fingerprint": fingerprint, "episode": first.astimezone(timezone.utc).date(),
            "first_at": first, "last_at": last, "uris": sorted(cited),
            "priority": "high" if len(members) >= 5 or subgraph.number_of_edges() >= 5 else "routine",
            "evidence": {
                "accounts": sorted(members), "edges": edges, "density": round(nx.density(subgraph), 3),
                "signals": sorted(signal_types),
                "records": [r.model_dump(mode="json") for r in evidence_records],
                "detector": DETECTOR_VERSION, "policy": policy.model_dump(), "semantic_enabled": bool(semantic_model),
            },
        })
    return alerts


def features(records: list[Record], now: datetime):
    by_did = defaultdict(list)
    for record in records:
        if record.event_at <= now:
            by_did[record.did].append(record)
    result = {}
    for did, activity in by_did.items():
        windows = {}
        for hours in (1, 24, 168):
            window = [r for r in activity if r.event_at > now - timedelta(hours=hours)]
            posts = sorted((r for r in window if r.collection == POST), key=lambda r: r.event_at)
            intervals = [(b.event_at - a.event_at).total_seconds() for a, b in zip(posts, posts[1:])]
            hours_utc = Counter(r.event_at.astimezone(timezone.utc).hour for r in posts)
            texts = [canonical_text(r.text) for r in posts if canonical_text(r.text)]
            targets = Counter(
                AT_POST.fullmatch(uri)[1] for r in window for kind, uri in r.refs.items() if kind != "thread"
            )
            average = sum(intervals) / len(intervals) if intervals else None
            windows[f"{hours}h"] = {
                "posts": len(posts), "posts_per_hour": round(len(posts) / hours, 4),
                "median_interval_seconds": median(intervals) if intervals else None,
                "interval_cv": round(pstdev(intervals) / average, 3) if len(intervals) > 1 and average else None,
                "utc_hour_counts": [hours_utc[h] for h in range(24)],
                "repeat_ratio": round(1 - len(set(texts)) / len(texts), 3) if texts else None,
                "posts_with_urls": sum(bool(r.urls) for r in posts),
                "top_domains": Counter(host for r in posts for host in r.domains).most_common(5),
                "interaction_concentration": round(max(targets.values()) / targets.total(), 3) if targets else None,
                "time_fallbacks": sum(r.time_source == "stream" for r in window),
            }
        result[did] = windows
    return result
