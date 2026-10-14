import { fmtRuntime } from '../lib'
import type { FilmCard } from '../types'
import { Availability } from './Availability'
import { Icon } from './Icon'
import { Poster } from './Poster'
import { Sheet } from './Sheet'

/** «¡Esta!»: lo que necesitas para empezar ya mismo. */
export function AcceptSheet({ card, onClose, onOpen }: { card: FilmCard | null; onClose: () => void; onOpen: () => void }) {
  return (
    <Sheet open={!!card} onClose={onClose} title="Toma buena">
      {card && (
        <div className="accept">
          <Poster film={card} className="accept__poster" />
          <h3>{card.title}</h3>
          <p className="muted">{card.year}{card.runtime ? `  ${fmtRuntime(card.runtime)}` : ''}</p>
          <Availability film={card} avail={card.availability} big />
          {card.trailer && (
            <a className="btn btn--ghost" href={`https://www.youtube.com/watch?v=${card.trailer}`} target="_blank" rel="noreferrer">
              <Icon name="play" size={18} /> Ver el tráiler
            </a>
          )}
          <p className="muted small">Queda en «La estoy viendo». Cuando acabes, valórala desde su ficha y afinaré las próximas.</p>
          <div className="accept__row">
            <button className="btn btn--ghost" onClick={onOpen}>Abrir ficha</button>
            <button className="btn btn--go" onClick={onClose}>Listo</button>
          </div>
        </div>
      )}
    </Sheet>
  )
}
