import '@fontsource-variable/bricolage-grotesque/wdth.css'
import '@fontsource-variable/newsreader/wght.css'
import '@fontsource-variable/newsreader/wght-italic.css'
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AppProvider } from './store'
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import './styles/tonight.css'
import './styles/pages.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </React.StrictMode>,
)
