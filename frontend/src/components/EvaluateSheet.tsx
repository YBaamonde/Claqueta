import { useEffect, useRef, useState } from 'react'
import { api, qs } from '../api'
import { useApp } from '../store'
import type { Ctx, FilmCard, FilmLight } from '../types'
import { Icon } from './Icon'
import { Poster } from './Poster'
import { Sheet } from './Sheet'

const VERDICT: Record<string, { title: string; cls: string }> = {
  go: { title: 'Adelante: encaja con esta noche', cls: 'go' },
  maybe: { title: 'Depende: tiene pegas', cls: 'maybe' },
  skip: { title: 'Mejor otra noche', cls: 'skip' },
}

/** «¿Me conviene?»: busca cualquier película y dime si va con lo que has pedido esta noche. */
export function EvaluateSheet({ open, onClose, ctx }: { open: boolean; onClose: () => void; ctx: Ctx }) {
  const { openFilm, toast, bump } = useApp()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<FilmLight[]>([])
  const [card, setCard] = useState<FilmCard | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { if (open) window.setTimeout(() => input.current?.focus(), 120); else { setQ(''); setResults([]); setCard(null) } }, [open])

  useEffect(() => {
    window.clearTimeout(timer.current)
    if (q.trim().length < 2) { setResults([]); return }
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.get<{ results: FilmLight[] }>(`/api/search${qs({ q: q.trim() })}`)
        setResults(r.results)
      } catch (e) { toast((e as Error).message, { tone: 'error' }) }
    }, 260)
    return () => window.clearTimeout(timer.current)
  }, [q, toast])

  const evaluate = async (f: FilmLight) => {
    setBusy(true)
    try {
      let id = f.id
      if (id === null && f.tmdb_id) id = (await api.post<FilmLight>('/api/films/from-tmdb', { tmdb_id: f.tmdb_id })).id
      if (id === null) return
      setCard(await api.post<FilmCard>(`/api/films/${id}/evaluate`, { context: ctx }))
    } catch (e) { toast((e as Error).message, { tone: 'error' }) } finally { setBusy(false) }
  }

  const park = async () => {
    if (!card?.id) return
    await api.post(`/api/films/${card.id}/state`, { status: 'parked' })
    toast(`«${card.title}» guardada para otro día`)
    bump()
  }

  return (
    <Sheet open={open} onClose={onClose} title="¿Me conviene esta película?" wide>
      <div className="eval">
        <div className="ask ask--solid">
          <Icon name="search" size={18} />
          <input ref={input} value={q} onChange={e => { setQ(e.target.value); setCard(null) }} placeholder="Escribe un título…" aria-label="Título de la película" />
        </div>
        {!card && results.length > 0 && (
          <ul className="eval__list">
            {results.map(r => (
              <li key={`${r.id}-${r.tmdb_id}`}>
                <button onClick={() => evaluate(r)} disabled={busy}>
                  <Poster film={{ ...r, directors: r.directors ?? [], id: r.id }} compact />
                  <span><b>{r.title}</b><small>{r.year}{r.kind === 'tmdb' ? '  desde TMDB' : ''}</small></span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {!card && q.trim().length >= 2 && results.length === 0 && <p className="muted pad">Nada con ese nombre. Con TMDB configurado también busco fuera de tu catálogo.</p>}
        {card && (
          <div className={`verdict verdict--${VERDICT[card.verdict ?? 'maybe'].cls}`}>
            <h3>{VERDICT[card.verdict ?? 'maybe'].title}</h3>
            <p><b>{card.title}</b> {card.year ? `(${card.year})` : ''}  {card.match}% de encaje con lo que has pedido</p>
            <ul className="reasons">
              {(card.reasons ?? []).slice(0, 3).map((r, i) => <li key={i}><span aria-hidden="true">{r.icon}</span>{r.text}</li>)}
              {(card.warnings ?? []).map((w, i) => <li key={`w${i}`} className="warn"><Icon name="warn" size={16} />{w.text}</li>)}
            </ul>
            <div className="actions actions--two">
              <button className="btn btn--ghost" onClick={() => { onClose(); openFilm(card.id) }}>Ver ficha</button>
              <button className="btn btn--save" onClick={park}><Icon name="bookmark" size={18} /> Otro día</button>
            </div>
            <button className="linkbtn" onClick={() => setCard(null)}>Probar con otra</button>
          </div>
        )}
      </div>
    </Sheet>
  )
}
