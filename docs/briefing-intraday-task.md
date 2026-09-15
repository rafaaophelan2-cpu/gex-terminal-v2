# Scheduled Task 2 — Briefing Intradía (mercado abierto)

Requiere `briefing-shared-instructions.md` ya pegado en las
instrucciones del Project (creá esta tarea DESDE DENTRO de la misma
conversación/Project que la de Pre-Market). Esto de acá va en el campo
**"Instructions"** al crear la tarea.

Solo QQQ, solo datos en vivo de nuestra propia web -- NUNCA
InsiderFinance acá (tiene 15 min de delay, sirve para pre-market, no
para esto).

## Campos del formulario

- **Name**: `Briefing Intradía`
- **Frequency**: Daily -- elegí la hora de apertura de mercado (09:35
  hora NY ≈ 08:35 Lima, unos minutos después de la apertura para que ya
  haya datos reales de la sesión). Si querés una actualización más
  seguido durante el día, podés crear copias de esta misma tarea a
  otras horas (ej. cada 2 horas) -- no hace falta que te arme una lógica
  de repetición especial, con varias tareas puntuales alcanza.
- **Permissions**: `Manually approve` al principio, igual que la de
  Pre-Market.
- **Require this computer**: activado (ON).

## Instructions (pegar tal cual)

```
Generá el análisis intradía de ahora mismo para QQQ (SOLO QQQ, en
vivo -- no uses InsiderFinance acá, es para pre-market únicamente).

1. Hacé GET a
   https://gexdash-5b885-default-rtdb.firebaseio.com/live_levels.json
   (público, sin login). Trae en vivo: spot, cw1/cw2/cw3 (Call Walls),
   pw1/pw2/pw3 (Put Walls), zero_gamma, gamma_wall. Usá cw1 como el
   Call Wall principal y pw1 como el Put Wall principal (un solo nivel
   por lado, no los tres).
2. Hacé GET a
   https://gex-terminal-api.onrender.com/market/premarket-briefing?symbol=QQQ
   (público, sin login). Usá SOLO la parte de VIX y VIX Term Structure
   de la respuesta (es dato en vivo real, el nombre del endpoint no
   importa acá) -- ignorá la parte de niveles de gamma y de calendario
   de esta respuesta, para eso ya usaste el paso 1.
3. Con todo eso, aplicá tus instrucciones del Project (marco Aleks) y
   escribime la actualización intradía en el formato de siempre.

Reglas:
- Si algún paso falla, decímelo explícitamente en vez de inventar un
  número.
- Dame UNA sola versión de la respuesta -- nunca la repitas dos veces
  aunque te autocorrijas a mitad de camino.
```

## Antes de confiarle el horario automático

Corré la tarea manualmente una vez y confirmá que los niveles/VIX
coincidan con lo que ves vos mismo en el dashboard en ese momento, y que
sea una sola respuesta, no dos.
