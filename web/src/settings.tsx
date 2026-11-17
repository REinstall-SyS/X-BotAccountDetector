import * as Dialog from '@radix-ui/react-dialog'
import { Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { request, useQuery } from './data'
import type { Policy, Scope, Source, Watchlist } from './types'
import { Badge, Empty, ErrorState, Loading, PageTitle } from './ui'

const defaults: Policy = { min_accounts: 3, min_rounds: 2, sync_seconds: 90, max_per_minute: 120, retention_days: 14 }
const bounds = [
  ['min_accounts', 'Minimum accounts', 3, 20],
  ['min_rounds', 'Required rounds per pair', 2, 8],
  ['sync_seconds', 'Maximum interval (seconds)', 10, 300],
  ['max_per_minute', 'Maximum new records per minute', 10, 300],
  ['retention_days', 'Retention (days)', 1, 30],
] as const

function PolicyFields({ policy, update }: { policy: Policy; update: (next: Policy) => void }) {
  return <div className="form-grid">{bounds.map(([key, label, min, max]) =>
    <label key={key}>{label}<input type="number" required value={Number.isNaN(policy[key]) ? '' : policy[key]} min={min} max={max}
      onChange={e => update({ ...policy, [key]: e.target.valueAsNumber })} /></label>
  )}</div>
}

function DeleteWatchlist({ name, remove }: { name: string; remove: () => Promise<boolean> }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  return <Dialog.Root open={open} onOpenChange={setOpen}>
    <Dialog.Trigger asChild><button type="button" className="button secondary danger"><Trash2 size={16} />Delete watchlist</button></Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="modal-overlay" />
      <Dialog.Content className="card modal">
        <Dialog.Title>Delete {name}?</Dialog.Title>
        <Dialog.Description>This removes the watchlist, its collected records, investigations, and reviewer notes.</Dialog.Description>
        {failed && <ErrorState>Deletion failed. Try again.</ErrorState>}
        <div className="actions mt-4">
          <Dialog.Close asChild><button className="button secondary">Cancel</button></Dialog.Close>
          <button className="button danger-solid" disabled={busy} onClick={async () => {
            setBusy(true)
            const deleted = await remove()
            if (deleted) setOpen(false)
            setFailed(!deleted)
            setBusy(false)
          }}>Delete watchlist</button>
        </div>
        <Dialog.Close asChild><button className="icon-button modal-close" aria-label="Close"><X size={16} /></button></Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

function Existing({ token, watch, reload }: { token: string; watch: Watchlist; reload: () => void }) {
  const [policy, setPolicy] = useState(watch.policy)
  const [enabled, setEnabled] = useState(watch.enabled)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const policyKey = JSON.stringify(watch.policy)
  useEffect(() => { setPolicy(JSON.parse(policyKey)); setEnabled(watch.enabled) }, [policyKey, watch.enabled])
  const mutate = async (method: 'PATCH' | 'DELETE') => {
    setError(''); setMessage(''); setBusy(true)
    try {
      await request(token, '/watchlists/' + watch.id, {
        method, body: method === 'PATCH' ? JSON.stringify({ enabled, policy }) : undefined,
      })
      setMessage('Watchlist saved. Analysis queued.'); reload(); return true
    } catch (error) { setError((error as Error).message); return false }
    finally { setBusy(false) }
  }
  return <details className="watch-detail">
    <summary><div><strong>{watch.name}</strong><small>{watch.source === 'fixture' ? 'Synthetic fixture' : 'Public Bluesky'}</small></div>
      <Badge tone={watch.enabled ? 'confirmed' : 'neutral'}>{watch.enabled ? watch.state || 'enabled' : 'paused'}</Badge></summary>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); void mutate('PATCH') }}>
      <div className="chips scope-chips">{Object.entries(watch.scope).flatMap(([kind, values]) =>
        values.map((value: string) => <Badge key={kind + value}>{kind} · {value}</Badge>))}</div>
      <label className="inline"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />Collection enabled</label>
      <PolicyFields policy={policy} update={setPolicy} />
      {message && <p className="subtle" role="status">{message}</p>}{error && <ErrorState>{error}</ErrorState>}
      <div className="actions"><button className="button primary" disabled={busy}>Save policy</button>
        {watch.source === 'fixture' && <button type="button" className="button secondary" disabled={!watch.enabled || busy} onClick={async () => {
          setError(''); setMessage(''); setBusy(true)
          try {
            await request(token, '/fixtures?watchlist_id=' + watch.id, { method: 'POST' })
            setMessage('Fixture replay queued for this watchlist.'); reload()
          } catch (error) { setError((error as Error).message) }
          finally { setBusy(false) }
        }}>Replay fixture</button>}
        <DeleteWatchlist name={watch.name} remove={() => mutate('DELETE')} /></div>
    </form>
  </details>
}

const blank = { dids: '', keywords: '', hashtags: '', domains: '', urls: '' }
export function SettingsPage({ token, mode, topicStream }: { token: string; mode: Source; topicStream: boolean }) {
  const list = useQuery<Watchlist[]>(token, '/watchlists', 8000)
  const [name, setName] = useState('')
  const [input, setInput] = useState(blank)
  const [policy, setPolicy] = useState(defaults)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const save = async () => {
    const scope = Object.fromEntries(Object.entries(input).map(([field, value]) =>
      [field, value.split(/[,\n]/).map(item => item.trim()).filter(Boolean)])) as Scope
    setBusy(true); setError(''); setMessage('')
    try {
      await request(token, '/watchlists', { method: 'POST', body: JSON.stringify({ name, scope, policy }) })
      setName(''); setInput(blank); setMessage('Watchlist created.'); list.reload()
    } catch (error) { setError((error as Error).message) }
    finally { setBusy(false) }
  }
  return <>
    <PageTitle title="Settings" description="Manage collection scope, retention, and coordination thresholds." />
    <div className="split settings-split">
      <section className="section card"><div className="section-heading"><div><h2>Create watchlist</h2><p>Enter multiple values separated by commas.</p></div><Badge tone={mode === 'fixture' ? 'fixture' : 'confirmed'}>{mode === 'fixture' ? 'Fixture mode' : 'Live mode'}</Badge></div>
        <form className="section-body form-stack" onSubmit={e => { e.preventDefault(); void save() }}>
          <label>Name<input required minLength={2} maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="Community watch" /></label>
          <label>Public account DIDs<input required={mode === 'bluesky' && !topicStream} value={input.dids} onChange={e => setInput({ ...input, dids: e.target.value })} placeholder="did:plc:…" /></label>
          <p className="subtle">{mode === 'bluesky' && !topicStream ? 'Add a DID to restrict the upstream stream. Topic-only collection is disabled.' : 'DIDs limit upstream collection to the selected accounts.'}</p>
          <div className="form-grid">
            {([['keywords', 'Keywords', 'community grants'], ['hashtags', 'Hashtags', '#community'],
              ['domains', 'Domains', 'example.org'], ['urls', 'Exact URLs', 'https://example.org/news']] as const).map(([key, label, placeholder]) =>
              <label key={key}>{label}<input value={input[key]} placeholder={placeholder} onChange={e => setInput({ ...input, [key]: e.target.value })} /></label>)}
          </div>
          <h3>Detection and retention</h3>
          <PolicyFields policy={policy} update={setPolicy} />
          {error && <ErrorState>{error}</ErrorState>}{message && <p role="status">{message}</p>}
          <button className="button primary justify-self-start" disabled={busy}><Plus size={17} />Create watchlist</button>
        </form>
      </section>
      <section className="section card"><div className="section-heading"><div><h2>Watchlists</h2><p>Open a watchlist to edit its policy.</p></div></div>
        {list.error ? <ErrorState>{list.error}</ErrorState> : !list.data ? <Loading /> : list.data.length ?
          list.data.map(w => <Existing key={w.id} watch={w} token={token} reload={list.reload} />) : <Empty>No watchlists have been created.</Empty>}
      </section>
    </div>
  </>
}
