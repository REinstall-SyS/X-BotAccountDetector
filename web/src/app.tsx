import { useState } from 'react'
import { Activity, FlaskConical, LayoutDashboard, ListChecks, LogOut, Network, Radio, Settings, UsersRound } from 'lucide-react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Accounts } from './accounts'
import { request } from './data'
import { Explorer, Queue } from './investigations'
import { ModelLab, Overview } from './overview'
import { SettingsPage } from './settings'
import type { Source } from './types'
import { Badge, ErrorState } from './ui'

const routes = [
  ['/', 'Overview', LayoutDashboard],
  ['/investigations', 'Investigations', ListChecks],
  ['/clusters', 'Cluster Explorer', Network],
  ['/accounts', 'Account Analysis', UsersRound],
  ['/models', 'Model Lab', FlaskConical],
  ['/settings', 'Settings', Settings],
] as const
type Session = { reviewer: string; mode: Source; topic_stream: boolean }

export function App() {
  const [session, setSession] = useState<{ token: string; info: Session }>()
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const location = useLocation()
  const signIn = async () => {
    setBusy(true); setError('')
    try {
      const token = input.trim()
      const info = await request<Session>(token, '/session')
      setSession({ token, info }); setInput('')
    } catch (error) { setError((error as Error).message) }
    finally { setBusy(false) }
  }
  if (!session) return <main className="login"><section className="card login-card">
    <div className="brand"><span className="brand-icon"><Activity size={23} /></span><div><strong>Signal Desk</strong><small>Community Integrity</small></div></div>
    <h1>Sign in to your workspace</h1><p>Use your reviewer token to access watchlists and investigations.</p>
    <form className="form-stack" onSubmit={e => { e.preventDefault(); void signIn() }}>
      <label>Reviewer token<input type="password" autoComplete="off" value={input} required maxLength={512} onChange={e => setInput(e.target.value)} /></label>
      {error && <ErrorState>{error}</ErrorState>}
      <button className="button primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </section></main>
  const { token, info } = session
  const current = routes.find(([path]) => path === location.pathname || (path !== '/' && location.pathname.startsWith(path + '/')))
  return <div className="workspace">
    <aside className="sidebar">
      <NavLink to="/" className="brand"><span className="brand-icon"><Activity size={23} /></span><div><strong>Signal Desk</strong><small>Community Integrity</small></div></NavLink>
      <nav aria-label="Workspace navigation">{routes.map(([path, label, Icon]) =>
        <NavLink key={path} end={path === '/'} to={path} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}><Icon size={18} />{label}</NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="workspace-state"><Radio size={16} /><div><strong>{info.mode === 'fixture' ? 'Fixture workspace' : 'Bluesky workspace'}</strong><small>{info.mode === 'fixture' ? 'Offline samples' : 'Public activity only'}</small></div></div>
        <button className="nav-link" onClick={() => setSession(undefined)}><LogOut size={17} />Sign out</button>
      </div>
    </aside>
    <div className="workspace-main">
      <header className="topbar"><div className="crumb"><span>Workspace</span><span>/</span><strong>{current?.[1] || 'Overview'}</strong></div>
        <div className="topbar-right"><Badge tone={info.mode === 'fixture' ? 'fixture' : 'confirmed'}>{info.mode === 'fixture' ? 'Fixture mode' : 'Bluesky live'}</Badge>
          <span className="avatar" title={info.reviewer}>{info.reviewer.slice(0, 2).toUpperCase()}</span><strong>{info.reviewer}</strong></div></header>
      <main className="content" id="main-content"><Routes>
        <Route path="/" element={<Overview token={token} mode={info.mode} />} />
        <Route path="/investigations" element={<Queue token={token} />} />
        <Route path="/investigations/:id" element={<Explorer token={token} />} />
        <Route path="/clusters" element={<Explorer token={token} graphOnly />} />
        <Route path="/clusters/:id" element={<Explorer token={token} graphOnly />} />
        <Route path="/accounts" element={<Accounts key={location.search} token={token} />} />
        <Route path="/models" element={<ModelLab token={token} mode={info.mode} />} />
        <Route path="/settings" element={<SettingsPage token={token} mode={info.mode} topicStream={info.topic_stream} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes></main>
    </div>
  </div>
}
