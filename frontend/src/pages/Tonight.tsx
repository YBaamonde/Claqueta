import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { AcceptSheet } from '../components/AcceptSheet'
import { ComposerBody, summarize } from '../components/Composer'
import { DeckCard } from '../components/DeckCard'
import { EvaluateSheet } from '../components/EvaluateSheet'
import { FilmStrip } from '../components/FilmStrip'
import { Icon } from '../components/Icon'
import { Poster } from '../components/Poster'
import { ReasonSheet } from '../components/ReasonSheet'
import { Sheet } from '../components/Sheet'
import { useMedia } from '../hooks'
import { go } from '../router'
import { useApp } from '../store'
import { DEFAULT_CTX, type Bootstrap, type Ctx, type Deck, type FilmCard, type HomeResponse } from '../types'

function Slate({ children, clap }: { children: React.ReactNode; clap: number }) {
  return (
    <div className="slate">
      <div className="clapper" aria-hidden="true">
        <motion.div key={clap} className="clapper__stick" initial={{ rotate: -16 }} animate={{ rotate: 0 }}
                    transition={{ type: 'spring', stiffness: 700, damping: 18, delay: 0.05 }} />
        <div className="clapper__base" />
      </div>
      <div className="slate__body">{children}</div>
    </div>
  )
}

function useMoodTint(ctx: Ctx, boot: Bootstrap) {
  useEffect(() => {
    const m = boot.moods.find(x => x.id === ctx.moods[0])
    const r = document.documentElement.style
    r.setProperty('--mood-a', m ? m.colors[0] : '#6a4c93')
    r.setProperty('--mood-b', m ? m.colors[1] : '#ffb547')
  }, [ctx.moods, boot.moods])
  useEffect(() => () => {
    document.documentElement.style.removeProperty('--mood-a')
    document.documentElement.style.removeProperty('--mood-b')
  }, [])
}

export default function Tonight({ boot }: { boot: Bootstrap }) {
  const { toast, bump, openFilm, version } = useApp()
  const wide = useMedia('(min-width: 980px)')
  const [ctx, setCtx] = useState<Ctx>(() => ({ ...DEFAULT_CTX, anti_toston: boot.defaults.anti_toston, ...boot.last_context }))
  const [data, setData] = useState<Deck | null>(null)
  const [order, setOrder] = useState<number[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reasonFor, setReasonFor] = useState<FilmCard | null>(null)
  const [accepted, setAccepted] = useState<FilmCard | null>(null)
  const [composerOpen, setComposerOpen] = useState(false)
  const [evalOpen, setEvalOpen] = useState(false)
  const [clap, setClap] = useState(0)
  const [home, setHome] = useState<HomeResponse | null>(null)
  const sid = useRef<string | null>(null)
  const seq = useRef(0)
  const dir = useRef(1)
  const latest = useRef(ctx)
  const timer = useRef<number | undefined>(undefined)
  latest.current = ctx
  useMoodTint(ctx, boot)

  const apply = useCallback((res: Deck) => { setData(res); setOrder(null); setError(null) }, [])

  const start = useCallback(async (c: Ctx) => {
    const my = ++seq.current
    setLoading(true)
    try {
      const res = await api.post<Deck>('/api/sessions', { context: c })
      if (my !== seq.current) return
      sid.current = res.session_id
      apply(res)
      setClap(n => n + 1)
    } catch (e) { if (my === seq.current) setError((e as Error).message) } finally { if (my === seq.current) setLoading(false) }
  }, [apply])

  useEffect(() => { void start(latest.current) }, [start])

  const pushContext = useCallback(async () => {
    if (!sid.current) return
    const my = ++seq.current
    try {
      const res = await api.put<Deck>(`/api/sessions/${sid.current}/context`, latest.current)
      if (my === seq.current) { dir.current = 1; apply(res) }
    } catch (e) { if (my === seq.current) setError((e as Error).message) }
  }, [apply])

  const change = useCallback((patch: Partial<Ctx>) => {
    setCtx(c => ({ ...c, ...patch }))
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void pushContext(), 320)
  }, [pushContext])

  const fresh = useCallback(() => {
    window.clearTimeout(timer.current)
    sid.current = null
    void start(latest.current)
    toast('Nueva toma: he olvidado los descartes de esta noche')
  }, [start, toast])

  useEffect(() => {
    api.get<HomeResponse>('/api/home').then(setHome).catch(() => undefined)
  }, [version])

  const cards = (() => {
    const d = data?.deck ?? []
    if (!order) return d
    const by = new Map(d.map(c => [c.id, c]))
    return order.map(i => by.get(i)).filter(Boolean) as FilmCard[]
  })()
  const current = cards[0]

  const undo = useCallback(async () => {
    if (!sid.current) return
    try {
      dir.current = -1
      apply(await api.post<Deck>(`/api/sessions/${sid.current}/undo`))
      bump()
    } catch (e) { toast((e as Error).message, { tone: 'warn' }) }
  }, [apply, bump, toast])

  const feedback = useCallback(async (card: FilmCard, action: 'dismiss' | 'save' | 'accept', reason?: string) => {
    if (!sid.current) return
    try {
      dir.current = 1
      const res = await api.post<Deck>(`/api/sessions/${sid.current}/feedback`, { film_id: card.id, action, reason })
      apply(res)
      bump()
      if (action === 'accept') setAccepted(card)
      else toast(res.toast ?? 'Hecho', { action: { label: 'Repetir toma', run: () => void undo() } })
    } catch (e) { toast((e as Error).message, { tone: 'error' }) }
  }, [apply, bump, toast, undo])

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [role=dialog]') || e.metaKey || e.ctrlKey || !current) return
      if (e.key === 'ArrowLeft') setReasonFor(current)
      else if (e.key === 'ArrowRight') void feedback(current, 'accept')
      else if (e.key.toLowerCase() === 's') void feedback(current, 'save')
      else if (e.key.toLowerCase() === 'z') void undo()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [current, feedback, undo])

  const quickFix = (patch: Partial<Ctx>) => change(patch)
  const summary = summarize(ctx, boot)

  const composer = <ComposerBody ctx={ctx} onChange={change} boot={boot} onReset={fresh} />

  return (
    <div className="tonight">
      {wide && <aside className="tonight__slate" aria-label="Qué quieres ver esta noche"><Slate clap={clap}>{composer}</Slate></aside>}

      <section className="tonight__main">
        {boot.needs_onboarding && (
          <div className="banner">
            <p><b>Todavía no sé qué te gusta.</b> Márcame unas cuantas películas o importa tu Letterboxd y acertaré mucho más.</p>
            <button className="btn btn--ghost btn--sm" onClick={() => go('empezar')}>Calibrar mi gusto</button>
          </div>
        )}

        <div className="bar">
          {!wide ? (
            <button className="bar__summary" onClick={() => setComposerOpen(true)} aria-label="Cambiar lo que quiero ver">
              <Icon name="sliders" size={18} />
              <span>{summary.slice(0, 3).join(' · ')}</span>
              <Icon name="chevron" size={16} />
            </button>
          ) : <p className="bar__summary bar__summary--static">{summary.join(' · ')}</p>}
          <button className="icon-btn" onClick={() => setEvalOpen(true)} aria-label="¿Me conviene una película concreta?" title="¿Me conviene?">
            <Icon name="search" />
          </button>
        </div>

        {data && data.adjustments.length > 0 && (
          <p className="adjusted"><Icon name="sparkle" size={14} /> Ajustado esta noche: {data.adjustments.join(', ')}</p>
        )}
        {data?.relaxed.map(r => <p key={r} className="adjusted adjusted--warn">{r}</p>)}

        <div className="stage" aria-live="polite">
          <AnimatePresence mode="popLayout" initial={false} custom={dir.current}>
            {current && (
              <DeckCard key={current.id} card={current} take={(data?.dismissed ?? 0) + 1} dir={dir.current}
                        onCut={() => setReasonFor(current)} onSave={() => void feedback(current, 'save')}
                        onAccept={() => void feedback(current, 'accept')} onOpen={() => openFilm(current.id)} />
            )}
          </AnimatePresence>

          {!current && !loading && !error && (
            <div className="empty">
              <h2>{data?.empty_reason === 'no_films' ? 'Aún no hay películas' : 'Nada cumple todo lo que has pedido'}</h2>
              {data?.empty_reason === 'no_films'
                ? <p>El catálogo está vacío. Carga los datos de ejemplo o conecta tus servicios en Ajustes.</p>
                : <p>Prueba a aflojar algo:</p>}
              <div className="chips">
                {ctx.max_minutes && <button className="chip" onClick={() => quickFix({ max_minutes: null })}>Quitar el límite de tiempo</button>}
                {(ctx.genres_in.length > 0 || ctx.genres_out.length > 0) && <button className="chip" onClick={() => quickFix({ genres_in: [], genres_out: [] })}>Quitar géneros</button>}
                {ctx.eras.length > 0 && <button className="chip" onClick={() => quickFix({ eras: [] })}>Cualquier época</button>}
                {ctx.scope !== 'all' && <button className="chip" onClick={() => quickFix({ scope: 'all' })}>Todo el catálogo</button>}
                {ctx.company !== 'solo' && <button className="chip" onClick={() => quickFix({ company: 'solo' })}>Ver solo</button>}
                <button className="chip" onClick={fresh}>Empezar de cero</button>
              </div>
              {!boot.stats.films && <button className="btn btn--go" onClick={() => go('ajustes')}>Ir a Ajustes</button>}
            </div>
          )}
          {loading && !current && <div className="skeleton" aria-label="Preparando sugerencias" />}
          {error && <div className="empty"><h2>No he podido preparar sugerencias</h2><p>{error}</p><button className="btn btn--ghost" onClick={fresh}>Reintentar</button></div>}
        </div>

        {data?.can_undo && current && (
          <button className="undo" onClick={() => void undo()}><Icon name="undo" size={16} /> Repetir la toma anterior</button>
        )}

        <FilmStrip items={cards.slice(1)} onPick={c => { dir.current = 1; setOrder([c.id as number, ...cards.filter(x => x.id !== c.id).map(x => x.id as number)]) }} />

        {home && (home.watching.length > 0 || home.parked.length > 0) && (
          <div className="resume">
            {home.watching.length > 0 && (
              <div><h3>Sigues con</h3>
                <ul>{home.watching.map(f => <li key={f.id}><button onClick={() => openFilm(f.id)}><Poster film={{ ...f, directors: f.directors ?? [] }} compact /><span>{f.title}</span></button></li>)}</ul></div>
            )}
            {home.parked.length > 0 && (
              <div><h3>Guardadas para otro día</h3>
                <ul>{home.parked.map(f => <li key={f.id}><button onClick={() => openFilm(f.id)}><Poster film={{ ...f, directors: f.directors ?? [] }} compact /><span>{f.title}</span></button></li>)}</ul></div>
            )}
          </div>
        )}
        {data && <p className="foot muted small">{data.pool.candidates} de {data.pool.films} películas cumplen lo que has pedido.</p>}
      </section>

      {!wide && (
        <Sheet open={composerOpen} onClose={() => setComposerOpen(false)} title="¿Qué ves esta noche?" wide>
          <Slate clap={clap}>{composer}</Slate>
          <button className="btn btn--go btn--block sticky-cta" onClick={() => setComposerOpen(false)}>Ver {data?.pool.candidates ?? ''} opciones</button>
        </Sheet>
      )}
      <ReasonSheet card={reasonFor} reasons={boot.reasons} onClose={() => setReasonFor(null)}
                   onPick={code => { const c = reasonFor; setReasonFor(null); if (c) void feedback(c, 'dismiss', code) }} />
      <AcceptSheet card={accepted} onClose={() => setAccepted(null)} onOpen={() => { const id = accepted?.id ?? null; setAccepted(null); openFilm(id) }} />
      <EvaluateSheet open={evalOpen} onClose={() => setEvalOpen(false)} ctx={ctx} />
    </div>
  )
}
