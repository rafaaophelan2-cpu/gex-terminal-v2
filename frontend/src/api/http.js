import { API_BASE } from '../config.js'

export class SessionExpiredError extends Error {
  constructor() {
    super('Tu sesión expiró -- inicia sesión de nuevo.')
    this.name = 'SessionExpiredError'
  }
}

/** Wrapper compartido por todas las llamadas a la API -- centraliza el
 * cookie de sesión y, sobre todo, la detección de 401: antes cada
 * módulo (rest.js, chat.js) hacía su propio fetch suelto, así que un
 * 401 (sesión expirada) se mostraba como un error críptico cualquiera
 * en el lugar donde pasara a ocurrir (ej. "No autenticado" en el status
 * del GRID) en vez de mandar al usuario de vuelta al login. Con esto,
 * cualquier 401 dispara un evento global una sola vez y main.js decide
 * qué hacer (mostrar login + aviso), sin que cada caller tenga que
 * saber de esto. */
export async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...options })
  if (resp.status === 401) {
    window.dispatchEvent(new CustomEvent('session-expired'))
    throw new SessionExpiredError()
  }
  return resp
}
