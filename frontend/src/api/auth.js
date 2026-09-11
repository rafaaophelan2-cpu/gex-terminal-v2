import { API_BASE } from '../config.js'
import { apiFetch, clearToken, getToken, setToken } from './http.js'

export async function login(username, password) {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    throw new Error(data.detail || `Error ${resp.status}`)
  }
  if (data.token) setToken(data.token)
  return data
}

export async function logout() {
  try {
    await apiFetch('/auth/logout', { method: 'POST' })
  } catch {
    // Si ya no hay sesión válida (401 -> SessionExpiredError), no hay
    // nada que cerrar en el servidor -- igual se limpia el token local.
  }
  clearToken()
}

export async function me() {
  // Sin token guardado, ni vale la pena pedirle al backend -- evita un
  // 401 "esperado" en cada carga inicial de alguien que no inició sesión.
  if (!getToken()) return null
  try {
    const resp = await apiFetch('/auth/me')
    if (!resp.ok) return null
    return resp.json()
  } catch {
    return null
  }
}
