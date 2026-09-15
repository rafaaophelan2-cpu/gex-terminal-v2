# Scheduled Task — Briefing pre-market (8:00 AM)

Instrucciones para crear la tarea programada en Claude Desktop (Pro).
**Importante**: creala desde DENTRO de una conversación del Project que
ya tiene `briefing-project-instructions.md` en sus instrucciones -- así
la tarea hereda ese marco sin que haga falta repetirlo acá. Si por algún
motivo la creás fuera del Project, pegale el contenido completo de
`briefing-project-instructions.md` antes de estos pasos.

**v2 (15-sep-2026)**: se simplificó a propósito. La v1 navegaba
InsiderFinance + Cboe + la pestaña News de gex-terminal-v2 -- generó una
sesión que expiró a mitad de tarea, un filtro de 0DTE mal identificado,
y un consumo de créditos alto (browsing con visión en 3 sitios). Ahora
todo sale de un solo endpoint propio (`/market/premarket-briefing`,
público, sin login) -- ver la sección "Fuente de datos" de
`briefing-project-instructions.md`.

## Campos del formulario

- **Name**: `Briefing pre-market`
- **Frequency**: Daily, `08:00` -- **ojo, esto ya falló una vez**: la
  tarea se disparó a las 23:32 hora de Lima de un lunes en vez de las
  8 AM. Confirmá explícitamente en qué zona horaria interpreta Desktop
  ese campo (probá poniendo una hora rara, tipo 08:07, y mirá cuándo
  corre de verdad la primera vez, antes de confiarle el horario real).
- **Permissions**: `Manually approve` (dejalo así las primeras veces;
  cambialo a auto-approve solo cuando confirmes que el resultado es
  bueno de forma consistente)
- **Require this computer**: dejalo activado (ON) por ahora -- es la
  configuración que ya sabemos que funciona. Como el nuevo flujo son
  solo 2 GET simples (ya no navega ni hace click en nada), es posible
  que funcione IGUAL sin este toggle activado (correría en la nube de
  Anthropic sin depender de que tu computadora esté prendida) -- si
  querés, probalo desactivado una vez con "Run now" y contame si
  funciona; si no, volvé a activarlo.

## Instructions (pegar tal cual, o ajustar el ticker si hace falta)

```
Generá el briefing pre-market de hoy para QQQ y NDX.

1. Hacé GET a https://gex-terminal-api.onrender.com/market/premarket-briefing?symbol=QQQ
   (público, sin login). Puede tardar 30-60s en responder si el server
   estaba dormido -- es normal, esperá esa primera respuesta.
2. Hacé GET a https://gex-terminal-api.onrender.com/market/premarket-briefing?symbol=NDX
   (mismo endpoint, para el cruce QQQ/NDX).
3. Con el campo "string" de cada respuesta (ya trae niveles de gamma del
   último cierre, VIX, VIX Term Structure, y calendario económico),
   aplicá el marco de tus instrucciones de Project y escribime el
   briefing corto en el formato de siempre.

Si algún paso falla (el endpoint no responde, falta un dato en el
string), decímelo explícitamente en vez de inventar un número --
preferible un briefing incompleto pero honesto a uno con datos falsos.
No repitas el briefing completo dos veces en la misma respuesta aunque
corrijas algo a mitad de camino -- si te equivocás, corregí y dame UNA
sola versión final.
```

## Antes de confiarle el horario automático

Corré la tarea manualmente una vez ("Run now" si el panel lo tiene) y
revisá con calma:
- Que de verdad haya hecho los 2 GET (no haya inventado los datos).
- Que los números coincidan con lo que ves si abrís esas mismas URLs
  vos mismo en el navegador en ese momento.
- Que sea UN solo briefing, no dos ni con una sección de "esto falló"
  salvo que algo haya fallado de verdad.
- Formato esperado: 2-4 oraciones por instrumento, sin tabla, sin
  secciones.

Recién después de eso yo dejaría "Manually approve" cambiado a
automático, si es que ese trámite manual te sigue pareciendo necesario.
