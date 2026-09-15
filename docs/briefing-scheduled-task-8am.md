# Scheduled Task — Briefing pre-market (8:00 AM)

Instrucciones para crear la tarea programada en Claude Desktop (Pro).
**Creala desde DENTRO de una conversación del Project que ya tiene
`briefing-premarket.md` pegado en sus instrucciones** -- así hereda el
marco analítico (Aleks, Context→Location→Confirmation, formato de
salida) sin que haga falta repetirlo acá.

**v3 (15-sep-2026)**: la v1 (navegar InsiderFinance) SÍ llegó a producir
un briefing real, con 3 bugs concretos que acá quedan corregidos:
1. El filtro 0DTE de InsiderFinance no son los botones de arriba (esos
   son porcentajes informativos, marcan 0.0%) -- es el desplegable "All
   expirations" → "Today (0DTE)".
2. La sesión de gex-terminal-8vb.pages.dev expiró a mitad de tarea
   ("tu sesión expiró") -- se reemplaza esa parte por un endpoint
   público propio que no necesita login (ver paso 3).
3. A veces devolvía DOS briefings en la misma respuesta (se
   autocorregía a mitad de camino y no descartaba el primer intento).

## Campos del formulario

- **Name**: `Briefing pre-market`
- **Frequency**: Daily, `08:00` -- **verificalo antes de confiar en el
  horario**: ya falló una vez (se disparó 23:32 hora Lima de un lunes en
  vez de las 8 AM). Probá primero con una hora rara (ej. 08:07) y fijate
  cuándo corre de verdad la primera vez, antes de dejarlo en el horario
  real.
- **Permissions**: `Manually approve` (dejalo así las primeras veces;
  pasalo a automático solo cuando el resultado sea bueno de forma
  consistente)
- **Require this computer**: activado (ON) -- necesita esto para poder
  usar Claude en Chrome y navegar de verdad
- Sin límite de créditos -- priorizá que el resultado sea bueno, no que
  sea barato.

## Instructions (pegar tal cual, o ajustar el ticker si hace falta)

```
Generá el briefing pre-market de hoy para QQQ y NDX.

1. Andá a https://www.insiderfinance.io/gamma-exposure/QQQ (público, sin
   login). El filtro 0DTE NO son los botones de arriba (esos son
   porcentajes informativos, no un selector -- van a marcar 0.0% y no
   hay que tocarlos). El selector real es un desplegable que dice "All
   expirations" -- abrilo y elegí "Today (0DTE)". Recién ahí anotá:
   Spot, Net GEX, Call GEX, Put GEX, Call Wall, Put Wall, Zero Gamma,
   ATM IV, Skew.
2. Andá a https://www.insiderfinance.io/gamma-exposure/NDX, mismo
   cambio de filtro a "Today (0DTE)", y anotá lo mismo para NDX.
3. Hacé GET a
   https://gex-terminal-api.onrender.com/market/premarket-briefing?symbol=QQQ
   (público, sin login -- puede tardar 30-60s la primera vez si el
   server estaba dormido, es normal). Usá SOLO la parte de VIX, VIX Term
   Structure, y calendario económico de la respuesta -- ignorá los
   niveles de gamma de ahí, para eso ya tenés InsiderFinance en los
   pasos 1-2, que es la fuente de mejor calidad.
4. Con todo eso, aplicá el marco de tus instrucciones de Project y
   escribime el briefing corto en el formato de siempre.

Reglas:
- Si algún paso falla (la página no carga, no encontrás un dato),
  decímelo explícitamente en vez de inventar un número.
- Dame UNA sola versión del briefing en tu respuesta. Si te
  autocorregís o cambiás de opinión a mitad de camino, corregí en
  silencio y mandame solo la versión final -- nunca dos briefings
  completos en la misma respuesta.
```

## Antes de confiarle el horario automático

Corré la tarea manualmente una vez ("Run now" si el panel lo tiene) y
revisá con calma:
- Que de verdad haya navegado a InsiderFinance (no haya alucinado los
  datos) y que haya elegido el desplegable "Today (0DTE)", no los
  botones de arriba.
- Que los números coincidan con lo que ves si abrís esas mismas páginas
  vos mismo en ese momento.
- Que sea UN solo briefing, no dos.
- Formato esperado: 2-4 oraciones por instrumento, sin tabla, sin
  secciones.
- Que de verdad se haya disparado a la hora esperada (ver nota de
  Frequency arriba).

Recién después de eso yo dejaría "Manually approve" cambiado a
automático, si es que ese trámite manual te sigue pareciendo necesario.
