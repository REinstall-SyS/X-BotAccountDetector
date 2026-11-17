import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { formatDate, percent, useQuery } from './data'
import type { Account, Watchlist } from './types'
import { ActivityList, Badge, Empty, ErrorState, Loading, PageTitle } from './ui'

export function Accounts({ token }: { token: string }) {
  const [params, setParams] = useSearchParams()
  const activeWatch = params.get('watchlist') || ''
  const activeDid = params.get('did') || ''
  const lists = useQuery<Watchlist[]>(token, '/watchlists')
  const [watch, setWatch] = useState(activeWatch)
  const [did, setDid] = useState(activeDid)
  const [window, setWindow] = useState('24h')
  const activity = useQuery<Account>(token, activeWatch && activeDid ?
    '/watchlists/' + encodeURIComponent(activeWatch) + '/account?did=' + encodeURIComponent(activeDid) : null)
  const snapshot = activity.data?.snapshot
  const stats = snapshot?.features[window]
  const max = Math.max(1, ...(stats?.utc_hour_counts || []))
  return <>
    <PageTitle title="Account Analysis" description="Inspect activity within a specific watchlist’s retained sample." />
    <section className="card section">
      <form className="filter-bar" onSubmit={e => { e.preventDefault(); setParams({ watchlist: watch, did: did.trim() }) }}>
        <label>Watchlist<select required value={watch} onChange={e => setWatch(e.target.value)}>
          <option value="">Select a watchlist</option>{lists.data?.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}</select></label>
        <label className="grow">Public account DID<input required value={did} maxLength={255} onChange={e => setDid(e.target.value)} placeholder="did:plc:…" /></label>
        <button className="button primary">Find activity</button>
      </form>
    </section>
    {(activity.error || lists.error) && <ErrorState>{activity.error || lists.error}</ErrorState>}
    {activeDid && !activity.data && !activity.error && activeWatch && <Loading />}
    {activity.data && <>
      <section className="card section">
        <div className="section-heading"><div><h2>Observed behavior</h2><p className="wrap-anywhere">{activity.data.did} · {activity.data.watchlist.name}</p></div>
          <select aria-label="Activity window" value={window} onChange={e => setWindow(e.target.value)}><option value="1h">1 hour</option><option value="24h">24 hours</option><option value="168h">7 days</option></select></div>
        {!stats || !snapshot ? <Empty>No recent features for this DID in the watchlist.</Empty> : <div className="section-body">
          {activity.data.watchlist.source === 'fixture' && <Badge tone="fixture">Synthetic fixture</Badge>}
          <dl className="metric-grid"><div><dt>Observed posts</dt><dd>{stats.posts}</dd></div>
            <div><dt>Posts per hour</dt><dd>{stats.posts_per_hour}</dd></div>
            <div><dt>Typical interval</dt><dd>{stats.median_interval_seconds === null ? '—' : Math.round(stats.median_interval_seconds) + 's'}</dd></div>
            <div><dt>Repeated text</dt><dd>{percent(stats.repeat_ratio)}</dd></div>
            <div><dt>Posts with URLs</dt><dd>{stats.posts_with_urls}</dd></div>
            <div><dt>Interaction concentration</dt><dd>{percent(stats.interaction_concentration)}</dd></div>
          </dl>
          <h3>Posting hour (UTC)</h3>
          <div className="histogram" role="img" aria-label={'Posting counts by UTC hour, starting at midnight: ' + stats.utc_hour_counts.join(', ')}>
            {stats.utc_hour_counts.map((count, hour) => <div key={hour} title={hour + ':00 UTC · ' + count + ' posts'}><i style={{ height: Math.max(2, 100 * count / max) + '%' }} /></div>)}</div>
          <div className="histogram-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>
          <p className="subtle">As of {formatDate(snapshot.as_of)} · {stats.time_fallbacks} stream timestamps used as fallback. Blank measures indicate insufficient data.</p>
        </div>}
      </section>
      <section className="card section"><div className="section-heading"><div><h2>Related investigations</h2><p>Review the relationship evidence involving this account.</p></div></div>
        {activity.data.investigations.length ? <ul className="line-list">{activity.data.investigations.map(item => <li key={item.id}>
          <Link className="row-title" to={'/investigations/' + item.id}>Investigation {item.id} · {formatDate(item.last_at)}</Link>
          <Badge tone={item.status}>{item.status}</Badge></li>)}</ul> : <Empty>No retained investigations cite this account.</Empty>}
      </section>
      <section className="card section"><div className="section-heading"><div><h2>Retained activity</h2><p>Latest {activity.data.records.length} matching records.</p></div></div>
        <ActivityList records={activity.data.records} fixture={activity.data.watchlist.source === 'fixture'} /></section>
    </>}
  </>
}
