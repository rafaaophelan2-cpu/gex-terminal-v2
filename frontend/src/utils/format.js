/** Abrevia un monto en USD a K/M/B (ej. 9000000 -> "+$9.00M") -- usado en
 * la barra de métricas, DATA y el GRID de gamma por expiración. */
export function fmtMoney(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '--'
  const abs = Math.abs(val)
  const sign = val >= 0 ? '+' : ''
  if (abs >= 1e9) return `${sign}$${(val / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(val / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(val / 1e3).toFixed(1)}K`
  return `${sign}$${val.toFixed(1)}`
}
