import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import { Poster } from '../components/Poster'
import { Stars } from '../components/Stars'
import { go } from '../router'
import { useApp } from '../store'
import type { Bootstrap, FilmLight } from '../types'

export default function Onboarding({ boot, onDemo, demoBusy, onDone }: { boot: Bootstrap; onDemo: () => void; demoBusy: boolean; onDone: () => void }) {
  const { toast, bump } = useApp()
  const [items, setItems] = useState<FilmLight[] | null>(null)
  const [ratings, setRatings] = useState<Record<number, number>>({})
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || items) return
    api.get<{ items: FilmLight[] }>('/api/onboarding?n=36').then(r => setItems(r.items)).catch(e => toast((e as Error).message, { tone: 'error' }))
  }, [open, items, toast])

  const n = Object.keys(ratings).length
  const save = async () => {
    setSaving(true)
    try {
      await api.post('/api/onboarding', { items: Object.entries(ratings).map(([film_id, rating]) => ({ film_id: Number(film_id), rating })) })
      toast(`Guardadas ${n} valoraciones. Ya te conozco un poco más`, { tone: 'ok' })
      bump()
      onDone()
    } catch (e) { toast((e as Error).message, { tone: 'error' }) } finally { setSaving(false) }
  }

  return (
    <div className="start">
      <h1 className="h1">Cuéntame qué te gusta</h1>
      <p className="lead">Cuantas más películas conozca de ti, menos tostones te propondré. Elige el camino que prefieras; puedes combinarlos.</p>

      <div className="start__ways">
        <section className="way">
          <Icon name="upload" size={26} />
          <h2>Importar mi Letterboxd</h2>
          <p>Lo mejor si ya llevas un diario: trae todo lo visto, con notas y favoritas, y tu watchlist.</p>
          <button className="btn btn--go" onClick={() => go('ajustes')}>Subir mi exportación</button>
        </section>
        <section className="way">
          <Icon name="star" size={26} />
          <h2>Valorar unas cuantas</h2>
          <p>Un minuto: marca las que has visto y cuánto te gustaron. Sin cuenta ni archivos.</p>
          <button className="btn btn--ghost" onClick={() => setOpen(o => !o)}>{open ? 'Ocultar la lista' : 'Ver la lista'}</button>
        </section>
        <section className="way">
          <Icon name="film" size={26} />
          <h2>Probar con un ejemplo</h2>
          <p>Carga el perfil de alguien que está empezando con los clásicos y explora cómo recomienda.</p>
          <button className="btn btn--ghost" disabled={demoBusy || boot.stats.demo > 0} onClick={onDemo}>
            {boot.stats.demo > 0 ? 'Ya cargado' : demoBusy ? 'Cargando…' : 'Cargar el ejemplo'}
          </button>
        </section>
      </div>

      {open && (
        <section className="calib" aria-label="Valorar películas">
          <p className="muted">Toca las estrellas en las que hayas visto. Las que no, déjalas sin marcar.</p>
          {!items && <div className="skeleton" />}
          <ul className="calib__grid">
            {items?.map(f => (
              <li key={f.id} className={ratings[f.id as number] ? 'is-rated' : ''}>
                <Poster film={{ ...f, directors: f.directors ?? [] }} />
                <b>{f.title}</b><small>{f.year}</small>
                <Stars value={ratings[f.id as number] ?? 0} size={17}
                       onChange={v => setRatings(r => (r[f.id as number] === v ? Object.fromEntries(Object.entries(r).filter(([k]) => Number(k) !== f.id)) : { ...r, [f.id as number]: v }))} />
              </li>
            ))}
          </ul>
          <div className="calib__bar">
            <span>{n ? `${n} valoradas` : 'Ninguna todavía'}</span>
            <button className="btn btn--go" disabled={!n || saving} onClick={save}>{saving ? 'Guardando…' : 'Guardar y ver sugerencias'}</button>
          </div>
        </section>
      )}
    </div>
  )
}
