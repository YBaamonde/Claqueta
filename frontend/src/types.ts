export type Status = 'watched' | 'watchlist' | 'parked' | 'watching' | 'never' | 'none'
export type Scope = 'all' | 'library' | 'streaming'
export type Company = 'solo' | 'pareja' | 'amigos' | 'familia' | 'peques'

export interface Ctx {
  moods: string[]
  company: Company
  max_minutes: number | null
  focus: number
  adventure: number
  eras: string[]
  genres_in: string[]
  genres_out: string[]
  scope: Scope
  subtitles_ok: boolean
  anti_toston: boolean
  allow_seen: boolean
}

export const DEFAULT_CTX: Ctx = {
  moods: [], company: 'solo', max_minutes: null, focus: 3, adventure: 0.35, eras: [],
  genres_in: [], genres_out: [], scope: 'all', subtitles_ok: true, anti_toston: true, allow_seen: false,
}

export interface Mood { id: string; label: string; emoji: string; blurb: string; colors: [string, string] }
export interface Option { id: string; label: string; emoji?: string }
export interface ReasonDef { code: string; label: string; emoji: string; hint: string }

export interface Avail {
  jellyfin: { available: boolean; url: string | null }
  seerr: { enabled: boolean; status?: string; url?: string | null; can_request?: boolean }
  streaming: { name: string; logo: string | null }[]
  streaming_link?: string | null
}

export interface FilmLight {
  id: number | null
  tmdb_id: number | null
  title: string
  original_title: string | null
  year: number | null
  runtime: number | null
  genres: string[]
  directors?: string[]
  poster: string | null
  vote_average: number | null
  status: Status
  my_rating?: number | null
  liked?: boolean
  watched_date?: string | null
  availability?: Avail
  aged?: string
  lang?: string | null
  kind?: 'local' | 'tmdb'
}

export interface Reason { kind: string; icon: string; text: string }
export interface Warning { kind: string; text: string }

export interface FilmCard extends FilmLight {
  overview: string | null
  tagline: string | null
  cast: string[]
  countries: string[]
  min_age: number | null
  vote_count: number
  imdb_id: string | null
  backdrop: string | null
  trailer: string | null
  letterboxd: string | null
  attrs: Record<string, number>
  tags: string[]
  attrs_source: string
  match?: number
  score?: number
  reasons?: Reason[]
  warnings?: Warning[]
  aged_info?: { risk: number; label: string; note: string }
  pitch?: string
  suggested_reasons?: string[]
  flags?: string[]
  rank?: number
  verdict?: 'go' | 'maybe' | 'skip'
}

export interface Deck {
  session_id: string
  context: Ctx
  effective: { max_minutes: number | null; subtitles_ok: boolean }
  deck: FilmCard[]
  pool: { films: number; candidates: number }
  adjustments: string[]
  relaxed: string[]
  empty_reason: string | null
  dismissed: number
  can_undo: boolean
  toast?: string
  restored_film_id?: number
}

export interface Bootstrap {
  version: string
  moods: Mood[]
  companies: Option[]
  eras: Option[]
  genres: string[]
  reasons: ReasonDef[]
  configured: Record<'tmdb' | 'jellyfin' | 'jellyseerr' | 'radarr' | 'llm' | 'letterboxd', boolean>
  stats: {
    films: number; complete: number; jellyfin: number; watched: number; watchlist: number; parked: number
    watching: number; demo: number; enrich: { total: number; enriched: number; pending: number }
  }
  last_context: Partial<Ctx>
  defaults: { anti_toston: boolean }
  needs_onboarding: boolean
  llm: { presets: Preset[]; used_today: number; daily_cap: number }
  last_runs: Record<string, string | null>
}

export interface Preset { id: string; label: string; base_url: string; model: string; extra: string; tpm: string; help: string }

export interface SettingItem {
  key: string; group: string; label: string; kind: 'text' | 'number' | 'bool' | 'json'
  help?: string; secret: boolean; value: unknown; is_set: boolean
}
export interface WeightItem { key: string; label: string; help: string; min: number; max: number; value: number; default: number }
export interface SettingsResponse { settings: SettingItem[]; weights: Record<string, WeightItem>; presets: Preset[]; configured?: Bootstrap['configured'] }

export interface Job {
  id: string; kind: string; title: string; state: 'queued' | 'running' | 'done' | 'error'
  progress: number; total: number; message: string; error: string | null; result: Record<string, unknown>
}

export interface LibraryResponse {
  items: FilmLight[]; total: number
  counts: Record<'parked' | 'watchlist' | 'watched' | 'watching' | 'never' | 'jellyfin' | 'requested', number>
}

export interface PathFilm extends FilmLight { path_title: string }
export interface CinePath { slug: string; title: string; emoji: string; blurb: string; films: PathFilm[]; seen: number; total: number; next_id: number | null }

export interface Affinity { name: string; affinity: number; count: number | null; avg?: number | null }
export interface TasteResponse {
  n_rated: number; n_watched: number; mean_rating: number; old_tolerance: number; old_label: string; old_seen: number
  genres_up: Affinity[]; genres_down: Affinity[]; directors: Affinity[]; decades: Affinity[]; countries: Affinity[]
  attr_tilt: { key: string; label: string; value: number }[]
  favorites: FilmLight[]
  learned: { counts: Record<string, number>; genre: Record<string, number>; people: Record<string, number>; old_tol: number; adventure: number }
  feedback_total: number; cold_start: boolean
}

export interface HomeResponse {
  watching: FilmLight[]; parked: FilmLight[]; recent: FilmLight[]; requested: number
  stats: Bootstrap['stats']; configured: Bootstrap['configured']; needs_onboarding: boolean
}

export interface DownloadItem extends FilmLight { download: { pct: number; eta: string | null; state: string } | null }
