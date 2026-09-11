/** Convierte una fecha+hora en hora de Nueva York (STORAGE_TZ del
 * backend) a segundos UTC -- para ejes de tiempo reales (Lightweight
 * Charts, o un eje 'date' de Plotly) en vez de strings "HH:MM" sueltos
 * en un eje de categorías. Usa el truco estándar de comparar cómo el
 * mismo instante se imprime en NY vs UTC para derivar el offset (maneja
 * EDT/EST solo con Intl, sin librería de fechas). */
export function nyWallClockToUtcSeconds(dateStr, timeStr) {
  const naive = new Date(`${dateStr}T${timeStr}:00`)
  const nyString = naive.toLocaleString('en-US', { timeZone: 'America/New_York' })
  const utcString = naive.toLocaleString('en-US', { timeZone: 'UTC' })
  const offsetMs = new Date(utcString).getTime() - new Date(nyString).getTime()
  return Math.floor((naive.getTime() + offsetMs) / 1000)
}

/** Igual que arriba, pero en milisegundos -- lo que espera un eje 'date'
 * de Plotly.js (Date object o ISO string). */
export function nyWallClockToDate(dateStr, timeStr) {
  return new Date(nyWallClockToUtcSeconds(dateStr, timeStr) * 1000)
}
