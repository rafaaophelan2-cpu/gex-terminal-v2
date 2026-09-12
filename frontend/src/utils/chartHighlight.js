/** Reborde blanco para la barra positiva más fuerte y la negativa más
 * fuerte de un set de valores (1 de cada lado) -- Plotly acepta arrays por
 * punto en marker.line.color/width, así que alcanza con devolver un color
 * y un ancho transparentes en todas las barras salvo esas dos. Usado en
 * GEX INFO, GREEKS y BACKGAMMA para que el nivel dominante de cada signo
 * salte a la vista de un vistazo, sin tener que leer los números. */
export function strongestOutline(values) {
  const colors = new Array(values.length).fill('rgba(0,0,0,0)')
  const widths = new Array(values.length).fill(0)

  let maxPosIdx = -1
  let maxPosVal = 0
  let maxNegIdx = -1
  let maxNegVal = 0

  values.forEach((v, i) => {
    if (v > maxPosVal) {
      maxPosVal = v
      maxPosIdx = i
    }
    if (v < maxNegVal) {
      maxNegVal = v
      maxNegIdx = i
    }
  })

  if (maxPosIdx !== -1) {
    colors[maxPosIdx] = '#FFFFFF'
    widths[maxPosIdx] = 2.5
  }
  if (maxNegIdx !== -1) {
    colors[maxNegIdx] = '#FFFFFF'
    widths[maxNegIdx] = 2.5
  }

  return { colors, widths }
}
