import { useState } from 'react'
import type { FilmCard, ReasonDef } from '../types'
import { Poster } from './Poster'
import { Sheet } from './Sheet'

/** «¿Qué le pasa?»: un toque descarta con motivo y la app aprende al instante. */
export function ReasonSheet({ card, reasons, onPick, onClose }: {
  card: FilmCard | null; reasons: ReasonDef[]; onPick: (code: string) => void; onClose: () => void
}) {
  const [more, setMore] = useState(false)
  const by = new Map(reasons.map(r => [r.code, r]))
  const order = (card?.suggested_reasons ?? reasons.map(r => r.code)).filter(c => by.has(c))
  const main = order.slice(0, 6)
  const rest = order.slice(6)
  const Btn = ({ code }: { code: string }) => {
    const r = by.get(code)!
    return (
      <button className="reason" onClick={() => { setMore(false); onPick(code) }}>
        <span className="reason__e" aria-hidden="true">{r.emoji}</span>
        <span className="reason__t"><b>{r.label}</b><small>{r.hint}</small></span>
      </button>
    )
  }
  return (
    <Sheet open={!!card} onClose={() => { setMore(false); onClose() }} title="¿Qué le pasa?">
      {card && (
        <>
          <div className="reason-film">
            <Poster film={card} compact />
            <div><b>{card.title}</b><span>{card.year}</span></div>
          </div>
          <div className="reasons-grid">{main.map(c => <Btn key={c} code={c} />)}</div>
          {rest.length > 0 && !more && <button className="linkbtn" onClick={() => setMore(true)}>Más motivos</button>}
          {more && <div className="reasons-grid">{rest.map(c => <Btn key={c} code={c} />)}</div>}
        </>
      )}
    </Sheet>
  )
}
