import { useState } from 'react'
import { api } from './api'
import { FilmDrawer } from './components/FilmDrawer'
import { Icon, type IconName } from './components/Icon'
import { Toasts } from './components/Toasts'
import { go, useRoute, type Route } from './router'
import { useApp } from './store'
import Library from './pages/Library'
import Login from './pages/Login'
import Onboarding from './pages/Onboarding'
import Paths from './pages/Paths'
import Settings from './pages/Settings'
import Taste from './pages/Taste'
import Tonight from './pages/Tonight'

const NAV: { route: Route; label: string; icon: IconName }[] = [
  { route: 'noche', label: 'Esta noche', icon: 'moon' },
  { route: 'biblioteca', label: 'Biblioteca', icon: 'library' },
  { route: 'rutas', label: 'Rutas', icon: 'route' },
  { route: 'gusto', label: 'Mi gusto', icon: 'heart' },
  { route: 'ajustes', label: 'Ajustes', icon: 'gear' },
]

function Brand() {
  return (
    <a className="brand" href="#/noche" aria-label="Claqueta, inicio">
      <Icon name="clap" size={22} />
      <span>Claqueta</span>
    </a>
  )
}

function Nav({ route, className }: { route: Route; className: string }) {
  return (
    <nav className={className} aria-label="Secciones">
      {NAV.map(n => (
        <a key={n.route} href={`#/${n.route}`} aria-current={route === n.route ? 'page' : undefined}
           className={route === n.route ? 'is-on' : ''}>
          <Icon name={n.icon} size={21} />
          <span>{n.label}</span>
        </a>
      ))}
    </nav>
  )
}

export default function App() {
  const { boot, bootError, refreshBoot, auth, setAuthOk } = useApp()
  const { route } = useRoute()
  const [loadingDemo, setLoadingDemo] = useState(false)

  if (auth === 'loading') return <div className="splash"><Icon name="clap" size={44} /></div>
  if (auth === 'login') return <><Login onDone={setAuthOk} /><Toasts /></>

  if (!boot) {
    return (
      <div className="splash">
        <Icon name="clap" size={44} />
        {bootError ? (
          <>
            <h1>No consigo hablar con Claqueta</h1>
            <p>{bootError}</p>
            <button className="btn btn--go" onClick={() => void refreshBoot()}>Reintentar</button>
          </>
        ) : <p>Preparando la sala…</p>}
      </div>
    )
  }

  const startDemo = async () => {
    setLoadingDemo(true)
    try { await api.post('/api/demo/load'); await refreshBoot() } finally { setLoadingDemo(false) }
  }

  return (
    <div className="app">
      <header className="top">
        <Brand />
        <Nav route={route} className="nav" />
      </header>
      <main id="main" className="page">
        <div hidden={route !== 'noche'}><Tonight boot={boot} /></div>
        {route === 'biblioteca' && <Library />}
        {route === 'rutas' && <Paths />}
        {route === 'gusto' && <Taste />}
        {route === 'ajustes' && <Settings boot={boot} onChanged={refreshBoot} />}
        {route === 'empezar' && <Onboarding boot={boot} onDemo={startDemo} demoBusy={loadingDemo} onDone={() => { void refreshBoot(); go('noche') }} />}
      </main>
      <Nav route={route} className="dock" />
      <FilmDrawer />
      <Toasts />
    </div>
  )
}
