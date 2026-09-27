/** Abrevia un monto en USD a K/M/B (ej. 9000000 -> "+$9.00M") -- usado en
 * la barra de métricas, DATA y el GRID de gamma por expiración. */
export function fmtMoney(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '--'
  const abs = Math.abs(val)
  let body
  if (abs >= 1e9) body = `${(abs / 1e9).toFixed(2)}B`
  else if (abs >= 1e6) body = `${(abs / 1e6).toFixed(2)}M`
  else if (abs >= 1e3) body = `${(abs / 1e3).toFixed(1)}K`
  else body = abs.toFixed(1)
  // El signo va ANTES del '$' ("-$448.22M", no "$-448.22M" como salía
  // antes al dejar que toFixed() pusiera el '-' dentro del número). Un
  // valor que redondea a cero no lleva signo: ni "+$0.0" por un -0 real
  // (una suma que cancela exacto) ni "-$0.0" por un -0.01.
  const isZero = /^0(\.0+)?[BMK]?$/.test(body)
  const sign = isZero ? '' : val > 0 ? '+' : '-'
  return `${sign}$${body}`
}

/** Para las griegas que el backend ya manda en MILLONES de USD (DEX, CHEX,
 * Vanna; ver UNITS en domain/briefing_data.py): mismo formato que
 * fmtMoney, así todas las tarjetas de Griegas se leen igual ("+$833.29M"),
 * en vez de mezclar "833.29M" sin $ con "$-2.63M". */
export function fmtMoneyM(millions) {
  if (millions === null || millions === undefined || Number.isNaN(millions)) return '--'
  return fmtMoney(millions * 1e6)
}
