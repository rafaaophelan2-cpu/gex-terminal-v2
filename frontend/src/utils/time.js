/** Convierte una fecha+hora en hora de Nueva York (STORAGE_TZ del
 * backend) a un timestamp para ejes de tiempo reales (Lightweight
 * Charts, o un eje 'date' de Plotly) en vez de strings "HH:MM" sueltos
 * en un eje de categorías.
 *
 * A propósito NO calcula el offset real NY->UTC: tanto Plotly como
 * Lightweight Charts terminan mostrando las etiquetas de los ejes en UTC
 * (confirmado en vivo: convertir con el offset real de NY hacía que
 * "14:00 NY" se mostrara en pantalla como "18:00"). En vez de pelear
 * contra eso, se incrustan los números de reloj de pared de NY
 * directamente como si fueran UTC -- así lo que la librería renderiza en
 * UTC termina mostrando exactamente esos mismos números. El timestamp
 * resultante no representa el instante real en UTC, pero el orden y el
 * espaciado relativo entre puntos sí son correctos (que es todo lo que
 * necesita un eje de tiempo), y la etiqueta en pantalla es la correcta. */
export function nyWallClockToUtcSeconds(dateStr, timeStr) {
  const [year, month, day] = dateStr.split('-').map(Number)
  const [hour, minute] = timeStr.split(':').map(Number)
  return Math.floor(Date.UTC(year, month - 1, day, hour, minute) / 1000)
}

export function nyWallClockToDate(dateStr, timeStr) {
  return new Date(nyWallClockToUtcSeconds(dateStr, timeStr) * 1000)
}

/** Para ejes 'date' de Plotly específicamente: pasarle un objeto Date de
 * JS (nyWallClockToDate) terminaba reinterpretándose en la zona horaria
 * LOCAL del navegador al renderizar, no en UTC -- confirmado en vivo con
 * un usuario en Lima (UTC-5): "11:00 NY" aparecía en pantalla como
 * "06:00". Un string de fecha/hora SIN timezone, en cambio, Plotly lo
 * trata como literal (no lo reinterpreta con el offset del navegador) --
 * lo que se pinta en el eje son estos mismos dígitos sin importar en qué
 * zona horaria esté quien mira la web. Lightweight Charts (NET DRIFT) no
 * tiene este problema -- usa nyWallClockToUtcSeconds tal cual, un número
 * de segundos UTC sin ambigüedad posible. */
export function nyWallClockToPlotlyString(dateStr, timeStr) {
  return `${dateStr} ${timeStr}:00`
}
