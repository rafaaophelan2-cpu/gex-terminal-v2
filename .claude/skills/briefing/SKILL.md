---
name: briefing
description: Genera el briefing diario corto de gamma exposure (estilo Aleks Rosme) para MNQ/NQ con los datos en vivo de gex-terminal-v2 -- usar cuando el usuario pida "briefing", "el briefing de hoy", el análisis/resumen del día para arrancar la sesión, o el estado de niveles/VIX antes de operar.
---

# Skill: Briefing diario de gamma exposure

Reemplaza al botón "Análisis para el día" de la web (que llama a Groq,
limitado a 8000 TPM) -- generás el mismo tipo de nota corta pero
razonando vos mismo (más capacidad que Groq), con los datos reales del
`gex-terminal-v2` desplegado. v1: este es un punto de partida a afinar
con ejemplos reales que el usuario va a ir pasando.

Cargá primero `!\`cat .claude/skills/briefing/reference.md\`` -- ahí está
el marco teórico completo (mecánica de gamma/dealers, Context->Location->
Confirmation, y el formato exacto del "Estilo del briefing diario" con
ejemplos reales) que tenés que aplicar. No lo repitas en tu respuesta al
usuario, es tu conocimiento de fondo.

## Paso 1 — Determinar el/los ticker(s)

Por defecto: QQQ (el principal). Si el usuario no aclara nada, generá el
briefing de QQQ + VIX. Si menciona NDX/SPX explícitamente, o si conviene
para el cruce (ver reference.md, "Context"), sumalo.

## Paso 2 — Conseguir un token de la API

Necesitás loguearte contra el backend en vivo
(`https://gex-terminal-api.onrender.com`) para varios endpoints. Las
credenciales de la app (usuario/contraseña, distintas de las de Schwab
o Supabase) NO están en este archivo a propósito -- si no las tenés ya
en el historial de la conversación actual, pedíselas al usuario. Nunca
las hardcodees en este skill ni en ningún archivo que se vaya a commitear.

```bash
RESP=$(curl -s -X POST "https://gex-terminal-api.onrender.com/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"<usuario>","password":"<password>"}' --max-time 60)
TOKEN=$(echo "$RESP" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
```

## Paso 3 — Traer los datos en vivo

**Niveles de gamma (Call/Put Walls, Zero Gamma, Gamma Wall, spot,
conversion_ratio) -- Firebase, público, sin token:**
```bash
curl -s "https://gexdash-5b885-default-rtdb.firebaseio.com/live_levels.json" --max-time 30
```
Trae `{qqq_spot, conversion_ratio, cw1, cw2, cw3, pw1, pw2, pw3, zero_gamma, gamma_wall, levels: [{strike, net_gex}]}`
para el símbolo configurado en `settings.quantower_symbol` (QQQ por
defecto -- ver `backend/app/services/quantower_pusher.py` si hace falta
confirmar). Si el usuario pidió NDX/SPX y ese nodo no lo cubre, avisale
que este endpoint solo tiene el símbolo principal del pusher.

**Régimen de gamma**: se deriva, no hace falta pedirlo aparte --
`spot > zero_gamma` = régimen positivo (rango/mean-reverting);
`spot < zero_gamma` = régimen negativo (expansivo/trending). Ver
reference.md para cómo aplicar esto al tono del briefing.

**VIX + clasificación:**
```bash
curl -s "https://gex-terminal-api.onrender.com/market/vix" -H "Authorization: Bearer $TOKEN" --max-time 60
```

**VIX term structure (contango/backwardation):**
```bash
curl -s "https://gex-terminal-api.onrender.com/market/vix-term-structure" -H "Authorization: Bearer $TOKEN" --max-time 60
```

**Implied Range (expected move, techo/piso estadístico):**
```bash
curl -s "https://gex-terminal-api.onrender.com/market/implied-range?symbol=QQQ" -H "Authorization: Bearer $TOKEN" --max-time 60
```

**Calendario económico de la semana (catalizadores -- FOMC/CPI/NFP):**
```bash
curl -s "https://gex-terminal-api.onrender.com/market/economic-calendar" -H "Authorization: Bearer $TOKEN" --max-time 60
```

**Velas de hoy (para el contexto intradía -- apertura/máximo/mínimo/
movimiento reciente, ver `build_intraday_context` en
`backend/app/domain/ai_prompt.py` para la lógica exacta si querés
replicarla a mano):**
```bash
curl -s "https://gex-terminal-api.onrender.com/market/candles?symbol=QQQ" -H "Authorization: Bearer $TOKEN" --max-time 60
```

**Opcional / si el usuario te lo pide o lo pega él mismo**: Skew
put/call, IV ATM, IV Rank, y los Greeks agregados (DEX/TEX/VEX/CHEX/
Vanna) hoy solo se calculan en el tick de WebSocket (no hay un endpoint
REST simple para ellos todavía) -- el formato del briefing diario en sí
no los necesita citar como números (ver los ejemplos en reference.md,
son prosa de contexto, no una tabla de Greeks), así que no bloquees el
briefing por esto. Si en algún momento hace falta agregarlos de forma
confiable, lo más limpio sería un endpoint REST nuevo tipo
`GET /market/gex-snapshot` que exponga lo mismo que ya arma
`ai_context.py` para el prompt de Groq -- proponéselo al usuario como
mejora futura si ves que lo termina pidiendo seguido.

## Paso 4 — Producir el briefing

Con reference.md cargado y los datos de arriba, escribí el briefing
siguiendo EXACTO el formato de "Estilo del briefing diario" (2-4
oraciones por instrumento, sin headers, sin tabla, cerrando con una
condición/precaución si aplica). En español. No repitas los números
crudos sin interpretarlos -- igual que los ejemplos, cada número va
atado a qué significa para el trader (pivot, obstáculo, rango de VIX,
por qué).

## Paso 5 — Cerrar el loop de mejora

Como este skill todavía es v1: si esta es una de las primeras veces que
se usa, o si notás que el resultado no se parece al tono real de Aleks,
recordale al usuario (una sola línea, no lo conviertas en el foco de la
respuesta) que puede pegarte un briefing real de Aleks de ese mismo día
para comparar y ajustar `reference.md` -- pero el output principal de
esta skill siempre es el briefing en sí, no una discusión sobre la skill.
