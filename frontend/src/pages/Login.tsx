import { useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'

export default function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try { await api.post('/api/auth/login', { password: pw }); onDone() }
    catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="splash">
      <Icon name="clap" size={44} />
      <h1>Claqueta</h1>
      <form className="login" onSubmit={submit}>
        <label htmlFor="pw">Contraseña de acceso</label>
        <input id="pw" type="password" autoFocus autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} />
        {err && <p className="form-error" role="alert">{err}</p>}
        <button className="btn btn--go btn--block" disabled={busy || !pw}>{busy ? 'Entrando…' : 'Entrar'}</button>
      </form>
    </div>
  )
}
