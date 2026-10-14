import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { fmtRuntime, STATUS_LABEL } from '../lib'
import { useApp } from '../store'
import type { FilmCard, FilmLight, Status } from '../types'
import { Availability } from './Availability'
import { Icon } from './Icon'
import { Poster } from './Poster'
import { Sheet } from './Sheet'
import { Stars } from './Stars'

const STATES: { v: Status; label: string; icon: 'eye' | 'bookmark' | 'clock' | 'play' | 'cut' }[] = [
  { v: 'watched', label: 'Vista', icon: 'eye' },
  { v: 'watchlist', label: 'Quiero verla', icon: 'bookmark' },
  { v: 'parked', label: 'Otro día', icon: 'clock' },
  { v: 'watching', label: 'La estoy viendo', icon: 'play' },
  { v: 'never', label: 'Nunca', icon: 'cut' },
]

const ATTR_ES: Record<string, string> = {
  pace: 'Ritmo', intensity: 'Intensidad', tension: 'Tensión', humor: 'Humor', warmth: 'Calidez',
  darkness: 'Oscuridad', emotional: 'Emoción', complexity: 'Complejidad',
}

/** Ficha completa de una película + todo lo que puedes hacer con ella. */
export function FilmDrawer() {
  const { film, openFilm, toast, bump } = useApp()
  const [card, setCard] = useState<FilmCard | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (id: number) => {
    setCard(await api.get<FilmCard>(`/api/films/${id}`))
  }, [])

  useEffect(() => {
    if (!film) { setCard(null); return }
    let alive = true
    setLoading(true)
    ;(async () => {
      try {
        let id = film.id
        if (id === null && film.tmdbId) id = (await api.post<FilmLight>('/api/films/from-tmdb', { tmdb_id: film.tmdbId })).id
        if (id !== null && alive) await load(id)
      } catch (e) {
        toast((e as Error).message, { tone: 'error' })
        openFilm(null)
      } finally { if (alive) setLoading(false) }
    })()
    return () => { alive = false }
  }, [film, load, openFilm, toast])

  const set = async (patch: Record<string, unknown>) => {
    if (!card?.id) return
    try {
      await api.post(`/api/films/${card.id}/state`, patch)
      await load(card.id)
      bump()
    } catch (e) { toast((e as Error).message, { tone: 'error' }) }
  }

  const toggleState = (v: Status) => set({ status: card?.status === v ? 'none' : v })

  return (
    <Sheet open={!!film} onClose={() => openFilm(null)} wide label={card?.title ?? 'Ficha'}>
      {loading && !card && <p className="muted pad">Abriendo ficha…</p>}
      {card && (
        <div className="drawer">
          <div className="drawer__top">
            <Poster film={card} className="drawer__poster" />
            <div>
              <h2 className="drawer__title">{card.title}</h2>
              {card.original_title && card.original_title !== card.title && <p className="card__orig">{card.original_title}</p>}
              <div className="meta">
                {card.year && <span>{card.year}</span>}
                {card.runtime ? <span>{fmtRuntime(card.runtime)}</span> : null}
                {card.directors && card.directors[0] && <span>{card.directors.join(' y ')}</span>}
                {card.vote_average ? <span>{card.vote_average.toFixed(1)} / 10</span> : null}
              </div>
              <div className="genres">{card.genres.map(g => <span key={g}>{g}</span>)}</div>
              {card.aged_info && <p className="drawer__aged"><b>{card.aged_info.label}.</b> {card.aged_info.note}</p>}
            </div>
          </div>

          {card.tagline && <p className="pitch">{card.tagline}</p>}
          {card.overview && <p className="overview">{card.overview}</p>}
          {card.cast.length > 0 && <p className="muted small">Con {card.cast.slice(0, 5).join(', ')}.</p>}

          <Availability film={card} avail={card.availability} big />

          <h3 className="sub">Mi estado</h3>
          <div className="states">
            {STATES.map(s => (
              <button key={s.v} className={`state ${card.status === s.v ? 'is-on' : ''}`} aria-pressed={card.status === s.v}
                      onClick={() => toggleState(s.v)}>
                <Icon name={s.icon} size={18} /> {s.label}
              </button>
            ))}
          </div>
          {card.status === 'watched' && (
            <div className="rate">
              <Stars value={card.my_rating} onChange={v => set({ status: 'watched', rating: v })} />
              <button className={`like ${card.liked ? 'is-on' : ''}`} aria-pressed={!!card.liked}
                      onClick={() => set({ liked: !card.liked })}><Icon name="heart" size={20} /> Me encantó</button>
              {card.my_rating ? <button className="linkbtn" onClick={() => set({ clear_rating: true })}>Quitar nota</button> : null}
            </div>
          )}
          <p className="muted small">Lo que marques aquí se queda en Claqueta: no se envía nada a tu Letterboxd.</p>

          <h3 className="sub">Cómo es por dentro</h3>
          <div className="attrs">
            {Object.entries(ATTR_ES).map(([k, l]) => (
              <div key={k} className="attrs__row"><span>{l}</span>
                <div className="attrs__bar"><i style={{ width: `${Math.round((card.attrs[k] ?? 0.5) * 100)}%` }} /></div></div>
            ))}
          </div>
          {card.attrs_source !== 'llm' && card.attrs_source !== 'seed' && (
            <p className="muted small">Perfil estimado a partir del género y la sinopsis. Con un LLM configurado se afina.</p>
          )}

          <div className="links">
            {card.letterboxd && <a href={card.letterboxd} target="_blank" rel="noreferrer"><Icon name="link" size={16} /> Letterboxd</a>}
            {card.trailer && <a href={`https://www.youtube.com/watch?v=${card.trailer}`} target="_blank" rel="noreferrer"><Icon name="play" size={16} /> Tráiler</a>}
            {card.imdb_id && <a href={`https://www.imdb.com/title/${card.imdb_id}/`} target="_blank" rel="noreferrer"><Icon name="link" size={16} /> IMDb</a>}
          </div>
          <p className="muted small">Estado actual: {STATUS_LABEL[card.status]}</p>
        </div>
      )}
    </Sheet>
  )
}
