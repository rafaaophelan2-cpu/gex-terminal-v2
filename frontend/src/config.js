// Backend desplegado en Render (ver docs/plan) -- por defecto el frontend
// de desarrollo local apunta directo a producción, así no hace falta
// correr el backend en la propia máquina para probar la UI. Se puede
// sobreescribir con una variable de entorno de Vite (.env.local:
// VITE_API_BASE=http://localhost:8000) si se quiere probar contra un
// backend corriendo en local.
const DEFAULT_API_BASE = 'https://gex-terminal-api.onrender.com'

export const API_BASE = import.meta.env.VITE_API_BASE || DEFAULT_API_BASE
export const WS_BASE = API_BASE.replace(/^http/, 'ws')
