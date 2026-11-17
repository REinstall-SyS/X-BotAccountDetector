# Detection and evaluation

## Signal construction

The unit of investigation is a connected group within one watchlist. Record authorship, interaction references, URIs, CIDs, observed stream time, and the analysis timestamp source survive normalization. A plausible record timestamp is used for event-time analysis. Otherwise, the witnessed stream time is used and displayed. Record timestamps are client-supplied and can be incorrect.

The worker reads up to the newest 5,000 retained records from the last seven days. Account snapshots give observed frequency, interval statistics, UTC hour counts, repeated-text ratio, URL use, top domains, interaction concentration, and timestamp fallbacks across 1-hour, 24-hour, and 7-day windows. Sparse statistics are null. Profile age, follower counts and other metadata the stream does not supply are absent. These are features of a filtered sample.

Coordination uses posts within 24 hours. Candidate retrieval uses bounded adjacent time buckets indexed by exact URL and by eight bands of a 64-bit SimHash over word bigrams. When enabled, the CPU sentence encoder adds time-bucket candidates and normalized cosine similarity. Buckets retain the most recent 36 records per key. Candidate matches require a configurable maximum interval and at least one of an exact shared URL, a SimHash distance of at most 9 bits, or a semantic cosine of at least 0.88. Shared domains corroborate a match. Distinct rounds must be separated by at least five minutes. The default requires two rounds per account pair and at least three connected accounts. Direct observable interactions are displayed as supplemental edges. Connected components can bridge weaker subgroups, which is why the interface exposes individual edges and records. A group with at least five members or coordination edges receives high priority. There is no bot probability.

Alerts deduplicate by watchlist, sorted member-set hash and UTC date of the first cited coordination record. Pending matching alerts may gain new evidence. A reviewed alert retains the evidence version the reviewer saw unless source data changes or expires. A changed membership can create a separate alert. Threshold changes enqueue reanalysis and affect new detection. Historical alerts preserve the policy under which they were opened.

## Reproducible results

Run `python -m integrity.evaluation` from the repository root. This deterministic scenario compares one simple exact-URL rule to graph coordination with the default policy.

| Synthetic case | Accounts | Posts | Synchronized exact-URL pairs | Cluster alerts |
| --- | ---: | ---: | ---: | ---: |
| Repeated giveaway scenario | 3 | 6 | 6 | 1 |
| One-round library announcement | 6 | 6 | 15 | 0 |

These scenarios demonstrate software behavior. They cannot estimate precision, recall, false positives, or generalization on public activity. The legacy profile benchmark is a separate synthetic experiment. The live protocol probe validates the wire contract and cursor, and the live smoke test checks persistence and feature computation. Neither carries a coordination label.

## Review evaluation

The Model Lab reports alert volume, duplicate candidate rate, median processing time, dismissal rate, reviewer workload, and precision at 10. Metrics use a rolling seven-day window. Outcome counts are current decisions on alerts created during the window. Reviewer workload counts review actions during the window. Duplicate candidate rate is the proportion of generated candidates matching an existing alert fingerprint and day. Dismissal rate divides dismissed by decisive alerts and reflects reviewer dispositions, with uncertain cases excluded.

For precision at 10, rank by triage priority and alert recency. Configure independent evaluator identities in `EVALUATION_REVIEWERS`, a comma-separated list of names from `INTEGRITY_REVIEWERS`. Assign these reviewers independently of threshold tuning and blind them to the algorithm variant during comparative evaluation. The dashboard reports the proportion confirmed only when all ten ranked cases have decisive latest outcomes from those identities. Other cases show coverage and a blank metric. This is a descriptive review metric. The product has limited labels for estimating recall or a true false-positive rate. Use a randomly sampled review set and adjudication protocol before claiming population performance.

Input drift compares the proportion of observed posts containing URLs in the last 24 hours with the preceding six days. It samples up to 5,000 posts per period per live watchlist. It flags a change of 20 percentage points given at least 100 sampled posts on both sides. This is a coverage diagnostic. Filters, topic shifts, collection gaps and caps can all affect it.

## Known limits

- Synchronization can reflect advocacy, recurring announcements, time zones, or ordinary reuse. A sampled relationship neither establishes cause nor indicates malicious automation.
- The sampling cap, bucket limits, one-day graph window, exact-URL handling, language coverage and required repeat rounds can miss campaigns. Short text, URL shorteners, and near-boundary posting times can reduce detection. Network-wide conclusions are inappropriate for DID-restricted or topical samples.
- A topic-only watcher tracks posts, their reply and quote references, and account lifecycle notifications. It does not reconstruct the full network of interactions. The stream adapter does not implement archive backfill or reconcile repository resyncs. Interrupted monitoring can miss upstream deletions outside the replay window.
- The queue is intended for one small team. Reviewed examples stay group-level. A future supervised group experiment needs sufficient independently adjudicated examples, recurrent-campaign grouping across splits, time-based holdout, and a separate validation phase. Review feedback informs evaluation today. Training and deployment remain explicit decisions.
