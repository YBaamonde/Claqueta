import { useState } from 'react'
import { api } from '../api'
import { fmtMinutes } from '../lib'
import { useApp } from '../store'
import type { Bootstrap, Company, Ctx, Scope } from '../types'
import { DEFAULT_CTX } from '../types'
import { Icon } from './Icon'

const TIMES: { label: string; v: number | null }[] = [
  { label: 'Sin límite', v: null }, { label: '1 h 30', v: 90 }, { label: '2 h', v: 120 }, { label: '2 h 30', v: 150 },
]
const FOCUS_LABEL = ['Cabeza apagada', 'Algo ligerito', 'Normal', 'Con ganas de atender', 'Atención total']
const ADV_LABEL = (v: number) => (v < 0.2 ? 'Apuesta segura' : v < 0.45 ? 'Casi seguro' : v < 0.7 ? 'Con un toque de riesgo' : 'Sorpréndeme')

export function Chip({ on, onClick, children, tone, title, disabled }: {
  on?: boolean; onClick?: () => void; children: React.ReactNode; tone?: 'ex'; title?: string; disabled?: boolean
}) {
  return (
    <button type="button" className={`chip ${on ? 'is-on' : ''} ${tone === 'ex' ? 'is-ex' : ''}`} aria-pressed={!!on}
            onClick={onClick} title={title} disabled={disabled}>
      {children}
    </button>
  )
}

function Field({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="field">
      <h3>{title}</h3>
      {hint && <p className="field__hint">{hint}</p>}
      {children}
    </section>
  )
}

export function summarize(ctx: Ctx, boot: Bootstrap): string[] {
  const out: string[] = []
  const moods = ctx.moods.map(id => boot.moods.find(m => m.id === id)?.label).filter(Boolean) as string[]
  out.push(moods.length ? moods.join(' + ') : 'Cualquier ánimo')
  if (ctx.company !== 'solo') out.push(boot.companies.find(c => c.id === ctx.company)?.label ?? ctx.company)
  if (ctx.max_minutes) out.push(`hasta ${fmtMinutes(ctx.max_minutes)}`)
  if (ctx.focus <= 2) out.push('cabeza apagada')
  if (ctx.focus >= 4) out.push('con atención')
  if (ctx.scope === 'library') out.push('solo en casa')
  if (ctx.scope === 'streaming') out.push('en streaming')
  if (ctx.eras.length) out.push(ctx.eras.map(e => boot.eras.find(x => x.id === e)?.label.split(' (')[0]).join(', '))
  if (ctx.genres_in.length) out.push(ctx.genres_in.join(', '))
  return out
}

export function ComposerBody({ ctx, onChange, boot, onReset }: {
  ctx: Ctx; onChange: (patch: Partial<Ctx>) => void; boot: Bootstrap; onReset: () => void
}) {
  const { toast } = useApp()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [showGenres, setShowGenres] = useState(ctx.genres_in.length + ctx.genres_out.length > 0)

  const toggle = (list: string[], v: string, max = 99) =>
    list.includes(v) ? list.filter(x => x !== v) : [...list, v].slice(-max)

  const cycleGenre = (g: string) => {
    if (ctx.genres_in.includes(g)) onChange({ genres_in: ctx.genres_in.filter(x => x !== g), genres_out: [...ctx.genres_out, g] })
    else if (ctx.genres_out.includes(g)) onChange({ genres_out: ctx.genres_out.filter(x => x !== g) })
    else onChange({ genres_in: [...ctx.genres_in, g] })
  }

  const interpret = async () => {
    const t = text.trim()
    if (t.length < 2) return
    setBusy(true)
    try {
      const r = await api.post<{ context: Partial<Ctx>; explanation: string; source: 'llm' | 'rules' }>('/api/context/parse', { text: t })
      const before = ctx
      onChange({ ...DEFAULT_CTX, ...r.context, allow_seen: ctx.allow_seen })
      setText('')
      toast(r.explanation || 'Hecho', { action: { label: 'Deshacer', run: () => onChange(before) }, ms: 6500 })
    } catch (e) {
      toast((e as Error).message, { tone: 'error' })
    } finally { setBusy(false) }
  }

  const time = ctx.max_minutes
  const customTime = time !== null && !TIMES.some(t => t.v === time)

  return (
    <div className="composer">
      <form className="ask" onSubmit={e => { e.preventDefault(); void interpret() }}>
        <label htmlFor="ask" className="sr-only">Cuéntamelo con tus palabras</label>
        <input id="ask" value={text} onChange={e => setText(e.target.value)} disabled={busy} autoComplete="off"
               placeholder="Cuéntamelo: «cansado, algo para reír, hora y media»" />
        <button className="btn btn--ghost btn--sm" type="submit" disabled={busy || text.trim().length < 2}>
          <Icon name="sparkle" size={16} /> {busy ? 'Leyendo…' : 'Entender'}
        </button>
      </form>

      <Field title="¿Qué te apetece?" hint="Elige hasta tres. El primero manda.">
        <div className="moods">
          {boot.moods.map(m => {
            const idx = ctx.moods.indexOf(m.id)
            return (
              <button key={m.id} type="button" className={`mood ${idx >= 0 ? 'is-on' : ''}`} aria-pressed={idx >= 0}
                      style={{ ['--ma' as string]: m.colors[0], ['--mb' as string]: m.colors[1] }}
                      title={m.blurb} onClick={() => onChange({ moods: toggle(ctx.moods, m.id, 3) })}>
                <span className="mood__e" aria-hidden="true">{m.emoji}</span>
                <span className="mood__l">{m.label}</span>
                {idx >= 0 && <span className="mood__n" aria-label={`Prioridad ${idx + 1}`}>{idx + 1}</span>}
              </button>
            )
          })}
        </div>
      </Field>

      <Field title="¿Con quién?">
        <div className="seg" role="radiogroup" aria-label="Compañía">
          {boot.companies.map(c => (
            <button key={c.id} type="button" role="radio" aria-checked={ctx.company === c.id}
                    className={`seg__b ${ctx.company === c.id ? 'is-on' : ''}`}
                    onClick={() => onChange({ company: c.id as Company })}>
              <span aria-hidden="true">{c.emoji}</span> {c.label}
            </button>
          ))}
        </div>
      </Field>

      <Field title="¿Cuánto tiempo tienes?">
        <div className="chips">
          {TIMES.map(t => <Chip key={t.label} on={time === t.v} onClick={() => onChange({ max_minutes: t.v })}>{t.label}</Chip>)}
          {customTime && <Chip on>{fmtMinutes(time)}</Chip>}
        </div>
        <input className="range" type="range" min={60} max={240} step={5} value={time ?? 240}
               aria-label="Duración máxima en minutos" aria-valuetext={fmtMinutes(time)}
               onChange={e => onChange({ max_minutes: Number(e.target.value) >= 240 ? null : Number(e.target.value) })} />
        <div className="range__ends"><span>1 h</span><b>{fmtMinutes(time)}</b><span>Sin límite</span></div>
      </Field>

      <Field title="¿Cuánta cabeza tienes?">
        <input className="range" type="range" min={1} max={5} step={1} value={ctx.focus} aria-valuetext={FOCUS_LABEL[ctx.focus - 1]}
               onChange={e => onChange({ focus: Number(e.target.value) })} />
        <div className="range__ends"><span>Zombi</span><b>{FOCUS_LABEL[ctx.focus - 1]}</b><span>Concentrado</span></div>
      </Field>

      <Field title="¿Cuánto riesgo quieres?">
        <input className="range" type="range" min={0} max={1} step={0.05} value={ctx.adventure} aria-valuetext={ADV_LABEL(ctx.adventure)}
               onChange={e => onChange({ adventure: Number(e.target.value) })} />
        <div className="range__ends"><span>Seguro</span><b>{ADV_LABEL(ctx.adventure)}</b><span>Sorpresa</span></div>
      </Field>

      <Field title="¿De qué época?" hint="Vacío = cualquiera.">
        <div className="chips">
          {boot.eras.map(e => <Chip key={e.id} on={ctx.eras.includes(e.id)} onClick={() => onChange({ eras: toggle(ctx.eras, e.id) })}>{e.label}</Chip>)}
        </div>
      </Field>

      <Field title="¿Dónde la ves?">
        <div className="seg" role="radiogroup" aria-label="Dónde">
          {([['all', 'Todo el catálogo'], ['library', 'Solo en casa'], ['streaming', 'Streaming']] as [Scope, string][]).map(([v, l]) => (
            <button key={v} type="button" role="radio" aria-checked={ctx.scope === v} className={`seg__b ${ctx.scope === v ? 'is-on' : ''}`}
                    onClick={() => onChange({ scope: v })}>{l}</button>
          ))}
        </div>
        {ctx.scope === 'library' && !boot.configured.jellyfin && (
          <p className="field__note">Conecta Jellyfin en Ajustes para saber qué tienes en casa.</p>
        )}
      </Field>

      <Field title="Géneros">
        <button type="button" className="linkbtn" onClick={() => setShowGenres(s => !s)} aria-expanded={showGenres}>
          {showGenres ? 'Ocultar' : ctx.genres_in.length + ctx.genres_out.length ? `${ctx.genres_in.length} sí, ${ctx.genres_out.length} no` : 'Elegir o excluir géneros'}
          <Icon name="down" size={16} className={showGenres ? 'flip' : ''} />
        </button>
        {showGenres && (
          <>
            <p className="field__hint">Un toque = sí, dos = no, tres = indiferente.</p>
            <div className="chips">
              {boot.genres.filter(g => g !== 'Película de TV').map(g => (
                <Chip key={g} on={ctx.genres_in.includes(g) || ctx.genres_out.includes(g)} tone={ctx.genres_out.includes(g) ? 'ex' : undefined}
                      onClick={() => cycleGenre(g)}>
                  {ctx.genres_in.includes(g) ? '✓ ' : ctx.genres_out.includes(g) ? '✕ ' : ''}{g}
                </Chip>
              ))}
            </div>
          </>
        )}
      </Field>

      <Field title="Afinar">
        <label className="switch"><input type="checkbox" checked={!ctx.subtitles_ok} onChange={e => onChange({ subtitles_ok: !e.target.checked })} />
          <span>Hoy sin subtítulos</span></label>
        <label className="switch"><input type="checkbox" checked={ctx.anti_toston} onChange={e => onChange({ anti_toston: e.target.checked })} />
          <span>Protégeme de los tostones <small>Baja los clásicos que han envejecido mal.</small></span></label>
        <label className="switch"><input type="checkbox" checked={ctx.allow_seen} onChange={e => onChange({ allow_seen: e.target.checked })} />
          <span>Incluir las que ya he visto</span></label>
      </Field>

      <button className="linkbtn linkbtn--danger" type="button" onClick={onReset}>
        <Icon name="refresh" size={16} /> Empezar de cero (olvida los descartes de esta noche)
      </button>
    </div>
  )
}
