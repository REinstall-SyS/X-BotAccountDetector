import { ArrowDownRight, ArrowUpRight, CircleAlert, Inbox, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { didLabel, formatDate, formatTime, publicLink } from './data'
import type { Activity, Alert } from './types'

export function PageTitle({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <div className="page-title"><div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="actions">{actions}</div>}</div>
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={'badge badge-' + tone}>{children}</span>
}

export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint: string; icon?: ReactNode }) {
  return <div className="card stat"><div className="stat-label">{label}{icon && <div className="stat-icon">{icon}</div>}</div><strong>{value}</strong><span>{hint}</span></div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><Inbox size={21} />{children}</div>
}

export function ErrorState({ children }: { children: ReactNode }) {
  return <div className="error" role="alert"><CircleAlert size={17} />{children}</div>
}

export function Loading() {
  return <div className="empty" role="status"><LoaderCircle className="animate-spin" size={20} />Loading workspace…</div>
}

export function AlertRows({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return <Empty>No investigations match this view.</Empty>
  return <div className="scroll-x"><table><thead><tr><th>Investigation</th><th>Accounts</th><th>Priority</th><th>Review</th><th>Last activity</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>
    {alerts.map(alert => <tr key={alert.id}>
      <td><Link className="row-title" to={'/investigations/' + alert.id}>{alert.topic}</Link>
        <div className="row-preview">{alert.source === 'fixture' ? 'Synthetic fixture · ' : ''}{alert.preview || 'Repeated synchronized activity'}</div>
        {alert.signals.length > 0 && <div className="chips mt-1">{alert.signals.map(signal => <Badge key={signal}>{signal}</Badge>)}</div>}</td>
      <td className="mono">{alert.accounts}</td>
      <td><Badge tone={alert.priority}>{alert.priority}</Badge></td>
      <td><Badge tone={alert.status}>{alert.status}</Badge></td>
      <td className="subtle nowrap">{formatDate(alert.last_at)}</td>
      <td><Link title={'Open ' + alert.topic} aria-label={'Open investigation ' + alert.id} className="icon-button" to={'/investigations/' + alert.id}><ArrowUpRight size={17} /></Link></td>
    </tr>)}
  </tbody></table></div>
}

export function ActivityList({ records, fixture = false, watchlist, focus = [] }: {
  records: Activity[]; fixture?: boolean; watchlist?: number; focus?: string[]
}) {
  if (!records.length) return <Empty>No activity in the retained watchlist sample.</Empty>
  return <ol className="timeline">{records.map(record => {
    const href = !fixture && publicLink(record.uri)
    return <li key={record.uri} id={encodeURIComponent(record.uri)} className={focus.includes(record.uri) ? 'highlight' : ''}>
      <div className="activity-head"><time dateTime={record.event_at}>{formatTime(record.event_at)}</time>
        {watchlist ? <Link title={record.did} to={'/accounts?watchlist=' + watchlist + '&did=' + encodeURIComponent(record.did)}>{didLabel(record.did)}</Link> : <span title={record.did}>{didLabel(record.did)}</span>}
        {record.time_source === 'stream' && <Badge>Stream time</Badge>}
        {href && <a href={href} target="_blank" rel="noreferrer" title="Open original Bluesky post" aria-label="Open original Bluesky post"><ArrowUpRight size={16} /></a>}
      </div>
      <p>{record.text || record.collection.split('.').at(-1)}</p>
      {record.domains.length > 0 && <div className="chips">{record.domains.map(domain => <Badge key={domain}>{domain}</Badge>)}</div>}
      {Object.entries(record.refs).map(([kind, ref]) => <div className="reference" key={kind}><ArrowDownRight size={13} />{kind} <code>{ref}</code></div>)}
    </li>
  })}</ol>
}
