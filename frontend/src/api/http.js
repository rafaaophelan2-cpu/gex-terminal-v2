import { API_BASE } from '../config.js'

const TOKEN_KEY = 'gex_token'

export class SessionExpiredError extends Error {
  constructor() {
    super('Tu sesión expiró -- inicia sesión de nuevo.')
    this.name = 'SessionExpiredError'
  }
}

/** El token vive en localStorage (no en una cookie) a propósito: el
 * backend (onrender.com) y el frontend (pages.dev) están en dominios
 * distintos, y una cookie ahí es cross-site -- varios navegadores
 * bloquean eso por defecto como protección anti-tracking (Safari con
 * "Prevent Cross-Site Tracking" desde iOS/Safari 13, Firefox en modo
 * Enhanced Tracking Protection estricto). Con eso activado, el login
 * respondía 200 OK pero el navegador descartaba la cookie en silencio,
 * y la siguiente llamada a la API caía en 401 -- el usuario veía "tu
 * sesión expiró" segundos después de haber iniciado sesión bien.
 * localStorage es same-origin al propio frontend, no le afecta nada de
 * esto en ningún navegador. */
export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // localStorage puede fallar (modo privado estricto en algún
    // navegador, cuota llena) -- sin él, la sesión no persiste entre
    // recargas, pero no debe romper el login en curso.
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ver comentario en setToken.
  }
}

/** Wrapper compartido por todas las llamadas a la API -- adjunta el
 * token como 'Authorization: Bearer' y centraliza la detección de 401:
 * antes cada módulo (rest.js, chat.js) hacía su propio fetch suelto, así
 * que un 401 se mostraba como un error críptico donde pasara a ocurrir
 * en vez de mandar al usuario de vuelta al login. Con esto, cualquier
 * 401 dispara un evento global una sola vez y main.js decide qué hacer
 * (mostrar login + aviso), sin que cada caller tenga que saber de esto. */
export async function apiFetch(path, options = {}) {
  const token = getToken()
  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (resp.status === 401) {
    window.dispatchEvent(new CustomEvent('session-expired'))
    throw new SessionExpiredError()
  }
  return resp
}
