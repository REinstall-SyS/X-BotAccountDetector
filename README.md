# Signal Desk

Signal Desk helps a moderation team investigate repeated coordination in a bounded sample of public Bluesky activity. Reviewers can inspect the accounts, records, and relationships that produced an alert, record a decision, and export the evidence. An alert is an invitation to investigate. It cannot establish automation, intent, or a platform policy violation.

## Quick start

Prerequisites are Docker Engine and the Compose plugin. From the repository root, copy `.env.example` to `.env` and replace the example token. Generate a distinct high-entropy token for each reviewer with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. `INTEGRITY_REVIEWERS` is a JSON object mapping reviewer names to tokens.

```sh
docker compose up --build -d
```

Open [Signal Desk](http://127.0.0.1:8080) and sign in with a configured token. The site binds to loopback by default.

- Select **Load fixture** in Overview for the ready-made scenario. Or create a watchlist with keyword `community` in Settings, open it, and select **Replay fixture**. Replay runs once per watchlist and uses the same validation, storage, and analysis code as live collection.
- Open the investigation, select an edge, and inspect the highlighted posts and shared destination. The one-round viral-sharing fixture does not appear in the queue.
- Record a decision and note. Reopen the investigation if new evidence warrants a second review. Export a JSON evidence report and inspect the synthetic review metrics in **Model Lab**.

### Live Bluesky

Set `INTEGRITY_MODE=bluesky` in `.env`, then run the following.

```sh
docker compose --profile live up --build -d
```

Create a watchlist with one or more public AT Protocol DIDs. DIDs define the upstream subscription. For posts, topical criteria are ORed with each other and ANDed with the DID restriction. Likes and reposts by the specified DIDs are stored as public interaction references. Keywords use word boundaries, hashtags match tags, domains include subdomains, and exact URLs preserve query parameters. Bluesky has no upstream keyword/domain filter on Jetstream. Set `ALLOW_TOPIC_STREAM=1` to opt into a rate-bounded scan of the public post collection for topical watchlists without DIDs. That mode retains only matching posts and excludes the broader like and repost streams.

Collection is capped at 12 watchlists and 100 DIDs per watchlist. Each collector limits its receive rate, in-memory queue, frame size, and retained matches per minute. Wide filters can fall behind the live tip. Observe the ingestion status and cursor time in Overview. Cursor replay is inclusive and scoped to the selected Jetstream host. If the cursor falls outside the server's replay window, the collector reports the coverage gap and preserves the cursor. Create a new watchlist to start from the live tip. The public live path needs no paid API or credentials. [Bluesky Jetstream documentation](https://bsky.network/docs/jetstream/)

### Local development

Use Python 3.11+, Node 22+, and PostgreSQL 17. Install dependencies into a virtual environment with `python -m pip install -r requirements-dev.txt`. Export `DATABASE_URL` for a PostgreSQL database dedicated to this project and set the reviewer token mapping in the API environment.

```sh
# Terminal 1
python -m integrity migrate
uvicorn integrity.api:app --host 127.0.0.1

# Terminal 2
python -m integrity analyze

# Terminal 3
cd web
npm ci
npm run dev -- --host 127.0.0.1
```

The Vite UI runs at [localhost:5173](http://127.0.0.1:5173). In live mode, set `INTEGRITY_MODE=bluesky` for the API and run `python -m integrity collect` in a separate terminal with the same mode and `DATABASE_URL`.

## Architecture

```mermaid
flowchart LR
    J["Public Jetstream v2 / offline fixture"] --> C["Collect, validate, normalize"]
    C --> T["PostgreSQL transaction: records + cursor + job"]
    T --> W["Analysis worker"]
    W --> F["1h, 24h, 7d account snapshots"]
    W --> G["Timed similarity candidates → NetworkX components"]
    G --> A["Evidence-backed investigation alerts"]
    F --> API["FastAPI"]
    A --> API
    API <--> R["React investigation and review UI"]
    API --> H["Reviewer decisions, notes and audit history"]
    H --> M["Review and workload metrics"]
```

PostgreSQL serves as the durable queue. It coalesces each watchlist's pending changes into one job and uses row locks with `SKIP LOCKED` to claim work. A batch commits record changes, the upstream checkpoint, and its queue entry together. The analyzer commits features, alerts, and job completion together. Errors roll back and eligible jobs retry with backoff. This design avoids a separate queue service and cross-system write coordination for a small deployment. Run one collector per workspace. The application serializes writes per watchlist.

The detector orders posts by event time in a bounded 24-hour evaluation window. It compares candidates drawn from nearby time buckets using SimHash bands, exact URLs, and optional semantic similarity. The default needs three connected accounts and two distinct synchronous rounds per coordination edge. The graph preserves actual reply, quote, repost, and like evidence separately. Reviewers can inspect exact intervals, shared domains and destinations, similarity, record timestamps, DIDs, AT URIs and CIDs. Priority is a triage rule based on group size or edge count. See [detection and evaluation](docs/evaluation.md) for the definitions and limits.

## Optional research and embeddings

- The original classifier, generator, and notebook are preserved in [legacy](legacy/README.md). Its metrics reflect generated profiles.
- The TwiBot-22 research command requires an approved local dataset. It runs a rule, Isolation Forest, and calibrated XGBoost, writes a versioned report and artifacts, and tracks the experiment with MLflow. See [dataset access and model documentation](docs/models.md).
- For optional CPU sentence embeddings, install `requirements-semantic.txt` and point `SEMANTIC_MODEL` to a pinned local model directory such as a snapshot of `sentence-transformers/all-MiniLM-L6-v2`. For Compose, place the snapshot under `artifacts`, set `INSTALL_SEMANTIC=1`, and set `SEMANTIC_MODEL=/app/artifacts/<snapshot>`. The analyzer loads the snapshot locally and records whether it contributed to candidate generation. The default detector works without model downloads.

## Verification and operation

```sh
# A dedicated test database is required. The tests truncate its watchlist tables.
python -m pip install -r requirements-dev.txt "pandas>=2.2,<3"
TEST_DATABASE_URL=postgresql://user:password@127.0.0.1/test python -m pytest -q
python -m integrity.evaluation
python -m integrity probe

# Optional live check with a dedicated database. It drops the temporary watchlist after the check.
python -m integrity.live_smoke --did did:plc:REPLACE_WITH_AN_ACTIVE_PUBLIC_DID
# Or explicitly authorize a 30-second topical scan
python -m integrity.live_smoke --keyword the

cd web
npm ci
npm run build
npx playwright install chromium
E2E_REVIEWER_TOKEN=your-local-fixture-token npm test
```

Use PowerShell's `$env:NAME = 'value'` on Windows. Playwright uses the fixture workspace at port 5173 unless `E2E_URL` is set. CI runs PostgreSQL integration tests and the browser workflow.

FastAPI serves health and reviewer session endpoints, watchlists, alert queries and evidence, account snapshots, review history, and evaluation metrics under `/api`. All workspace data and mutations require a reviewer token. Source posts render as escaped text. Shared destinations remain plain text and are never fetched by the application. Links to originals use a fixed Bluesky origin. Browser tokens remain in memory. Use TLS and a trusted ingress if the service is shared across machines, and rotate reviewer tokens through the server configuration. The local deployment uses a single team workspace.

Retention defaults to 14 days with a 1–30 day range. Hourly maintenance expires underlying records and related evidence. Source deletions and deactivation remove retained content and affected alert snapshots, including reviews attached to those snapshots. Deleting a watchlist cascades through records, queue state, features, investigations, and notes. External evidence exports are controlled by the recipient. Avoid retaining more public material than the investigation requires.

Use reviewer outcomes as group-level decisions. Preserve context for ambiguous cases, and keep fixtures separate from any effectiveness evaluation. This tool has no account enforcement integration.
