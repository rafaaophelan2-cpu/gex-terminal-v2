import { nyWallClockToUtcSeconds } from '../utils/time.js'

/** Pestaña News: calendario económico (izquierda) + feed de noticias
 * (derecha), estilo FinancialJuice -- HTML/CSS plano, no Plotly (mismo
 * criterio que signalsPanel.js). Los datos ya vienen filtrados/curados
 * del backend (ver domain/news_filter.py) -- acá solo se renderiza. */

function escapeHtml(value) {
  const div = document.createElement('div')
  div.textContent = value == null ? '' : String(value)
  return div.innerHTML
}

/** "Ahora" en hora de Nueva York, codificado con el mismo truco que
 * nyWallClockToUtcSeconds (dígitos de NY incrustados como si fueran UTC)
 * -- para poder comparar directo contra los timestamps de los eventos
 * del calendario (que vienen en "YYYY-MM-DD"/"HH:MM" de NY), sin
 * pelearse con el offset real NY<->huso horario del navegador. */
function nyNowFakeUtcSeconds() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).formatToParts(new Date())
  const get = (type) => parts.find((p) => p.type === type)?.value
  return nyWallClockToUtcSeconds(`${get('year')}-${get('month')}-${get('day')}`, `${get('hour')}:${get('minute')}`)
}

function formatDayHeader(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.toLocaleDateString('es-PE', { day: 'numeric', month: 'long', timeZone: 'UTC' })
}

function formatCalendarValues(ev) {
  const parts = []
  if (ev.actual !== null && ev.actual !== undefined && ev.actual !== '') parts.push(`Real ${escapeHtml(ev.actual)}`)
  if (ev.forecast !== null && ev.forecast !== undefined && ev.forecast !== '') parts.push(`Pron. ${escapeHtml(ev.forecast)}`)
  if (ev.previous !== null && ev.previous !== undefined && ev.previous !== '') parts.push(`Ant. ${escapeHtml(ev.previous)}`)
  return parts.join(' · ')
}

/** 'events': lista ya ordenada por fecha/hora (ver GET /market/economic-calendar,
 * domain -> integrations/finnhub_client.py::fetch_economic_calendar). */
export function renderNewsCalendar(container, events) {
  if (!events || events.length === 0) {
    container.innerHTML = '<p class="news-placeholder">Sin eventos económicos de impacto medio/alto en este rango.</p>'
    return
  }

  const nowSec = nyNowFakeUtcSeconds()
  // El "próximo" evento a resaltar: el de menor delta hacia el futuro
  // (delta >= 0). Si TODOS los eventos del rango ya pasaron, no se
  // resalta ninguno -- no tiene sentido marcar "el próximo" sobre algo
  // que ya ocurrió.
  let upcomingIndex = -1
  let bestDelta = Infinity
  events.forEach((ev, i) => {
    const sec = nyWallClockToUtcSeconds(ev.date, ev.time || '00:00')
    const delta = sec - nowSec
    if (delta >= 0 && delta < bestDelta) {
      bestDelta = delta
      upcomingIndex = i
    }
  })

  let html = ''
  let lastDate = null
  events.forEach((ev, i) => {
    if (ev.date !== lastDate) {
      html += `<div class="news-calendar-day-header">${escapeHtml(formatDayHeader(ev.date))}</div>`
      lastDate = ev.date
    }
    const values = formatCalendarValues(ev)
    html += `
      <div class="news-calendar-row${i === upcomingIndex ? ' upcoming' : ''}">
        <span class="news-calendar-row-time">${escapeHtml(ev.time || '--:--')}</span>
        <span class="news-calendar-row-body">
          <span class="news-calendar-row-event">${escapeHtml(ev.event)}</span>
          ${values ? `<span class="news-calendar-row-values">${values}</span>` : ''}
        </span>
      </div>
    `
  })

  container.innerHTML = html
}

function formatArticleTime(epochSeconds) {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  return date.toLocaleString('es-PE', {
    timeZone: 'America/Lima', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

/** 'articles': ya filtrados a relevancia QQQ/NQ y con 'important' seteado
 * del lado del backend (ver GET /market/news, domain/news_filter.py) --
 * ver el disclaimer ahí, es una heurística por palabras clave, no un
 * clasificador real (la fuente gratis no tagea noticias por ticker). */
export function renderNewsFeed(container, articles) {
  if (!articles || articles.length === 0) {
    container.innerHTML = '<p class="news-placeholder">Sin noticias relevantes para QQQ/NQ en este momento.</p>'
    return
  }

  container.innerHTML = articles.map((a) => {
    const tag = a.url ? 'a' : 'div'
    const hrefAttrs = a.url ? `href="${escapeHtml(a.url)}" target="_blank" rel="noopener noreferrer"` : ''
    const meta = [formatArticleTime(a.datetime), a.source].filter(Boolean).map(escapeHtml).join(' · ')
    return `
      <${tag} class="news-feed-item${a.important ? ' important' : ''}" ${hrefAttrs}>
        <span class="news-feed-item-headline">${escapeHtml(a.headline)}</span>
        <span class="news-feed-item-meta">${meta}</span>
      </${tag}>
    `
  }).join('')
}
