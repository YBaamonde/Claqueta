import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import { Poster } from '../components/Poster'
import { useApp } from '../store'
import type { CinePath } from '../types'

export default function Paths() {
  const { openFilm, version } = useApp()
  const [paths, setPaths] = useState<CinePath[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<{ paths: CinePath[] }>('/api/paths').then(r => setPaths(r.paths)).catch(e => setError((e as Error).message))
  }, [version])

  return (
    <div className="paths">
      <h1 className="h1">Rutas de cine</h1>
      <p className="lead">Recorridos cortos para descubrir clásicos sin pasar por los tostones. Cada ruta empieza por lo más fácil de ver y sube poco a poco.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!paths && !error && <div className="skeleton" />}
      <div className="paths__list">
        {paths?.map(p => {
          const pct = p.total ? Math.round((100 * p.seen) / p.total) : 0
          const next = p.films.find(f => f.id === p.next_id)
          return (
            <section className="path" key={p.slug} aria-labelledby={`p-${p.slug}`}>
              <header className="path__head">
                <span className="path__emoji" aria-hidden="true">{p.emoji}</span>
                <div>
                  <h2 id={`p-${p.slug}`}>{p.title}</h2>
                  <p>{p.blurb}</p>
                </div>
              </header>
              <div className="path__progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
                   aria-label={`${p.seen} de ${p.total} vistas`}>
                <i style={{ width: `${pct}%` }} /><span>{p.seen} de {p.total} vistas</span>
              </div>
              <ol className="path__films">
                {p.films.map(f => (
                  <li key={f.id} className={f.status === 'watched' ? 'is-seen' : f.id === p.next_id ? 'is-next' : ''}>
                    <button onClick={() => openFilm(f.id)} aria-label={`${f.title}${f.status === 'watched' ? ', vista' : ''}`}>
                      <Poster film={{ ...f, directors: f.directors ?? [] }} compact />
                      {f.status === 'watched' && <span className="path__check"><Icon name="check" size={14} /></span>}
                      <span>{f.title}</span>
                    </button>
                  </li>
                ))}
              </ol>
              {next
                ? <button className="btn btn--go path__next" onClick={() => openFilm(next.id)}><Icon name="play" size={18} /> <span className="path__next-t">Siguiente: {next.title}</span></button>
                : <p className="muted small">Ruta completada. Ya puedes presumir.</p>}
            </section>
          )
        })}
      </div>
    </div>
  )
}
