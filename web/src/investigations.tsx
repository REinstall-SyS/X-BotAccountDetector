import { lazy, Suspense, useEffect, useState } from 'react'
import { ArrowDownRight, ArrowLeft, Download, GitFork, ListChecks, Network, UsersRound } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { didLabel, formatDate, request, useQuery } from './data'
import type { Alert, Edge, Investigation, Status, Watchlist } from './types'
import { ActivityList, AlertRows, Badge, Empty, ErrorState, Loading, PageTitle, Stat } from './ui'

const Graph = lazy(() => import('./graph'))

export function Queue({ token }: { token: string }) {
  const lists = useQuery<Watchlist[]>(token, '/watchlists')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [watchlist, setWatchlist] = useState('')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [page, setPage] = useState(0)
  const filters = new URLSearchParams({ offset: String(page * 25), limit: '25' })
  if (status) filters.set('status', status)
  if (priority) filters.set('priority', priority)
  if (watchlist) filters.set('watchlist_id', watchlist)
  if (since) filters.set('since', new Date(since + 'T00:00:00').toISOString())
  if (until) filters.set('until', new Date(until + 'T23:59:59.999').toISOString())
  const rows = useQuery<Alert[]>(token, '/alerts?' + filters.toString(), 8000)
  return <>
    <PageTitle title="Investigations" description="Filter the queue to decide which groups need review." />
    <section className="card section">
      <div className="filter-bar">
        <label>Watchlist<select value={watchlist} onChange={e => { setPage(0); setWatchlist(e.target.value) }}><option value="">All watchlists</option>
          {lists.data?.map(w => <option value={w.id} key={w.id}>{w.name}</option>)}</select></label>
        <label>Review status<select value={status} onChange={e => { setPage(0); setStatus(e.target.value) }}><option value="">Any status</option>
          {['pending', 'confirmed', 'dismissed', 'inconclusive'].map(s => <option key={s}>{s}</option>)}</select></label>
        <label>Priority<select value={priority} onChange={e => { setPage(0); setPriority(e.target.value) }}><option value="">Any priority</option><option>routine</option><option>high</option></select></label>
        <label>From<input type="date" value={since} max={until || undefined} onChange={e => { setPage(0); setSince(e.target.value) }} /></label>
        <label>Through<input type="date" value={until} min={since || undefined} onChange={e => { setPage(0); setUntil(e.target.value) }} /></label>
      </div>
      {lists.error && <ErrorState>{lists.error}</ErrorState>}
      {rows.error ? <ErrorState>{rows.error}</ErrorState> : rows.data ? <AlertRows alerts={rows.data} /> : <Loading />}
      <div className="pagination"><button className="button secondary" onClick={() => setPage(page - 1)} disabled={!page}>Previous</button>
        <span>Page {page + 1}</span><button className="button secondary" onClick={() => setPage(page + 1)} disabled={(rows.data?.length || 0) < 25 || page >= 400}>Next</button></div>
    </section>
  </>
}

function EdgeDetails({ edge }: { edge: Edge }) {
  return <div className="edge-detail">
    <h3>{didLabel(edge.source)} <span>↔</span> {didLabel(edge.target)}</h3>
    <p className="subtle">{edge.matches.length} separated matches · {edge.interactions.length} direct interactions</p>
    <ul className="edge-list">{edge.matches.map(match => <li key={match.left + match.right}>
      <strong>{match.interval_seconds}s apart</strong>
      <div className="chips">
        {match.shared_urls.length > 0 && <Badge tone="confirmed">{match.shared_urls.length} shared {match.shared_urls.length === 1 ? 'URL' : 'URLs'}</Badge>}
        {match.simhash_distance !== null && <Badge>SimHash distance {match.simhash_distance}/64</Badge>}
        {match.cosine !== null && <Badge>Cosine {match.cosine}</Badge>}
      </div>
      {match.shared_urls.map(url => <code key={url}>{url}</code>)}
      {!match.shared_urls.length && match.shared_domains.length > 0 && <code>Shared domains · {match.shared_domains.join(', ')}</code>}
      <a className="text-link" href={'#' + encodeURIComponent(encodeURIComponent(match.left))}>Find the earlier record <ArrowDownRight size={13} /></a>
    </li>)}
    {edge.interactions.map(item => <li key={item.kind + item.record}><strong>{item.kind}</strong><code>{item.target}</code></li>)}</ul>
  </div>
}

export function Explorer({ token, graphOnly = false }: { token: string; graphOnly?: boolean }) {
  const { id } = useParams()
  const query = useQuery<Investigation>(token, id ? '/alerts/' + id : null)
  const options = useQuery<Alert[]>(token, id ? null : '/alerts?limit=40')
  const [selected, setSelected] = useState(0)
  const [note, setNote] = useState('')
  const [outcome, setOutcome] = useState<Status>('confirmed')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setSelected(0); setNote(''); setError(''); setOutcome('confirmed') }, [id])
  if (!id) return <><PageTitle title="Cluster Explorer" description="Open an investigation to inspect its account network and recorded relationships." />
    <section className="card section">{options.error ? <ErrorState>{options.error}</ErrorState> : options.data ?
      <ul className="line-list">{options.data.length ? options.data.map(row => <li key={row.id}><div><Link className="row-title" to={'/clusters/' + row.id}>{row.topic}</Link>
        <small>{row.accounts} accounts · {row.edges} relationships</small></div><Badge tone={row.status}>{row.status}</Badge></li>) : <li><Empty>No clusters to explore.</Empty></li>}</ul> : <Loading />}</section></>
  if (query.error) return <ErrorState>{query.error}</ErrorState>
  if (!query.data) return <Loading />
  const alert = query.data
  const edge = alert.evidence.edges[selected] || alert.evidence.edges[0]
  const focus = edge ? edge.matches.flatMap(item => [item.left, item.right]).concat(edge.interactions.map(item => item.record)) : []
  const save = async () => {
    setError(''); setBusy(true)
    try {
      await request(token, '/alerts/' + id + '/reviews', { method: 'POST', body: JSON.stringify({
        status: alert.status === 'pending' ? outcome : 'pending', expected_status: alert.status, note,
      }) })
      setNote(''); query.reload()
    } catch (error) { setError((error as Error).message); query.reload() }
    finally { setBusy(false) }
  }
  const exportEvidence = async () => {
    try {
      const report = await request<object>(token, '/alerts/' + id + '/export')
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = 'investigation-' + id + '.json'; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 3000)
    } catch (error) { setError((error as Error).message) }
  }
  return <>
    <Link to={graphOnly ? '/clusters' : '/investigations'} className="back"><ArrowLeft size={16} />{graphOnly ? 'All clusters' : 'Investigation queue'}</Link>
    <PageTitle title={alert.topic} description={'Repeated synchronized activity · ' + formatDate(alert.first_at) + ' through ' + formatDate(alert.last_at)}
      actions={<button className="button secondary" onClick={exportEvidence}><Download size={17} />Export evidence</button>} />
    <div className="chips mb-5"><Badge tone={alert.status}>{alert.status}</Badge><Badge tone={alert.priority}>{alert.priority} priority</Badge>
      {alert.source === 'fixture' && <Badge tone="fixture">Synthetic fixture</Badge>}<Badge>{alert.evidence.detector}</Badge></div>
    {error && <ErrorState>{error}</ErrorState>}
    <div className="stat-grid triple">
      <Stat label="Accounts" value={alert.evidence.accounts.length} hint="Connected by repeated overlap" icon={<UsersRound size={16} />} />
      <Stat label="Relationships" value={alert.evidence.edges.length} hint="Coordination and public interactions" icon={<GitFork size={16} />} />
      <Stat label="Evidence records" value={alert.evidence.records.length} hint="Retained public record references" icon={<ListChecks size={16} />} />
    </div>
    <div className="split wide-left">
      <section className="section card"><div className="section-heading"><div><h2>Account network</h2><p>Select an edge to inspect its evidence.</p></div><Network size={20} /></div>
        <Suspense fallback={<Loading />}><Graph alert={alert} selected={selected} choose={setSelected} /></Suspense>
      </section>
      <section className="section card"><div className="section-heading"><div><h2>Relationship evidence</h2><p>Matches within {alert.evidence.policy.sync_seconds} seconds, repeated across distinct rounds.</p></div></div>
        <div className="section-body"><label>Account pair<select value={selected} onChange={e => setSelected(Number(e.target.value))}>
          {alert.evidence.edges.map((item, index) => <option key={item.source + item.target} value={index}>{didLabel(item.source)} ↔ {didLabel(item.target)}</option>)}
        </select></label>{edge && <EdgeDetails edge={edge} />}</div>
      </section>
    </div>
    <div className="split wide-left"><section className="section card">
      <div className="section-heading"><div><h2>Evidence timeline</h2><p>Highlighted records support the selected relationship. Times are displayed in your timezone.</p></div></div>
      <ActivityList records={alert.evidence.records} fixture={alert.source === 'fixture'} watchlist={alert.watchlist_id} focus={focus} />
    </section><section className="section card">
      <div className="section-heading"><div><h2>Human review</h2><p>Consider shared context, legitimate announcements and incomplete coverage before recording a decision.</p></div></div>
      <div className="section-body">
        <form className="form-stack" onSubmit={event => { event.preventDefault(); void save() }}>
          {alert.status === 'pending' && <label>Outcome<select value={outcome} onChange={e => setOutcome(e.target.value as Status)}>
            <option value="confirmed">Confirmed</option><option value="dismissed">Dismissed</option><option value="inconclusive">Inconclusive</option></select></label>}
          <label>Investigation note<textarea required value={note} maxLength={4000} onChange={e => setNote(e.target.value)} rows={4}
            placeholder="Summarize the evidence and context behind your decision." /></label>
          <button className="button primary" disabled={busy || !note.trim()}>{alert.status === 'pending' ? 'Record outcome' : 'Reopen investigation'}</button>
        </form>
        {alert.reviews.map((review, index) => <div className="review" key={index}>
          <div><strong>{review.reviewer}</strong> <Badge tone={review.status}>{review.status}</Badge></div>
          <small>{formatDate(review.reviewed_at)}</small><p>{review.note}</p>
        </div>)}
      </div>
    </section></div>
  </>
}
