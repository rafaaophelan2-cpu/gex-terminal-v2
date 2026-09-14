// Cloudflare Pages Function -- proxea el feed publico de ForexFactory
// para el calendario economico. El backend en Render lo llama a ESTE
// endpoint en vez de a ForexFactory directo: el IP de salida de Render
// (compartido con otros clientes del free/starter tier) quedo bloqueado
// por ForexFactory durante horas seguidas (confirmado en vivo -- el
// mismo fetch funciona al instante desde cualquier otra IP), mientras
// que la red de Cloudflare (la misma que ya sirve este frontend) no
// tiene ese problema. Sin esto, /market/economic-calendar se queda
// vacio indefinidamente cada vez que el IP de Render vuelve a quedar
// baneado, sin manera de recuperarse solo.
export async function onRequestGet() {
  const upstream = await fetch('https://nfs.faireconomy.media/ff_calendar_thisweek.json', {
    headers: { 'User-Agent': 'Mozilla/5.0' },
  })
  const body = await upstream.text()
  return new Response(body, {
    status: upstream.status,
    headers: { 'content-type': 'application/json' },
  })
}
