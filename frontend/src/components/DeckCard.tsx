import { motion, useMotionValue, useTransform } from 'framer-motion'
import { useState } from 'react'
import { fmtRuntime } from '../lib'
import type { FilmCard } from '../types'
import { Availability } from './Availability'
import { Icon } from './Icon'
import { Poster } from './Poster'

const ATTR_ES: Record<string, string> = {
  pace: 'Ritmo', intensity: 'Intensidad', tension: 'Tensión', humor: 'Humor', warmth: 'Calidez',
  darkness: 'Oscuridad', emotional: 'Emoción', complexity: 'Complejidad',
}

function Toston({ risk, label, note }: { risk: number; label: string; note: string }) {
  const lvl = Math.max(1, Math.min(5, Math.ceil(risk * 5)))
  return (
    <div className="toston" aria-label={`Prueba del tostón: ${label}`}>
      <div className="toston__bar" aria-hidden="true">
        {[1, 2, 3, 4, 5].map(i => <i key={i} className={i <= lvl ? `on l${lvl}` : ''} />)}
      </div>
      <div><b>{label}</b><span>{note}</span></div>
    </div>
  )
}

export function DeckCard({ card, take, onCut, onSave, onAccept, onOpen, dir }: {
  card: FilmCard; take: number
  onCut: () => void; onSave: () => void; onAccept: () => void; onOpen: () => void; dir: number
}) {
  const x = useMotionValue(0)
  const rotate = useTransform(x, [-220, 0, 220], [-7, 0, 7])
  const cutOp = useTransform(x, [-140, -30, 0], [1, 0.25, 0])
  const goOp = useTransform(x, [0, 30, 140], [0, 0.25, 1])
  const [showAttrs, setShowAttrs] = useState(false)

  return (
    <motion.article
      className="card" style={{ x, rotate }} drag="x" dragSnapToOrigin dragElastic={0.5} dragMomentum={false}
      dragConstraints={{ left: 0, right: 0 }}
      onDragEnd={(_, i) => {
        if (i.offset.x < -110 || i.velocity.x < -700) onCut()
        else if (i.offset.x > 110 || i.velocity.x > 700) onAccept()
      }}
      initial={{ opacity: 0, x: 60 * dir, scale: 0.97 }} animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -140 * dir, rotate: -5 * dir, transition: { duration: 0.22 } }}
      transition={{ type: 'spring', stiffness: 380, damping: 34 }}
    >
      <motion.div className="stamp stamp--cut" style={{ opacity: cutOp }} aria-hidden="true">Corten</motion.div>
      <motion.div className="stamp stamp--go" style={{ opacity: goOp }} aria-hidden="true">¡Esta!</motion.div>

      <div className="card__top">
        <button className="card__poster" onClick={onOpen} aria-label={`Ver ficha de ${card.title}`}>
          <Poster film={card} />
        </button>
        <div className="card__head">
          <p className="take">Toma {take}</p>
          <h2 className="card__title">{card.title}</h2>
          {card.original_title && card.original_title !== card.title && <p className="card__orig">{card.original_title}</p>}
          <div className="meta">
            {card.year && <span>{card.year}</span>}
            {card.runtime ? <span>{fmtRuntime(card.runtime)}</span> : null}
            {card.directors && card.directors[0] && <span>{card.directors[0]}</span>}
            {card.min_age ? <span className="meta__age">+{card.min_age}</span> : null}
          </div>
          <div className="genres">{card.genres.map(g => <span key={g}>{g}</span>)}</div>
          <div className="match" aria-label={`${card.match} por ciento de encaje`}>
            <b>{card.match}</b><span>% de encaje</span>
          </div>
        </div>
      </div>

      {card.pitch && <p className="pitch">{card.pitch}</p>}

      <ul className="reasons">
        {(card.reasons ?? []).map((r, i) => <li key={i}><span aria-hidden="true">{r.icon}</span>{r.text}</li>)}
        {(card.warnings ?? []).map((w, i) => <li key={`w${i}`} className="warn"><Icon name="warn" size={16} />{w.text}</li>)}
      </ul>

      {card.aged_info && <Toston risk={card.aged_info.risk} label={card.aged_info.label} note={card.aged_info.note} />}

      <Availability film={card} avail={card.availability} />

      <button className="linkbtn" onClick={() => setShowAttrs(s => !s)} aria-expanded={showAttrs}>
        Cómo es por dentro <Icon name="down" size={16} className={showAttrs ? 'flip' : ''} />
      </button>
      {showAttrs && (
        <div className="attrs">
          {Object.entries(ATTR_ES).map(([k, l]) => (
            <div key={k} className="attrs__row"><span>{l}</span>
              <div className="attrs__bar"><i style={{ width: `${Math.round((card.attrs[k] ?? 0.5) * 100)}%` }} /></div></div>
          ))}
        </div>
      )}

      <div className="actions">
        <button className="btn btn--cut" onClick={onCut}><Icon name="cut" size={20} /> Corten</button>
        <button className="btn btn--save" onClick={onSave}><Icon name="bookmark" size={20} /> Otro día</button>
        <button className="btn btn--go" onClick={onAccept}><Icon name="check" size={20} /> ¡Esta!</button>
      </div>
    </motion.article>
  )
}
