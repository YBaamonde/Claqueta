export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message)
  }
}

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

async function request<T>(method: string, url: string, body?: unknown, form?: FormData): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: {} }
  if (form) init.body = form
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError('No hay conexión con el servidor de Claqueta', 0, 'network')
  }
  if (res.status === 401) onUnauthorized?.()
  if (!res.ok) {
    let detail = `Error ${res.status}`
    let code: string | undefined
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : detail
      code = j.code
    } catch { /* cuerpo no JSON */ }
    throw new ApiError(detail, res.status, code)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  del: <T>(url: string) => request<T>('DELETE', url),
  upload: <T>(url: string, form: FormData) => request<T>('POST', url, undefined, form),
}

export const qs = (params: Record<string, string | number | undefined | null>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v))
  const s = u.toString()
  return s ? `?${s}` : ''
}
