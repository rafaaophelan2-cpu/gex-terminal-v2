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
//
// CACHE PROPIO (agregado 14-sep-2026): este proxy NO tenia cache -- cada
// llamada disparaba un fetch NUEVO a ForexFactory, sin importar quien la
// origine. ForexFactory limita a ~1 req/hora por IP; el backend ya cachea
// 3600s de su lado (ver forexfactory_client.py), pero ESE cache vive en
// memoria de proceso y se resetea en cada redeploy de Render -- con
// varios redeploys seguidos (comun en esta sesion) mas cualquier prueba
// manual del proxy (curl/PowerShell), el numero real de fetches a
// ForexFactory por hora superaba su limite igual, y volvia a gatillar el
// mismo 429 una y otra vez (confirmado en logs de Render, 14-sep-2026,
// 21:28: 429 en /ff-calendar pese a que el backend recien se habia
// redesplegado con cache vacio). Cachear ACA, en el unico punto de la
// red de Cloudflare por el que pasan TODOS los llamadores (backend en
// cualquier instancia/redeploy, o alguien probando el proxy a mano),
// garantiza como maximo 1 fetch real a ForexFactory por hora sin
// importar cuantas veces/desde donde se llame a este proxy.
const CACHE_TTL_SECONDS = 3600

export async function onRequestGet(context) {
  const cache = caches.default
  const cacheKey = new Request('https://ff-calendar-proxy.internal/cache-key')

  const cached = await cache.match(cacheKey)
  if (cached) {
    return cached
  }

  const upstream = await fetch('https://nfs.faireconomy.media/ff_calendar_thisweek.json', {
    headers: { 'User-Agent': 'Mozilla/5.0' },
  })
  const body = await upstream.text()
  const response = new Response(body, {
    status: upstream.status,
    headers: {
      'content-type': 'application/json',
      'cache-control': `public, max-age=${CACHE_TTL_SECONDS}`,
    },
  })

  // Solo se cachea una respuesta exitosa -- un 429/error NO se guarda,
  // para no quedar sirviendo ese error durante una hora entera si
  // ForexFactory se recupera antes.
  if (upstream.ok) {
    context.waitUntil(cache.put(cacheKey, response.clone()))
  }

  return response
}
