import { useState } from 'react'
import { api } from '../api'
import { useApp } from '../store'
import type { Avail, FilmLight } from '../types'
import { Icon } from './Icon'

const SEERR_TEXT: Record<string, string> = {
  pending: 'Pedida: pendiente de aprobar', processing: 'Descargándose', partial: 'Disponible en parte', available: 'Disponible',
}

/** Dónde verla: Jellyfin (ver ya), Jellyseerr (pedirla) o streaming. */
export function Availability({ film, avail, big = false }: { film: Pick<FilmLight, 'id' | 'title'>; avail: Avail | undefined; big?: boolean }) {
  const { toast, bump } = useApp()
  const [busy, setBusy] = useState(false)
  const [local, setLocal] = useState<string | null>(null)
  if (!avail) return null
  const seerr = avail.seerr
  const status = local ?? seerr.status ?? 'none'

  const request = async () => {
    if (!film.id) return
    setBusy(true)
    try {
      await api.post(`/api/films/${film.id}/request`)
      setLocal('pending')
      toast(`Pedida «${film.title}» en Jellyseerr`, { tone: 'ok' })
      bump()
    } catch (e) {
      toast((e as Error).message, { tone: 'error', ms: 6000 })
    } finally { setBusy(false) }
  }

  return (
    <div className={`avail ${big ? 'avail--big' : ''}`}>
      {avail.jellyfin.available && avail.jellyfin.url && (
        <a className="btn btn--play" href={avail.jellyfin.url} target="_blank" rel="noreferrer">
          <Icon name="play" size={18} /> Ver en Jellyfin
        </a>
      )}
      {avail.jellyfin.available && !avail.jellyfin.url && <span className="pill pill--ok"><Icon name="play" size={14} /> En tu Jellyfin</span>}
      {!avail.jellyfin.available && seerr.enabled && status === 'none' && seerr.can_request && (
        <button className="btn btn--ghost" onClick={request} disabled={busy}>
          <Icon name="download2" size={18} /> {busy ? 'Pidiendo…' : 'Pedir en Jellyseerr'}
        </button>
      )}
      {!avail.jellyfin.available && status !== 'none' && (
        <a className="pill pill--wait" href={seerr.url ?? undefined} target="_blank" rel="noreferrer">
          <Icon name="download2" size={14} /> {SEERR_TEXT[status] ?? status}
        </a>
      )}
      {avail.streaming.length > 0 && (
        <a className="pill pill--tv" href={avail.streaming_link ?? undefined} target="_blank" rel="noreferrer"
           title="Disponible por suscripción (JustWatch / TMDB)">
          <Icon name="tv" size={14} /> {avail.streaming.map(s => s.name).slice(0, 3).join(', ')}
        </a>
      )}
      {!avail.jellyfin.available && !seerr.enabled && avail.streaming.length === 0 && (
        <span className="pill pill--none">No la tienes en casa ni en streaming</span>
      )}
    </div>
  )
}
