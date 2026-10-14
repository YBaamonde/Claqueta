import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import { relDate } from '../lib'
import { useApp } from '../store'
import type { Bootstrap, Job, Preset, SettingItem, SettingsResponse } from '../types'

type Service = 'tmdb' | 'jellyfin' | 'jellyseerr' | 'radarr' | 'letterboxd' | 'llm'

const SERVICES: { id: Service; title: string; desc: string }[] = [
  { id: 'tmdb', title: 'TMDB: carteles y datos', desc: 'Pone carteles, reparto, duración y plataformas de streaming. Es gratuito y es lo que más mejora la app.' },
  { id: 'jellyfin', title: 'Jellyfin: tu biblioteca', desc: 'Sabe qué tienes en casa, te lleva a verla con un toque e importa lo que ya has visto.' },
  { id: 'jellyseerr', title: 'Jellyseerr: pedir películas', desc: 'Si una sugerencia no está en casa, la pides sin salir de Claqueta.' },
  { id: 'radarr', title: 'Radarr: progreso de descarga', desc: 'Opcional. Solo para ver cuánto falta de lo que has pedido.' },
  { id: 'letterboxd', title: 'Letterboxd: tu diario', desc: 'Lectura pública de tu perfil por RSS. Nunca escribe en tu cuenta.' },
  { id: 'llm', title: 'LLM: afinar fichas y entenderte', desc: 'Opcional y gratuito. Valora el ritmo y el tono de cada película y entiende frases como «cansado y con hora y media».' },
]

const ACTIONS: { id: string; label: string; desc: string; need?: Service }[] = [
  { id: 'jellyfin', label: 'Sincronizar Jellyfin', desc: 'Marca lo que tienes en casa e importa tu historial de reproducciones.', need: 'jellyfin' },
  { id: 'letterboxd-rss', label: 'Leer mi RSS de Letterboxd', desc: 'Trae tus últimas ~50 entradas del diario.', need: 'letterboxd' },
  { id: 'resolve', label: 'Identificar películas en TMDB', desc: 'Añade carteles y datos reales al catálogo inicial y a lo importado.', need: 'tmdb' },
  { id: 'expand', label: 'Ampliar el catálogo', desc: 'Trae afines a tus favoritas, las mejor valoradas y clásicos de cada década.', need: 'tmdb' },
  { id: 'enrich', label: 'Enriquecer con el LLM', desc: 'Afina ritmo, tono y riesgo de tostón de cada ficha (respeta el tope diario).', need: 'llm' },
  { id: 'seerr', label: 'Actualizar peticiones', desc: 'Comprueba qué se ha descargado ya.', need: 'jellyseerr' },
]
const LAST_RUN: Record<string, string> = {
  jellyfin: 'jellyfin_sync', 'letterboxd-rss': 'letterboxd_rss', resolve: 'resolve', expand: 'expand', enrich: 'enrich', seerr: 'seerr',
}

const n = (v: unknown) => (typeof v === 'number' ? v : 0)
const pl = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`

/** Resumen en español de lo que hizo una tarea terminada. */
function describeJob(j: Job): string {
  if (j.state === 'error') return j.error ?? 'Ha fallado'
  const r = j.result
  switch (j.kind) {
    case 'import_letterboxd':
    case 'sync_lb_rss': {
      const parts = [`${pl(n(r.watched), 'vista', 'vistas')}`, `${pl(n(r.watchlist), 'pendiente', 'pendientes')}`]
      if (n(r.failed)) parts.push(`${pl(n(r.failed), 'no se pudo importar', 'no se pudieron importar')}`)
      return `${pl(n(r.imported), 'película importada', 'películas importadas')}: ${parts.join(', ')}.${r.tmdb ? '' : ' Sin TMDB no hay carteles: añade tu clave en Ajustes.'}`
    }
    case 'sync_jellyfin':
      return `${pl(n(r.items), 'película en tu biblioteca', 'películas en tu biblioteca')}; ${pl(n(r.history), 'marcada como vista', 'marcadas como vistas')} por tu historial.`
    case 'resolve':
      return `${pl(n(r.resolved), 'película identificada', 'películas identificadas')}${n(r.missed) ? `, ${n(r.missed)} sin coincidencia` : ''}.`
    case 'expand':
      return `${pl(n(r.added), 'película nueva', 'películas nuevas')} en el catálogo; ${n(r.hydrated)} fichas completadas.`
    case 'enrich':
      return `${pl(n(r.enriched), 'ficha afinada', 'fichas afinadas')} con el LLM.`
    case 'seerr':
      return `${n(r.checked)} peticiones revisadas, ${n(r.changed)} con novedades.`
    case 'maintenance':
      return `${pl(n(r.hydrated), 'ficha completada', 'fichas completadas')}.`
    default:
      return 'Terminado.'
  }
}

function useJobs(onFinished: () => void) {
  const { toast, bump } = useApp()
  const [jobs, setJobs] = useState<Job[]>([])
  const watching = useRef<Set<string>>(new Set())
  const timer = useRef<number | undefined>(undefined)
  const cb = useRef(onFinished)
  cb.current = onFinished

  const poll = useCallback(async () => {
    try {
      const r = await api.get<{ jobs: Job[] }>('/api/jobs')
      setJobs(r.jobs)
      for (const j of r.jobs) {
        if (watching.current.has(j.id) && (j.state === 'done' || j.state === 'error')) {
          watching.current.delete(j.id)
          if (j.state === 'done') toast(`${j.title}: terminado`, { tone: 'ok' })
          else toast(j.error ?? `${j.title}: error`, { tone: 'error', ms: 8000 })
          bump()
          cb.current()
        }
      }
      if (r.jobs.some(j => j.state === 'running' || j.state === 'queued')) timer.current = window.setTimeout(poll, 1200)
    } catch { timer.current = window.setTimeout(poll, 4000) }
  }, [toast, bump])

  useEffect(() => { void poll(); return () => window.clearTimeout(timer.current) }, [poll])
  const track = useCallback((job: Job) => {
    watching.current.add(job.id)
    window.clearTimeout(timer.current)
    void poll()
  }, [poll])
  return { jobs, track }
}

function Panel({ title, desc, status, children, id }: { title: string; desc?: string; status?: boolean; children: React.ReactNode; id?: string }) {
  return (
    <section className="panel" id={id}>
      <header className="panel__head">
        <h2>{title}{status !== undefined && <span className={`dot ${status ? 'dot--on' : ''}`} role="img" aria-label={status ? 'Configurado' : 'Sin configurar'} />}</h2>
        {desc && <p>{desc}</p>}
      </header>
      {children}
    </section>
  )
}

function FieldInput({ item, value, onChange }: { item: SettingItem; value: unknown; onChange: (v: unknown) => void }) {
  const id = `s-${item.key}`
  if (item.kind === 'bool') {
    return (
      <label className="switch"><input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} /><span>{item.label}</span></label>
    )
  }
  return (
    <div className="frow">
      <label htmlFor={id}>{item.label}</label>
      <input id={id} type={item.kind === 'number' ? 'number' : 'text'} value={value === null || value === undefined ? '' : String(value)}
             autoComplete="off" spellCheck={false} placeholder={item.secret && item.is_set ? 'Guardada. Escribe para cambiarla' : ''}
             onFocus={e => { if (item.secret && String(value).includes('•')) e.currentTarget.select() }}
             onChange={e => onChange(item.kind === 'number' ? e.target.value : e.target.value)} />
      {item.help && <small>{item.help}</small>}
    </div>
  )
}

export default function Settings({ boot, onChanged }: { boot: Bootstrap; onChanged: () => Promise<void> }) {
  const { toast, bump, version } = useApp()
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [testing, setTesting] = useState<Service | null>(null)
  const [results, setResults] = useState<Partial<Record<Service, { ok: boolean; message: string }>>>({})
  const [files, setFiles] = useState<File[]>([])
  const [drag, setDrag] = useState(false)
  const [importing, setImporting] = useState(false)
  const { jobs, track } = useJobs(() => void onChanged())

  const load = useCallback(async () => {
    const r = await api.get<SettingsResponse>('/api/settings')
    setData(r)
    setWeights(Object.fromEntries(Object.entries(r.weights).map(([k, w]) => [k, w.value])))
  }, [])
  useEffect(() => { void load().catch(e => toast((e as Error).message, { tone: 'error' })) }, [load, toast, version])

  const val = (it: SettingItem) => (it.key in draft ? draft[it.key] : it.value)
  const group = (g: string) => (data?.settings ?? []).filter(s => s.group === g)

  const save = async (keys: string[]) => {
    const values = Object.fromEntries(keys.filter(k => k in draft).map(k => [k, draft[k]]))
    if (!Object.keys(values).length) return true
    try {
      const r = await api.put<SettingsResponse>('/api/settings', { values })
      setData(r)
      setDraft(d => Object.fromEntries(Object.entries(d).filter(([k]) => !keys.includes(k))))
      await onChanged()
      return true
    } catch (e) { toast((e as Error).message, { tone: 'error', ms: 6000 }); return false }
  }

  const saveAndTest = async (svc: Service) => {
    const keys = group(svc).map(s => s.key)
    if (!(await save(keys))) return
    setTesting(svc)
    try {
      const r = await api.post<{ ok: boolean; message: string }>(`/api/settings/test/${svc}`)
      setResults(x => ({ ...x, [svc]: r }))
    } catch (e) { setResults(x => ({ ...x, [svc]: { ok: false, message: (e as Error).message } })) } finally { setTesting(null) }
  }

  const applyPreset = (p: Preset) => setDraft(d => ({ ...d, llm_base_url: p.base_url, llm_model: p.model, llm_extra_body: p.extra, llm_tpm: Number(p.tpm) }))

  const run = async (id: string) => {
    try { track(await api.post<Job>(`/api/sync/${id}`)) } catch (e) { toast((e as Error).message, { tone: 'error', ms: 6000 }) }
  }

  const doImport = async () => {
    if (!files.length) return
    const form = new FormData()
    files.forEach(f => form.append('files', f, f.name))
    setImporting(true)
    try {
      track(await api.upload<Job>('/api/import/letterboxd', form))
      setFiles([])
      toast('Importando tu Letterboxd. Puedes seguir usando la app', { tone: 'ok' })
    } catch (e) { toast((e as Error).message, { tone: 'error', ms: 7000 }) } finally { setImporting(false) }
  }

  const saveWeights = async (reset = false) => {
    if (!data) return
    const w = reset ? Object.fromEntries(Object.entries(data.weights).map(([k, v]) => [k, v.default])) : weights
    try {
      const r = await api.put<SettingsResponse>('/api/settings', { weights: w, values: 'anti_toston_default' in draft ? { anti_toston_default: draft.anti_toston_default } : {} })
      setData(r)
      setWeights(Object.fromEntries(Object.entries(r.weights).map(([k, v]) => [k, v.value])))
      setDraft(d => { const { anti_toston_default: _, ...rest } = d; return rest })
      toast(reset ? 'Pesos restaurados' : 'Pesos guardados', { tone: 'ok' })
    } catch (e) { toast((e as Error).message, { tone: 'error' }) }
  }

  const demo = async (load: boolean) => {
    try {
      if (load) { await api.post('/api/demo/load'); toast('Datos de ejemplo cargados') }
      else { await api.del('/api/demo/history'); toast('Historial de ejemplo borrado') }
      await onChanged(); bump()
    } catch (e) { toast((e as Error).message, { tone: 'error' }) }
  }

  if (!data) return <div className="skeleton" />
  const running = jobs.filter(j => j.state === 'running' || j.state === 'queued')
  const recent = jobs.filter(j => j.state === 'error' || j.state === 'done').slice(0, 3)
  const llm = boot.llm
  const usedPct = llm.daily_cap ? Math.min(100, Math.round((100 * llm.used_today) / llm.daily_cap)) : 0
  const antiDefault = 'anti_toston_default' in draft ? !!draft.anti_toston_default : boot.defaults.anti_toston

  return (
    <div className="settings">
      <h1 className="h1">Ajustes</h1>
      <p className="lead">Todo es opcional: Claqueta funciona desde el primer minuto con su catálogo de ejemplo. Cada conexión mejora algo concreto.</p>

      {(running.length > 0 || recent.length > 0) && (
        <section className="jobs" aria-live="polite">
          {running.map(j => (
            <div className="job" key={j.id}>
              <b>{j.title}</b><span>{j.message}</span>
              <div className="progress"><i style={{ width: j.total ? `${Math.round((100 * j.progress) / j.total)}%` : '35%' }} className={j.total ? '' : 'indeterminate'} /></div>
            </div>
          ))}
          {running.length === 0 && recent.map(j => (
            <div className={`job job--${j.state}`} key={j.id}><b>{j.title}</b>
              <span>{describeJob(j)}</span></div>
          ))}
        </section>
      )}

      <Panel title="Importar tu Letterboxd" id="importar"
             desc="Letterboxd no tiene API pública: exporta tus datos y súbelos aquí. Claqueta solo lee el archivo; nunca escribe en tu cuenta ni toca tu watchlist.">
        <ol className="howto">
          <li>En letterboxd.com: <b>Ajustes → Importar y exportar → Exportar tus datos</b>.</li>
          <li>Sube el ZIP tal cual (o los CSV sueltos: watched, ratings, diary, watchlist, likes).</li>
        </ol>
        <label className={`drop ${drag ? 'is-over' : ''}`}
               onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
               onDrop={e => { e.preventDefault(); setDrag(false); setFiles(Array.from(e.dataTransfer.files)) }}>
          <Icon name="upload" size={26} />
          <span>{files.length ? files.map(f => f.name).join(', ') : 'Arrastra aquí el ZIP o los CSV, o pulsa para elegirlos'}</span>
          <input type="file" multiple accept=".zip,.csv" onChange={e => setFiles(Array.from(e.target.files ?? []))} />
        </label>
        <div className="row">
          <button className="btn btn--go" disabled={!files.length || importing} onClick={doImport}>{importing ? 'Subiendo…' : 'Importar'}</button>
          <span className="muted small">Última importación: {relDate(boot.last_runs.letterboxd_import)}</span>
        </div>
        <div className="row row--wrap">
          <a className="linkbtn" href="/api/export/letterboxd/diary" download><Icon name="download" size={16} /> Exportar lo visto aquí (CSV para Letterboxd)</a>
          <a className="linkbtn" href="/api/export/letterboxd/watchlist" download><Icon name="download" size={16} /> Exportar pendientes (CSV)</a>
        </div>
      </Panel>

      {SERVICES.map(s => {
        const items = group(s.id)
        const keys = items.map(i => i.key)
        const dirty = keys.some(k => k in draft)
        const res = results[s.id]
        return (
          <Panel key={s.id} id={s.id} title={s.title} desc={s.desc} status={boot.configured[s.id]}>
            {s.id === 'llm' && (
              <div className="presets">
                <p className="muted small">Elige un proveedor gratuito y rellena solo la clave:</p>
                <div className="chips">{data.presets.map(p => <button key={p.id} className="chip" onClick={() => applyPreset(p)} title={p.help}>{p.label}</button>)}</div>
                {data.presets.map(p => draft.llm_base_url === p.base_url && <p key={p.id} className="muted small">{p.help}</p>)}
              </div>
            )}
            <div className="form">
              {items.map(it => <FieldInput key={it.key} item={it} value={val(it)} onChange={v => setDraft(d => ({ ...d, [it.key]: v }))} />)}
            </div>
            {s.id === 'llm' && llm.daily_cap > 0 && (
              <div className="usage"><span>Tokens hoy: {llm.used_today.toLocaleString('es-ES')} de {llm.daily_cap.toLocaleString('es-ES')}</span>
                <div className="progress"><i style={{ width: `${usedPct}%` }} /></div></div>
            )}
            <div className="row">
              <button className="btn btn--ghost" onClick={() => void saveAndTest(s.id)} disabled={testing === s.id}>
                {testing === s.id ? 'Probando…' : dirty ? 'Guardar y probar' : 'Probar conexión'}
              </button>
              {dirty && <button className="btn btn--go" onClick={() => void save(keys)}>Guardar</button>}
            </div>
            {res && <p className={`test ${res.ok ? 'test--ok' : 'test--bad'}`} role="status">{res.ok ? '✓ ' : '✕ '}{res.message}</p>}
          </Panel>
        )
      })}

      <Panel title="Catálogo y tareas" desc="Se ejecutan en segundo plano y algunas se repiten solas. Aquí puedes lanzarlas a mano.">
        <ul className="actions-list">
          {ACTIONS.map(a => {
            const blocked = a.need && !boot.configured[a.need]
            return (
              <li key={a.id}>
                <div><b>{a.label}</b><span>{a.desc}</span>
                  <small>{blocked ? `Necesita configurar ${a.need === 'llm' ? 'un LLM' : a.need?.toUpperCase() === 'TMDB' ? 'TMDB' : a.need}` : `Última vez: ${relDate(boot.last_runs[LAST_RUN[a.id]])}`}</small></div>
                <button className="btn btn--ghost btn--sm" disabled={!!blocked || running.length > 0} onClick={() => void run(a.id)}>Lanzar</button>
              </li>
            )
          })}
        </ul>
        <p className="muted small">{boot.stats.films} películas en el catálogo, {boot.stats.complete} con ficha completa, {boot.stats.enrich.enriched} con perfil afinado.</p>
      </Panel>

      <Panel title="Cómo decide el motor" desc="Estos pesos reparten la importancia entre tu gusto, el ánimo, la calidad… Los valores por defecto funcionan bien; toca solo si algo te chirría.">
        <div className="weights">
          {Object.entries(data.weights).map(([k, w]) => (
            <label key={k} className="weight">
              <span><b>{w.label}</b><small>{w.help}</small></span>
              <input type="range" min={w.min} max={w.max} step={0.01} value={weights[k] ?? w.value}
                     onChange={e => setWeights(x => ({ ...x, [k]: Number(e.target.value) }))} aria-label={w.label} />
              <output>{Math.round((weights[k] ?? w.value) * 100)}</output>
            </label>
          ))}
        </div>
        <label className="switch"><input type="checkbox" checked={antiDefault} onChange={e => setDraft(d => ({ ...d, anti_toston_default: e.target.checked }))} />
          <span>Protección anti-tostón activada por defecto</span></label>
        <div className="row"><button className="btn btn--go" onClick={() => void saveWeights()}>Guardar pesos</button>
          <button className="btn btn--ghost" onClick={() => void saveWeights(true)}>Restaurar valores</button></div>
      </Panel>

      <Panel title="Datos de ejemplo" desc="Un historial inventado de 30 películas para probar las recomendaciones sin importar nada. Bórralo cuando tengas el tuyo.">
        <div className="row">
          <button className="btn btn--ghost" onClick={() => void demo(true)}>Cargar historial de ejemplo</button>
          <button className="btn btn--ghost" onClick={() => void demo(false)} disabled={!boot.stats.demo}>Borrar el de ejemplo ({boot.stats.demo})</button>
        </div>
      </Panel>

      <p className="foot muted small">Claqueta {boot.version}. Tus datos viven en el volumen del contenedor; no se envía nada a terceros salvo las consultas a los servicios que configures.</p>
    </div>
  )
}
