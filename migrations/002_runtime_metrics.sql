ALTER TABLE analysis_runs ADD COLUMN duration_seconds double precision;
ALTER TABLE analysis_queue ADD COLUMN failures integer NOT NULL DEFAULT 0;
ALTER TABLE analysis_queue ADD COLUMN available_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX records_watchlist_obs ON records (watchlist_id, observed_at DESC) WHERE NOT deleted;
