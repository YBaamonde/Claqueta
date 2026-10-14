import type { FilmCard } from '../types'
import { Poster } from './Poster'

/** Las siguientes tomas, en una tira de película con perforaciones. Un toque la sube al primer puesto. */
export function FilmStrip({ items, onPick }: { items: FilmCard[]; onPick: (c: FilmCard) => void }) {
  if (!items.length) return null
  return (
    <div className="strip" aria-label="Siguientes opciones">
      <div className="strip__holes" aria-hidden="true" />
      <ol className="strip__list">
        {items.map(c => (
          <li key={c.id}>
            <button className="strip__item" onClick={() => onPick(c)} aria-label={`${c.title}, ${c.match}% de encaje. Ver primero`}>
              <Poster film={c} compact />
              <span className="strip__match">{c.match}%</span>
              <span className="strip__title">{c.title}</span>
            </button>
          </li>
        ))}
      </ol>
      <div className="strip__holes" aria-hidden="true" />
    </div>
  )
}
