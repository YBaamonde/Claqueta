import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import { Poster } from '../components/Poster'
import { go } from '../router'
import { useApp } from '../store'
import type { Affinity, TasteResponse } from '../types'

const REASON_ES: Record<string, string> = {
  too_long: 'muy larga', too_slow: 'muy lenta', too_dated: 'pinta a tostón', not_mood: 'no era mi ánimo', too_heavy: 'demasiado dura',
  too_light: 'demasiado ligera', too_weird: 'demasiado rara', too_known: 'demasiado típica', genre_no: 'género que no me va',
  people_no: 'director o reparto', subtitles: 'sin subtítulos', similar_recent: 'como lo último', seen: 'ya vista', later: 'otro día',
  never: 'nunca', save: 'guardadas', accept: 'aceptadas', dismiss: 'descartadas',
}

/** Barras divergentes: a la derecha lo que te gusta, a la izquierda lo que te pesa. */
function Diverging({ rows, empty }: { rows: Affinity[]; empty: string }) {
  if (!rows.length) return <p className="muted small">{empty}</p>
  const max = Math.max(0.2, ...rows.map(r => Math.abs(r.affinity)))
  return (
    <ul className="div">
      {rows.map(r => (
        <li key={r.name}>
          <span className="div__name">{r.name}</span>
          <span className="div__track" aria-hidden="true">
            <i className={r.affinity < 0 ? 'neg' : 'pos'} style={{ width: `${(Math.abs(r.affinity) / max) * 50}%` }} />
          </span>
          <span className="div__note">{r.count ? `${r.count} vistas${r.avg ? ` · ${r.avg.toFixed(1)}★` : ''}` : ''}</span>
        </li>
      ))}
    </ul>
  )
}

export default function Taste() {
  const { openFilm, toast, bump, version } = useApp()
  const [t, setT] = useState<TasteResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    api.get<TasteResponse>('/api/taste').then(setT).catch(e => setError((e as Error).message))
  }, [])
  useEffect(load, [load, version])

  const reset = async () => {
    if (!window.confirm('¿Olvidar todo lo aprendido de tus descartes? Tus valoraciones no se tocan.')) return
    await api.post('/api/taste/reset-learning')
    toast('He olvidado lo aprendido de tus descartes')
    bump()
  }

  if (error) return <p className="form-error" role="alert">{error}</p>
  if (!t) return <div className="skeleton" />

  const tol = Math.round(t.old_tolerance * 100)
  const learned = Object.entries(t.learned.counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])

  return (
    <div className="taste">
      <h1 className="h1">Lo que he aprendido de ti</h1>
      {t.cold_start ? (
        <div className="banner">
          <p><b>Todavía voy a ciegas.</b> Con menos de 8 películas valoradas mis sugerencias son genéricas.</p>
          <button className="btn btn--ghost btn--sm" onClick={() => go('empezar')}>Calibrar mi gusto</button>
        </div>
      ) : (
        <p className="lead">{t.n_watched} películas vistas, {t.n_rated} con nota (media {t.mean_rating.toFixed(1)}★).</p>
      )}

      <section className="panel tol">
        <h2>Tolerancia a los clásicos</h2>
        <div className="tol__gauge" role="img" aria-label={`${tol} sobre 100`}>
          <i style={{ left: `${tol}%` }} />
        </div>
        <div className="range__ends"><span>Prefiero lo reciente</span><span>Me encantan los clásicos</span></div>
        <p>{t.old_label}.</p>
        <p className="muted small">Se calcula comparando lo que puntúas en películas anteriores a 1975 con las modernas, y sube cuando aceptas clásicos que te propongo.</p>
      </section>

      <div className="taste__cols">
        <section className="panel"><h2>Géneros que te tiran</h2><Diverging rows={t.genres_up} empty="Aún no hay datos suficientes." /></section>
        <section className="panel"><h2>Géneros que te pesan</h2><Diverging rows={t.genres_down} empty="Nada que te pese de momento." /></section>
        <section className="panel"><h2>Directores</h2><Diverging rows={t.directors} empty="Valora más películas para ver tus directores." /></section>
        <section className="panel"><h2>Cómo te gusta el cine</h2>
          {t.attr_tilt.length ? (
            <ul className="div">
              {t.attr_tilt.map(a => (
                <li key={a.key}><span className="div__name">{a.label}</span>
                  <span className="div__track" aria-hidden="true"><i className={a.value < 0 ? 'neg' : 'pos'} style={{ width: `${Math.min(1, Math.abs(a.value) / 0.4) * 50}%` }} /></span>
                  <span className="div__note">{a.value > 0 ? 'te gusta más' : 'te gusta menos'}</span></li>
              ))}
            </ul>
          ) : <p className="muted small">Todavía no distingo qué rasgos buscas.</p>}
        </section>
      </div>

      {t.favorites.length > 0 && (
        <section className="panel"><h2>Tus favoritas</h2>
          <ul className="favs">
            {t.favorites.map(f => (
              <li key={f.id}><button onClick={() => openFilm(f.id)}><Poster film={{ ...f, directors: f.directors ?? [] }} compact /><span>{f.title}</span></button></li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <h2>Lo que he aprendido de tus descartes</h2>
        {t.feedback_total === 0 ? <p className="muted">Todavía no has descartado nada. Cada «Corten» con su motivo me enseña algo.</p> : (
          <>
            <p>{t.feedback_total} decisiones registradas:</p>
            <div className="chips">{learned.map(([k, n]) => <span className="chip" key={k}>{REASON_ES[k] ?? k} <b>{n}</b></span>)}</div>
            {Object.keys(t.learned.genre).length > 0 && (
              <p className="muted small">Ajustes por género: {Object.entries(t.learned.genre).map(([g, v]) => `${g} ${v > 0 ? '+' : ''}${(v * 100).toFixed(0)}`).join(', ')}.</p>
            )}
            <button className="linkbtn linkbtn--danger" onClick={reset}><Icon name="refresh" size={16} /> Olvidar lo aprendido de mis descartes</button>
          </>
        )}
      </section>
    </div>
  )
}
