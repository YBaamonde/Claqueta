import { AnimatePresence, motion, useDragControls } from 'framer-motion'
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'

/** Hoja inferior en móvil, diálogo centrado en escritorio. Se cierra con Esc, clic fuera o la X. */
export function Sheet({ open, onClose, title, children, wide = false, label }: {
  open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode; wide?: boolean; label?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const controls = useDragControls()
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', onKey)
    document.body.classList.add('no-scroll')
    const t = window.setTimeout(() => ref.current?.focus(), 30)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.classList.remove('no-scroll')
      window.clearTimeout(t)
      prev?.focus?.()
    }
  }, [open, onClose])

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="sheet-root" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    transition={{ duration: 0.18 }}>
          <div className="sheet-scrim" onClick={onClose} />
          <motion.div
            ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label ?? (typeof title === 'string' ? title : 'Diálogo')}
            className={`sheet ${wide ? 'sheet--wide' : ''}`}
            initial={{ y: 40, opacity: 0.6 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 40, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 38 }}
            drag="y" dragControls={controls} dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={(_, i) => { if (i.offset.y > 110 || i.velocity.y > 600) onClose() }}
            dragListener={false}
          >
            <div className="sheet__grip" aria-hidden="true" onPointerDown={e => controls.start(e)} />
            <header className="sheet__head">
              {title && <h2>{title}</h2>}
              <button className="icon-btn" onClick={onClose} aria-label="Cerrar"><Icon name="close" /></button>
            </header>
            <div className="sheet__body">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
