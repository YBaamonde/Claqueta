import { useState } from 'react'
import { hash } from '../lib'
import type { FilmLight } from '../types'

interface Palette { bg: string; fg: string; ac: string }

const BY_GENRE: Record<string, Palette> = {
  Terror: { bg: '#1b0f13', fg: '#efe6d6', ac: '#d12c35' },
  Comedia: { bg: '#f1bf45', fg: '#1b2440', ac: '#e4572e' },
  Drama: { bg: '#2a3856', fg: '#f3ead9', ac: '#e8b05c' },
  'Ciencia ficción': { bg: '#0c2a3d', fg: '#c6ecff', ac: '#ff6b35' },
  Romance: { bg: '#f2a7b9', fg: '#3b1c2c', ac: '#fff0cf' },
  Acción: { bg: '#c6362c', fg: '#fff0cf', ac: '#13181f' },
  Animación: { bg: '#35b56f', fg: '#fffdf2', ac: '#ffd23f' },
  Familia: { bg: '#35b56f', fg: '#fffdf2', ac: '#ffd23f' },
  Crimen: { bg: '#121a23', fg: '#f2e9d8', ac: '#f2aa4c' },
  Suspense: { bg: '#161d2b', fg: '#ece4d4', ac: '#e65a4f' },
  Misterio: { bg: '#2d1f50', fg: '#e8dcff', ac: '#7bdff2' },
  Bélica: { bg: '#474c38', fg: '#efe9d2', ac: '#d9a441' },
  Aventura: { bg: '#1d504b', fg: '#fff3c9', ac: '#f28c28' },
  Fantasía: { bg: '#3a2766', fg: '#ffe9b8', ac: '#6ee0c1' },
  Western: { bg: '#b8661e', fg: '#2a190c', ac: '#f6e2b9' },
  Música: { bg: '#5b2a6e', fg: '#ffe6f5', ac: '#ffcf4a' },
  Historia: { bg: '#4b3a2a', fg: '#f1e4cc', ac: '#c9a05c' },
  Documental: { bg: '#2c3e3a', fg: '#e8f0e6', ac: '#e9c46a' },
}
const FALLBACK: Palette = { bg: '#2b2437', fg: '#f4ebdc', ac: '#ffb547' }

export const paletteFor = (genres: string[]): Palette => {
  for (const g of genres) if (BY_GENRE[g]) return BY_GENRE[g]
  return FALLBACK
}

/** Cartel tipográfico generado: siempre el mismo para la misma película, sin necesidad de imagen. */
function Generated({ film, compact }: { film: Pick<FilmLight, 'title' | 'year' | 'genres' | 'directors' | 'id'>; compact: boolean }) {
  const p = paletteFor(film.genres)
  const h = hash(`${film.title}|${film.year ?? ''}`)
  const shape = h % 5
  const off = (h >> 5) % 40
  const title = film.title.length > 38 ? film.title.slice(0, 36) + '…' : film.title
  const size = title.length > 26 ? 21 : title.length > 16 ? 26 : title.length > 9 ? 32 : 40
  return (
    <div className="poster-gen" style={{ background: p.bg, color: p.fg }} role="img" aria-label={`Cartel de ${film.title}`}>
      <svg viewBox="0 0 200 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        {shape === 0 && <circle cx={60 + off} cy={105} r={62} fill={p.ac} />}
        {shape === 1 && <path d={`M0 ${190 + off} L200 ${90 + off} V300 H0Z`} fill={p.ac} />}
        {shape === 2 && [0, 1, 2, 3, 4].map(i => <rect key={i} x={-10 + i * 46 + off / 4} y="0" width="20" height="300" fill={p.ac} opacity={0.9 - i * 0.14} />)}
        {shape === 3 && <path d={`M${30 + off} 230 V120 a${50} ${50} 0 0 1 ${100} 0 V230Z`} fill={p.ac} />}
        {shape === 4 && [0, 1, 2].map(i => <circle key={i} cx={100} cy={110} r={24 + i * 26} fill="none" stroke={p.ac} strokeWidth="9" opacity={1 - i * 0.28} />)}
      </svg>
      <div className="poster-gen__text">
        <b style={{ fontSize: compact ? `max(10px, ${size / 2}cqw)` : `${size / 2}cqw` }}>{title}</b>
        {!compact && (
          <span>{film.year}{film.directors && film.directors[0] ? `  ${film.directors[0]}` : ''}</span>
        )}
      </div>
    </div>
  )
}

export function Poster({ film, compact = false, className = '' }: {
  film: Pick<FilmLight, 'title' | 'year' | 'genres' | 'directors' | 'poster' | 'id'>
  compact?: boolean
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  return (
    <div className={`poster ${className}`}>
      {film.poster && !failed
        ? <img src={film.poster} alt={`Cartel de ${film.title}`} loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : <Generated film={film} compact={compact} />}
    </div>
  )
}
