import { useCallback, useEffect, useRef, useState } from 'react'
import { api, qs } from '../api'
import { Icon } from '../components/Icon'
import { Poster } from '../components/Poster'
import { Stars } from '../components/Stars'
import { useDebounced } from '../hooks'
import { fmtRuntime, STATUS_LABEL } from '../lib'
import { go } from '../router'
import { useApp } from '../store'
import type { DownloadItem, FilmLight, LibraryResponse } from '../types'

type Tab = 'parked' | 'watchlist' | 'watching' | 'watched' | 'jellyfin' | 'requested' | 'never'
const TABS: { id: Tab; label: string; empty: string }[] = [
  { id: 'parked', label: 'Otro día', empty: 'Aquí caen las películas que guardas con «Otro día». Ninguna todavía.' },
  { id: 'watchlist', label: 'Quiero verlas', empty: 'Tu watchlist de Letterboxd aparece aquí al importarla. También puedes marcar películas desde su ficha.' },
  { id: 'watching', label: 'Viendo', empty: 'Cuando aceptes una sugerencia con «¡Esta!», la verás aquí hasta que la valores.' },
  { id: 'watched', label: 'Vistas', empty: 'Sin películas vistas: importa tu Letterboxd o calibra tu gusto para empezar.' },
  { id: 'jellyfin', label: 'En casa', empty: 'Sincroniza Jellyfin en Ajustes para ver aquí tu biblioteca.' },
  { id: 'requested', label: 'Pedidas', empty: 'Las películas que pidas en Jellyseerr aparecen aquí con su progreso de descarga.' },
  { id: 'never', label: 'Nunca', empty: 'Las que descartes con «Nunca» viven aquí por si cambias de idea.' },
]
const SORTS = [['recent', 'Más recientes'], ['rating', 'Mejor nota'], ['title', 'Título'], ['year', 'Año'], ['runtime', 'Duración']]
const PAGE = 60

function Tile({ f, dl }: { f: FilmLight; dl?: DownloadItem['download'] }) {
  const { openFilm } = useApp()
  return (
    <li className="tile">
      <button onClick={() => openFilm(f.id)} aria-label={`${f.title}${f.year ? `, ${f.year}` : ''}`}>
        <Poster film={{ ...f, directors: f.directors ?? [] }} />
        {f.availability?.jellyfin.available && <span className="tile__badge" title="En tu Jellyfin"><Icon name="play" size={12} /></span>}
        {dl && <span className="tile__dl" role="progressbar" aria-valuenow={dl.pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${dl.pct}%` }} /></span>}
        <span className="tile__title">{f.title}</span>
        <span className="tile__meta">
          {f.year}{f.runtime ? `  ${fmtRuntime(f.runtime)}` : ''}
        </span>
        {f.status === 'watched' && f.my_rating ? <Stars value={f.my_rating} readOnly size={13} /> : null}
        {f.status !== 'none' && f.status !== 'watched' && <span className="tile__state">{STATUS_LABEL[f.status]}</span>}
      </button>
    </li>
  )
}

export default function Library() {
  const { version } = useApp()
  const [tab, setTab] = useState<Tab>('parked')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('recent')
  const [data, setData] = useState<LibraryResponse | null>(null)
  const [items, setItems] = useState<FilmLight[]>([])
  const [dls, setDls] = useState<Record<number, DownloadItem['download']>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const picked = useRef(false)
  const dq = useDebounced(q, 250)

  const load = useCallback(async (offset: number) => {
    setLoading(true)
    try {
      const r = await api.get<LibraryResponse>(`/api/library${qs({ tab, q: dq.trim(), sort, limit: PAGE, offset })}`)
      setData(r)
      setItems(prev => (offset === 0 ? r.items : [...prev, ...r.items]))
      setError(null)
      if (!picked.current && offset === 0 && r.total === 0 && !dq) {
        picked.current = true
        const next = TABS.find(t => (r.counts[t.id] ?? 0) > 0)
        if (next && next.id !== tab) setTab(next.id)
      }
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }, [tab, dq, sort])

  useEffect(() => { void load(0) }, [load, version])

  useEffect(() => {
    if (tab !== 'requested') return
    api.get<{ items: DownloadItem[] }>('/api/downloads')
      .then(r => setDls(Object.fromEntries(r.items.filter(i => i.id && i.download).map(i => [i.id as number, i.download]))))
      .catch(() => undefined)
  }, [tab, version])

  const cur = TABS.find(t => t.id === tab)!
  return (
    <div className="lib">
      <h1 className="h1">Tu biblioteca</h1>
      <div className="tabs" role="tablist" aria-label="Listas">
        {TABS.map(t => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? 'is-on' : ''}`}
                  onClick={() => { picked.current = true; setTab(t.id) }}>
            {t.label}{data ? <small>{data.counts[t.id] ?? 0}</small> : null}
          </button>
        ))}
      </div>
      <div className="lib__tools">
        <div className="ask ask--solid">
          <Icon name="search" size={18} />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Buscar en esta lista…" aria-label="Buscar en esta lista" />
        </div>
        <label className="select"><span className="sr-only">Ordenar</span>
          <select value={sort} onChange={e => setSort(e.target.value)}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}
      {items.length > 0 && (
        <ul className="grid">{items.map(f => <Tile key={f.id} f={f} dl={f.id ? dls[f.id] : undefined} />)}</ul>
      )}
      {!loading && items.length === 0 && !error && (
        <div className="empty empty--flat">
          <h2>{q ? 'Nada con ese nombre' : 'Lista vacía'}</h2>
          <p>{q ? 'Prueba con otra búsqueda o cambia de lista.' : cur.empty}</p>
          {!q && (tab === 'watched' || tab === 'watchlist') && <button className="btn btn--go" onClick={() => go('empezar')}>Calibrar mi gusto</button>}
          {!q && tab === 'jellyfin' && <button className="btn btn--ghost" onClick={() => go('ajustes')}>Ir a Ajustes</button>}
        </div>
      )}
      {data && items.length < data.total && (
        <button className="btn btn--ghost lib__more" disabled={loading} onClick={() => void load(items.length)}>
          {loading ? 'Cargando…' : `Ver más (${data.total - items.length})`}
        </button>
      )}
    </div>
  )
}
