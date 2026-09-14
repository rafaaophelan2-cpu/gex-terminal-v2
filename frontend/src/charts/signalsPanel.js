const SIGNAL_ICONS = {
  volatility_dampened: '⚠️',
  volatility_increased: '⚠️',
  volatility_increased_below: '⚠️',
  magnet: '🧲',
  resistance: '🛡️',
}

const STATE_CLASSES = {
  UNLIKELY: 'state-unlikely',
  POSSIBLE: 'state-possible',
  LIKELY: 'state-likely',
  IMMINENT: 'state-imminent',
}

function badgeClass(badge) {
  return badge === 'STRONG' ? 'badge-strong' : 'badge-moderate'
}

function stateClass(state) {
  return STATE_CLASSES[state] || 'state-unlikely'
}

function renderSignalCard(signal) {
  const pct = signal.pct_from_spot ?? 0
  const sign = pct >= 0 ? '+' : ''
  const pctClass = pct > 0 ? 'val-positive' : pct < 0 ? 'val-negative' : ''
  return `
    <div class="signal-card">
      <div class="signal-card-header">
        <span class="signal-card-title">${SIGNAL_ICONS[signal.type] || '•'} ${signal.title}</span>
        <span class="badge ${badgeClass(signal.badge)}">${signal.badge}</span>
      </div>
      <p class="signal-card-desc">${signal.description}</p>
      <div class="signal-card-footer">
        <span>@ $${signal.level.toFixed(2)}</span>
        <span class="${pctClass}">${sign}${pct.toFixed(2)}%</span>
      </div>
    </div>
  `
}

function renderFactorRow(factor) {
  // Math.min(..., 100) -- si score > max (no debería pasar, pero sin
  // resguardo propio acá del lado del backend) la barra se dibujaba más
  // ancha que su propio track en vez de tope en 100%.
  const pct = factor.max > 0 ? Math.min((factor.score / factor.max) * 100, 100) : 0
  const maxed = factor.max > 0 && factor.score >= factor.max
  return `
    <div class="factor-row">
      <div class="factor-row-top">
        <span>${factor.label}</span>
        <span>${factor.score}/${factor.max}</span>
      </div>
      <div class="factor-bar-track">
        <div class="factor-bar-fill${maxed ? ' factor-bar-full' : ''}" style="width:${pct}%"></div>
      </div>
    </div>
  `
}

/** Pestaña GEX INFO: panel de Señales + Gamma Squeeze Screener (ver
 * domain/signals.py en el backend) -- HTML/CSS plano, no Plotly, porque
 * es una lista de tarjetas/barras de progreso, no un gráfico. 'data' es
 * el objeto {signals, squeeze} que llega en data.signals del tick/
 * chain_full del WS. */
export function renderSignalsPanel(listEl, squeezeEl, biasBadgeEl, data) {
  if (!data) return
  const { signals, squeeze } = data

  if (!signals || signals.length === 0) {
    listEl.innerHTML = '<p class="signals-placeholder">Sin señales disponibles todavía.</p>'
  } else {
    listEl.innerHTML = signals.map(renderSignalCard).join('')
  }

  if (!squeeze || squeeze.probability === null || squeeze.probability === undefined) {
    biasBadgeEl.textContent = ''
    biasBadgeEl.className = 'badge badge-bias'
    squeezeEl.innerHTML = '<p class="signals-placeholder">Sin datos suficientes todavía.</p>'
    return
  }

  biasBadgeEl.textContent = squeeze.bias === 'BULLISH' ? 'BULLISH BIAS' : 'NEUTRAL BIAS'
  biasBadgeEl.className = `badge badge-bias ${squeeze.bias === 'BULLISH' ? 'badge-bullish' : 'badge-neutral'}`

  const kl = squeeze.key_levels || {}
  const cwPct = kl.call_wall_pct ?? 0
  const cwSign = cwPct >= 0 ? '+' : ''
  // Antes hardcodeado a 'val-positive' sin importar el signo -- un Call
  // Wall por DEBAJO del precio actual (cwPct negativo, ej. tras una
  // ruptura fuerte) se mostraba en verde igual, mismo criterio que
  // pctClass en renderSignalCard más arriba.
  const cwClass = cwPct > 0 ? 'val-positive' : cwPct < 0 ? 'val-negative' : ''

  squeezeEl.innerHTML = `
    <div class="squeeze-direction-row">
      <span class="squeeze-direction">⚡ ${squeeze.direction}</span>
      <span class="badge ${stateClass(squeeze.state)}">${squeeze.state}</span>
    </div>
    <div class="squeeze-score-row">
      <span class="squeeze-score-label">PROBABILITY SCORE</span>
      <span class="squeeze-score-value ${stateClass(squeeze.state)}">${squeeze.probability}<span class="squeeze-score-max">/100</span></span>
    </div>
    <div class="squeeze-bar-track">
      <div class="squeeze-bar-fill ${stateClass(squeeze.state)}" style="width:${squeeze.probability}%"></div>
    </div>
    <div class="squeeze-scale-labels">
      <span>Unlikely</span><span>Possible</span><span>Likely</span><span>Imminent</span>
    </div>
    <p class="factor-breakdown-label">FACTOR BREAKDOWN</p>
    <div class="factor-list">
      ${squeeze.factors.map(renderFactorRow).join('')}
    </div>
    <div class="key-levels-box">
      <p class="key-levels-title">KEY LEVELS</p>
      <div class="key-levels-row"><span>Current Price</span><span>$${(kl.current_price ?? 0).toFixed(2)}</span></div>
      <div class="key-levels-row"><span>Call Wall</span><span class="${cwClass}">(${cwSign}${cwPct.toFixed(2)}%) $${(kl.call_wall ?? 0).toFixed(2)}</span></div>
      <div class="key-levels-row"><span>Trigger Level</span><span class="key-levels-trigger">$${(kl.trigger_level ?? 0).toFixed(2)}</span></div>
    </div>
  `
}
