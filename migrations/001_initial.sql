CREATE TABLE watchlists (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text UNIQUE NOT NULL,
    scope jsonb NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    policy jsonb NOT NULL,
    source text NOT NULL CHECK (source IN ('bluesky', 'fixture')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE checkpoints (
    watchlist_id bigint REFERENCES watchlists ON DELETE CASCADE,
    stream text NOT NULL,
    seq bigint NOT NULL,
    observed_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (watchlist_id, stream)
);
CREATE TABLE ingestion_health (
    watchlist_id bigint PRIMARY KEY REFERENCES watchlists ON DELETE CASCADE,
    state text NOT NULL,
    scanned bigint NOT NULL DEFAULT 0,
    matched bigint NOT NULL DEFAULT 0,
    invalid bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE records (
    watchlist_id bigint REFERENCES watchlists ON DELETE CASCADE,
    uri text NOT NULL,
    did text NOT NULL,
    seq bigint NOT NULL,
    event_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    deleted boolean NOT NULL,
    record jsonb,
    PRIMARY KEY (watchlist_id, uri)
);
CREATE INDEX records_window ON records (watchlist_id, event_at DESC) WHERE NOT deleted;
CREATE INDEX records_account ON records (watchlist_id, did, event_at DESC) WHERE NOT deleted;
CREATE INDEX records_retention ON records (observed_at);
CREATE TABLE analysis_queue (
    watchlist_id bigint PRIMARY KEY REFERENCES watchlists ON DELETE CASCADE,
    queued_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE account_features (
    watchlist_id bigint REFERENCES watchlists ON DELETE CASCADE,
    did text NOT NULL,
    as_of timestamptz NOT NULL,
    features jsonb NOT NULL,
    PRIMARY KEY (watchlist_id, did)
);
CREATE TABLE alerts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    watchlist_id bigint REFERENCES watchlists ON DELETE CASCADE,
    fingerprint text NOT NULL,
    episode date NOT NULL,
    first_at timestamptz NOT NULL,
    last_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    priority text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'dismissed', 'inconclusive')),
    evidence jsonb NOT NULL,
    evidence_uris text[] NOT NULL,
    UNIQUE (watchlist_id, fingerprint, episode)
);
CREATE INDEX alerts_queue ON alerts (watchlist_id, created_at DESC, id DESC);
CREATE INDEX alerts_evidence ON alerts USING gin (evidence_uris);
CREATE TABLE reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id bigint REFERENCES alerts ON DELETE CASCADE,
    reviewed_at timestamptz NOT NULL DEFAULT now(),
    reviewer text NOT NULL,
    status text NOT NULL,
    note varchar(4000) NOT NULL
);
CREATE INDEX reviews_alert ON reviews (alert_id, id);
CREATE TABLE analysis_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    watchlist_id bigint REFERENCES watchlists ON DELETE CASCADE,
    analyzed_at timestamptz NOT NULL DEFAULT now(),
    candidates integer NOT NULL,
    duplicates integer NOT NULL,
    latency_seconds double precision NOT NULL,
    sample_size integer NOT NULL,
    truncated boolean NOT NULL
);
CREATE INDEX analysis_runs_retention ON analysis_runs (analyzed_at);
