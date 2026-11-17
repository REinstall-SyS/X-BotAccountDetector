import { Activity, ArrowRight, Clock3, ListChecks, Radio, ScanLine, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { formatDate, percent, request, useQuery } from './data'
import type { Alert, Metrics, Source, Watchlist } from './types'
import { AlertRows, Badge, Empty, ErrorState, Loading, PageTitle, Stat } from './ui'

export function Overview({ token, mode }: { token: string; mode: Source }) {
  const watch = useQuery<Watchlist[]>(token, '/watchlists', 4000)
  const metric = useQuery<Metrics>(token, '/metrics?source=' + mode, 4000)
  const alerts = useQuery<Alert[]>(token, '/alerts?limit=8&source=' + mode, 4000)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const sample = async () => {
    setLoading(true); setError('')
    try {
      await request(token, '/fixtures', { method: 'POST' })
      watch.reload(); metric.reload(); alerts.reload()
      setLoaded(true)
    } catch (error) { setError((error as Error).message) }
    finally { setLoading(false) }
  }
  const health = watch.data?.filter(w => w.source === mode) || []
  const active = health.filter(w => w.enabled)
  const observed = health.reduce((total, w) => total + (w.matched || 0), 0)
  return <>
    <PageTitle title="Overview" description="Monitor public activity and triage evidence-backed coordination alerts."
      actions={<><Link className="button secondary" to="/settings">Manage watchlists</Link>
        {mode === 'fixture' && <button className="button primary" onClick={sample} disabled={loading}><ScanLine size={17} />{loading ? 'Loading…' : 'Load fixture'}</button>}</>} />
    {error && <ErrorState>{error}</ErrorState>}
    {mode === 'fixture' && <div className="notice"><span className="notice-icon"><ScanLine size={19} /></span><div>
      <strong>Offline fixture workspace</strong><p>{loaded ? 'Fixture records queued. Investigations update automatically.' : 'Load the synthetic sample to investigate a repeated posting pattern and try the review workflow.'}</p>
    </div><Badge tone="fixture">Synthetic data</Badge></div>}
    <section className="stat-grid" aria-label="Workspace metrics">
      <Stat label="Matched events" value={watch.data ? observed.toLocaleString() : '—'} hint="Lifetime watchlist matches" icon={<Radio size={17} />} />
      <Stat label="Open investigations" value={metric.data?.pending ?? '—'} hint="Pending within the last 7 days" icon={<ListChecks size={17} />} />
      <Stat label="Enabled watchlists" value={watch.data ? active.length : '—'} hint={mode === 'fixture' ? 'Offline fixture mode' : 'Public Bluesky activity'} icon={<Activity size={17} />} />
      <Stat label="Median queue lag" value={metric.data?.median_lag_seconds != null ? metric.data.median_lag_seconds.toFixed(1) + 's' : '—'} hint="Time awaiting analysis · 7 days" icon={<Clock3 size={17} />} />
    </section>
    <section className="card section">
      <div className="section-heading"><div><h2>Recent investigations</h2><p>Review the latest evidence from active watchlists.</p></div>
        <Link to="/investigations" className="button secondary">View queue <ArrowRight size={16} /></Link></div>
      {alerts.error ? <ErrorState>{alerts.error}</ErrorState> : alerts.data ? <AlertRows alerts={alerts.data} /> : <Loading />}
    </section>
    <div className="split">
      <section className="card section">
        <div className="section-heading"><div><h2>Ingestion health</h2><p>Latest status reported by each watchlist.</p></div><Radio size={18} className="subtle" /></div>
        {watch.error ? <ErrorState>{watch.error}</ErrorState> : !watch.data ? <Loading /> : !health.length ? <Empty>Add a watchlist to see collection status.</Empty> :
          <ul className="line-list">{health.map(w => <li key={w.id}><div><strong>{w.name}</strong>
          <small>{w.cursor_time ? 'Last observed ' + formatDate(w.cursor_time) : 'Waiting for first event'} · {w.invalid || 0} invalid{w.analysis_failures > 0 ? ' · analysis retrying' : ''}</small></div>
            <Badge tone={w.enabled && w.state === 'streaming' ? 'confirmed' : 'neutral'}>{w.enabled ? w.state || 'waiting' : 'paused'}</Badge></li>)}</ul>}
      </section>
      <section className="card section">
        <div className="section-heading"><div><h2>Review outcomes</h2><p>Current outcomes for alerts from the last 7 days.</p></div><ShieldCheck size={18} className="subtle" /></div>
        {metric.error ? <ErrorState>{metric.error}</ErrorState> : !metric.data ? <Loading /> :
          <ul className="line-list">{(['confirmed', 'dismissed', 'inconclusive'] as const).map(key => (
            <li key={key}><Badge tone={key}>{key}</Badge><strong>{metric.data![key]}</strong></li>
          ))}</ul>}
      </section>
    </div>
  </>
}

export function ModelLab({ token, mode }: { token: string; mode: Source }) {
  const [source, setSource] = useState(mode)
  const metrics = useQuery<Metrics>(token, '/metrics?source=' + source, 5000)
  const inventory = useQuery<{ detector: string; semantic_enabled: boolean; research: import('./types').Report[] }>(token, '/models')
  const drift = useQuery<{ watchlist_id: number; name: string; shift: number | null; current?: { n: number }; reference?: { n: number } }[]>(token, '/drift')
  const m = metrics.data
  return <>
    <PageTitle title="Model Lab" description="Inspect detector versions, supervised research runs, and human review metrics." />
    {inventory.error && <ErrorState>{inventory.error}</ErrorState>}
    <section className="card section">
      <div className="section-heading"><div><h2>Live detector</h2><p>Each alert records its policy and operating version.</p></div>
        <Badge tone="confirmed">{inventory.data?.detector || 'Loading'}</Badge></div>
      <div className="section-body"><p>SimHash, shared destinations, posting intervals and graph connectivity. Sentence embeddings {inventory.data?.semantic_enabled ? 'enabled' : 'disabled'}.</p>
        <p className="subtle">Investigations surface repeated signals for review. A signal alone cannot establish automation or intent.</p>
        {!!m?.truncated_runs && <ErrorState>{m.truncated_runs} analysis runs reached the sample cap in the past 7 days. Watchlist coverage is incomplete.</ErrorState>}
      </div>
    </section>
    <section className="section card">
      <div className="section-heading"><div><h2>Investigation evaluation</h2><p>Rolling 7-day window. Decisions reflect the reviewers’ assessment of the evidence.</p></div>
        <select aria-label="Evaluation source" value={source} onChange={e => setSource(e.target.value as Source)}><option value="bluesky">Public Bluesky</option><option value="fixture">Synthetic fixture</option></select></div>
      {metrics.error ? <ErrorState>{metrics.error}</ErrorState> : !m ? <Loading /> :
        <div className="section-body"><dl className="metric-grid">
          <div><dt>Alert volume</dt><dd>{m.alert_volume}</dd></div>
          <div><dt>Duplicate candidate rate</dt><dd>{percent(m.duplicate_rate)}</dd></div>
          <div><dt>Median processing time</dt><dd>{m.median_processing_seconds?.toFixed(2) ?? '—'}{m.median_processing_seconds !== null && 's'}</dd></div>
          <div><dt>Dismissal rate</dt><dd>{percent(m.dismissal_rate)}</dd><small>{m.decisive} decisive outcomes</small></div>
          <div><dt>Reviewer workload</dt><dd>{m.actions} {m.actions === 1 ? 'action' : 'actions'}</dd><small>{m.reviewers} reviewers · {m.pending} pending</small></div>
          <div><dt>Review-based precision @ 10</dt><dd>{percent(m.precision_at_10)}</dd><small>{m.top_10_adjudicated} of {m.top_10_count} ranked alerts independently decided</small></div>
        </dl>{m.decisive < 30 && <p className="subtle">Small review sample. Reported proportions are descriptive.</p>}</div>}
    </section>
    <section className="section card">
      <div className="section-heading"><div><h2>Input drift</h2><p>Share of Bluesky posts with URLs, comparing the last 24 hours with the preceding 6 days.</p></div></div>
      {drift.error ? <ErrorState>{drift.error}</ErrorState> : !drift.data ? <Loading /> : drift.data.length ? <ul className="line-list">
        {drift.data.map(item => <li key={item.watchlist_id}><div><strong>{item.name}</strong>
          <small>{item.current?.n || 0} recent · {item.reference?.n || 0} reference posts</small></div>
          <Badge tone={item.shift !== null && Math.abs(item.shift) >= .2 ? 'high' : 'neutral'}>
            {item.shift === null ? 'Insufficient history' : (item.shift > 0 ? '+' : '') + (100 * item.shift).toFixed(1) + ' pp'}
          </Badge></li>)}
        </ul> : <Empty>Collect live activity to monitor drift.</Empty>}
    </section>
    <section className="section card">
      <div className="section-heading"><div><h2>Supervised benchmarks</h2><p>TwiBot-22 research · historical Twitter account labels</p></div><Badge>Research only</Badge></div>
      {!inventory.data?.research.length ? <Empty>No approved labeled dataset run is available.</Empty> : inventory.data.research.map(report =>
        <div className="section-body" key={report.version}><h3>{report.dataset} · {report.version}</h3>
          <div className="scroll-x"><table><thead><tr><th>Experiment</th><th>Precision</th><th>Recall</th><th>F1</th><th>PR-AUC</th></tr></thead>
            <tbody>{Object.entries(report.experiments).map(([name, values]) => <tr key={name}><td>{name}</td>
              <td>{percent(values.precision)}</td><td>{percent(values.recall)}</td><td>{percent(values.f1)}</td><td>{percent(values.pr_auc)}</td></tr>)}</tbody></table></div>
          {report.shap_mean_absolute && <><h3>Mean absolute TreeSHAP contribution</h3>
            <dl className="metric-grid">{Object.entries(report.shap_mean_absolute).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value.toFixed(3)}</dd></div>)}</dl></>}
        </div>)}
    </section>
    <section className="section card"><div className="section-heading"><div><h2>Legacy synthetic classifier</h2>
      <p>Repository research baseline. Run it separately to reproduce results on generated profiles.</p></div><Badge tone="fixture">Synthetic only</Badge></div></section>
  </>
}
