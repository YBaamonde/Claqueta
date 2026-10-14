import { useId, useState } from 'react'

/** Valoración de 0,5 a 5 con medias estrellas (como Letterboxd). */
export function Stars({ value, onChange, size = 26, readOnly = false }: {
  value: number | null | undefined; onChange?: (v: number) => void; size?: number; readOnly?: boolean
}) {
  const [hover, setHover] = useState<number | null>(null)
  const uid = useId().replace(/:/g, '')
  const shown = hover ?? value ?? 0
  const pick = (e: React.MouseEvent<HTMLButtonElement>, i: number) => {
    const half = e.clientX - e.currentTarget.getBoundingClientRect().left < e.currentTarget.offsetWidth / 2
    return i - (half ? 0.5 : 0)
  }
  return (
    <div className="stars" role={readOnly ? 'img' : 'group'} aria-label={value ? `${value} de 5 estrellas` : 'Sin valorar'}
         onMouseLeave={() => setHover(null)} style={{ ['--star' as string]: `${size}px` }}>
      {[1, 2, 3, 4, 5].map(i => {
        const fill = Math.max(0, Math.min(1, shown - (i - 1)))
        return (
          <button key={i} type="button" disabled={readOnly} className="stars__s" aria-label={`${i} estrellas`}
                  onMouseMove={e => !readOnly && setHover(pick(e, i))}
                  onClick={e => onChange?.(pick(e, i))}>
            <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
              <defs><clipPath id={`c${uid}${i}`}><rect x="0" y="0" width={24 * fill} height="24" /></clipPath></defs>
              <path d="m12 2.500 2.900 6 6.600.9-4.800 4.600 1.200 6.500L12 17.400 6.100 20.500l1.200-6.500L2.500 9.400l6.600-.9Z"
                    fill="none" stroke="currentColor" strokeWidth="1.500" strokeLinejoin="round" opacity="0.45" />
              <path d="m12 2.500 2.900 6 6.600.9-4.800 4.600 1.200 6.500L12 17.400 6.100 20.500l1.200-6.500L2.500 9.400l6.600-.9Z"
                    fill="currentColor" clipPath={`url(#c${uid}${i})`} />
            </svg>
          </button>
        )
      })}
    </div>
  )
}
