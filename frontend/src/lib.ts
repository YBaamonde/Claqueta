import type { FilmLight, Status } from './types'

export const fmtRuntime = (min: number | null | undefined): string => {
  if (!min) return ''
  const h = Math.floor(min / 60)
  const m = min % 60
  if (h === 0) return `${m} min`
  return m ? `${h} h ${String(m).padStart(2, '0')} min` : `${h} h`
}

export const fmtMinutes = (min: number | null): string => (min === null ? 'Sin límite' : fmtRuntime(min))

export const STATUS_LABEL: Record<Status, string> = {
  watched: 'Vista', watchlist: 'En mi watchlist', parked: 'Para otro día', watching: 'La estoy viendo',
  never: 'Nunca', none: 'Sin marcar',
}

export const clamp = (x: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x))

/** Hash determinista (FNV-1a) para que cada película tenga siempre el mismo cartel generado. */
export function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export const shortDirector = (f: Pick<FilmLight, 'directors'>) => (f.directors && f.directors[0]) || ''

export const relDate = (iso: string | null | undefined): string => {
  if (!iso) return 'nunca'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'nunca'
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins < 2) return 'ahora mismo'
  if (mins < 60) return `hace ${mins} min`
  if (mins < 60 * 24) return `hace ${Math.round(mins / 60)} h`
  return `hace ${Math.round(mins / 1440)} d`
}

export const ratingToStars = (r: number | null | undefined) => (r ? r.toFixed(1).replace('.0', '') : '')
