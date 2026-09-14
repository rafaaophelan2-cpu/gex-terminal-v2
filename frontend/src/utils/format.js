/** Abrevia un monto en USD a K/M/B (ej. 9000000 -> "+$9.00M") -- usado en
 * la barra de métricas, DATA y el GRID de gamma por expiración. */
export function fmtMoney(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '--'
  const abs = Math.abs(val)
  // '> 0' (no '>= 0') -- con '>= 0', un valor de -0 (real, ej. una suma
  // de GEX que cancela exacto) rendereaba como "+$0.0": -0 >= 0 es true
  // en JS, pero (-0).toFixed(n) no imprime el signo negativo por su
  // cuenta, así que el '+' quedaba puesto sobre un cero que en realidad
  // venía del lado negativo. Un valor negativo real sigue mostrando su
  // propio '-' vía toFixed() más abajo, sin cambios.
  const sign = val > 0 ? '+' : ''
  if (abs >= 1e9) return `${sign}$${(val / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(val / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(val / 1e3).toFixed(1)}K`
  return `${sign}$${val.toFixed(1)}`
}
