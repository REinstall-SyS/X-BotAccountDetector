export type Status = 'pending' | 'confirmed' | 'dismissed' | 'inconclusive'
export type Source = 'fixture' | 'bluesky'
export type Scope = { dids: string[]; keywords: string[]; hashtags: string[]; domains: string[]; urls: string[] }
export type Policy = { min_accounts: number; min_rounds: number; sync_seconds: number; max_per_minute: number; retention_days: number }
export type Watchlist = {
  id: number; name: string; source: Source; scope: Scope; enabled: boolean; policy: Policy;
  state: string | null; matched: number | null; scanned: number | null; invalid: number | null;
  heartbeat: string | null; cursor_time: string | null; analysis_failures: number;
}
export type Activity = {
  uri: string; did: string; collection: string; cid: string | null; event_at: string; observed_at: string;
  text: string; urls: string[]; domains: string[]; refs: Record<string, string>; time_source: 'record' | 'stream'
}
export type Edge = {
  source: string; target: string
  matches: { left: string; right: string; interval_seconds: number; shared_urls: string[]; shared_domains: string[];
    simhash_distance: number | null; cosine: number | null }[]
  interactions: { kind: string; record: string; target: string }[]
}
export type Alert = {
  id: number; watchlist_id: number; topic: string; source: Source; status: Status; priority: 'high' | 'routine';
  first_at: string; last_at: string; created_at: string; accounts: number; edges: number; preview?: string; signals: string[];
}
export type Investigation = Omit<Alert, 'accounts' | 'edges' | 'preview' | 'signals'> & {
  evidence: { accounts: string[]; edges: Edge[]; records: Activity[]; detector: string; density: number; policy: Policy };
  reviews: { reviewer: string; status: Status; note: string; reviewed_at: string }[]
}
export type Metrics = {
  alert_volume: number; pending: number; confirmed: number; dismissed: number; inconclusive: number;
  candidates: number | null; duplicates: number | null; duplicate_rate: number | null; median_lag_seconds: number | null;
  median_processing_seconds: number | null; truncated_runs: number; runs: number; source: Source; actions: number; reviewers: number; decisive: number;
  dismissal_rate: number | null; precision_at_10: number | null; top_10_count: number; top_10_adjudicated: number;
}
export type Snapshot = {
  posts: number; posts_per_hour: number; median_interval_seconds: number | null; interval_cv: number | null;
  utc_hour_counts: number[]; repeat_ratio: number | null; posts_with_urls: number; top_domains: [string, number][];
  interaction_concentration: number | null; time_fallbacks: number;
}
export type Account = {
  did: string; watchlist: { name: string; source: Source };
  snapshot: { as_of: string; features: Record<string, Snapshot> } | null; records: Activity[];
  investigations: Pick<Alert, 'id' | 'status' | 'priority' | 'last_at'>[]
}
export type Report = {
  dataset: string; version: string; split_sizes: Record<string, number>;
  experiments: Record<string, { precision: number; recall: number; f1: number; pr_auc: number; confusion: number[][] }>;
  shap_mean_absolute?: Record<string, number>;
}
