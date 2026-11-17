import { useCallback, useEffect, useState } from 'react'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function request<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, {
    ...init, headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = typeof body.detail === 'string'
      ? body.detail : body.detail?.map?.((entry: { msg: string }) => entry.msg).join(' · ')
    throw new ApiError(response.status, detail || 'Request failed (' + response.status + ')')
  }
  return response.status === 204 ? undefined as T : response.json()
}

export function useQuery<T>(token: string, path: string | null, interval = 0) {
  const [revision, refresh] = useState(0)
  const [result, setResult] = useState<{ path: string; data?: T; error?: string }>()
  useEffect(() => {
    if (!path) return
    const abort = new AbortController()
    let busy = false
    const load = async () => {
      if (busy) return
      busy = true
      try {
        const data = await request<T>(token, path, { signal: abort.signal })
        if (!abort.signal.aborted) setResult({ path, data })
      } catch (error) {
        if (!abort.signal.aborted) setResult({ path, error: (error as Error).message })
      } finally {
        busy = false
      }
    }
    void load()
    const timer = interval ? window.setInterval(load, interval) : undefined
    return () => { abort.abort(); window.clearInterval(timer) }
  }, [token, path, interval, revision])
  const reload = useCallback(() => refresh((version) => version + 1), [])
  return { ...(result?.path === path ? result : {}), reload }
}

export const formatDate = (time: string) => new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
}).format(new Date(time))
export const formatTime = (time: string) => new Intl.DateTimeFormat(undefined, {
  hour: 'numeric', minute: '2-digit', second: '2-digit',
}).format(new Date(time))
export const percent = (value: number | null) => value === null ? '—' : (100 * value).toFixed(1) + '%'
export const didLabel = (did: string) => did.length > 26 ? did.slice(8, 16) + '…' + did.slice(-5) : did
export function publicLink(uri: string) {
  const match = /^at:\/\/(did:[a-z0-9]+:[A-Za-z0-9.:%_-]+)\/app\.bsky\.feed\.post\/([A-Za-z0-9_.~:-]+)$/.exec(uri)
  return match ? 'https://bsky.app/profile/' + encodeURIComponent(match[1]) + '/post/' + encodeURIComponent(match[2]) : null
}
