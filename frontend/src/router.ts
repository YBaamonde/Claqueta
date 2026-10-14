import { useEffect, useState } from 'react'

export type Route = 'noche' | 'biblioteca' | 'rutas' | 'gusto' | 'ajustes' | 'empezar'
const ROUTES: Route[] = ['noche', 'biblioteca', 'rutas', 'gusto', 'ajustes', 'empezar']

export function parseHash(hash: string): { route: Route; param: string } {
  const [seg, param = ''] = hash.replace(/^#\/?/, '').split('/')
  const route = (ROUTES as string[]).includes(seg) ? (seg as Route) : 'noche'
  return { route, param }
}

export function go(route: Route, param = '') {
  window.location.hash = `#/${route}${param ? '/' + param : ''}`
}

export function useRoute() {
  const [state, setState] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const on = () => setState(parseHash(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return state
}
