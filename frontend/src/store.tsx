import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler } from './api'
import type { Bootstrap } from './types'

export interface ToastItem { id: number; text: string; action?: { label: string; run: () => void }; tone?: 'ok' | 'warn' | 'error' }

interface AppState {
  boot: Bootstrap | null
  bootError: string | null
  refreshBoot: () => Promise<void>
  toasts: ToastItem[]
  toast: (text: string, opts?: { action?: ToastItem['action']; tone?: ToastItem['tone']; ms?: number }) => void
  dismissToast: (id: number) => void
  openFilm: (id: number | null, tmdbId?: number | null) => void
  film: { id: number | null; tmdbId: number | null } | null
  /** Se incrementa cuando algo cambia en los datos del usuario: las listas se recargan. */
  version: number
  bump: () => void
  auth: 'loading' | 'ok' | 'login'
  setAuthOk: () => void
}

const Ctx = createContext<AppState | null>(null)

export function useApp(): AppState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp fuera de AppProvider')
  return v
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [film, setFilm] = useState<AppState['film']>(null)
  const [version, setVersion] = useState(0)
  const [auth, setAuth] = useState<AppState['auth']>('loading')
  const nextId = useRef(1)

  const refreshBoot = useCallback(async () => {
    try {
      setBoot(await api.get<Bootstrap>('/api/bootstrap'))
      setBootError(null)
    } catch (e) {
      setBootError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth('login'))
    api.get<{ required: boolean; authenticated: boolean }>('/api/auth/status')
      .then(s => {
        if (s.required && !s.authenticated) setAuth('login')
        else { setAuth('ok'); void refreshBoot() }
      })
      .catch(e => { setBootError((e as Error).message); setAuth('ok') })
  }, [refreshBoot])

  const dismissToast = useCallback((id: number) => setToasts(t => t.filter(x => x.id !== id)), [])
  const toast = useCallback<AppState['toast']>((text, opts) => {
    const id = nextId.current++
    setToasts(t => [...t.slice(-2), { id, text, action: opts?.action, tone: opts?.tone }])
    window.setTimeout(() => dismissToast(id), opts?.ms ?? (opts?.action ? 7000 : 3600))
  }, [dismissToast])

  const value = useMemo<AppState>(() => ({
    boot, bootError, refreshBoot, toasts, toast, dismissToast, version,
    bump: () => setVersion(v => v + 1),
    film, openFilm: (id, tmdbId = null) => setFilm(id === null && tmdbId === null ? null : { id, tmdbId }),
    auth, setAuthOk: () => { setAuth('ok'); void refreshBoot() },
  }), [boot, bootError, refreshBoot, toasts, toast, dismissToast, version, film, auth])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
