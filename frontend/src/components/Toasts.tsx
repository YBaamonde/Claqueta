import { AnimatePresence, motion } from 'framer-motion'
import { useApp } from '../store'
import { Icon } from './Icon'

export function Toasts() {
  const { toasts, dismissToast } = useApp()
  return (
    <div className="toasts" role="status" aria-live="polite">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div key={t.id} layout className={`toast toast--${t.tone ?? 'ok'}`}
                      initial={{ y: 24, opacity: 0, scale: 0.96 }} animate={{ y: 0, opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, y: 10 }} transition={{ type: 'spring', stiffness: 500, damping: 36 }}>
            <span>{t.text}</span>
            {t.action && (
              <button className="toast__action" onClick={() => { t.action!.run(); dismissToast(t.id) }}>
                <Icon name="undo" size={16} /> {t.action.label}
              </button>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
