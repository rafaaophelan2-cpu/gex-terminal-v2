# Scheduled Task 1 — Briefing Pre-Market (8:00 AM)

Requiere `briefing-shared-instructions.md` ya pegado en las
instrucciones del Project (creá esta tarea DESDE DENTRO de una
conversación de ese Project). Esto de acá va en el campo
**"Instructions"** al crear la tarea -- es lo ESPECÍFICO de esta tarea,
no repite el marco genérico (eso ya lo tiene por las instrucciones del
Project).

## Campos del formulario

- **Name**: `Briefing Pre-Market`
- **Frequency**: Daily, `08:00` -- **verificalo antes de confiar en el
  horario**: ya falló una vez (se disparó 23:32 hora Lima de un lunes en
  vez de las 8 AM). Probá primero con una hora rara (ej. 08:07) y fijate
  cuándo corre de verdad la primera vez.
- **Permissions**: `Manually approve` (pasalo a automático solo cuando
  el resultado sea bueno de forma consistente)
- **Require this computer**: activado (ON) -- necesita esto para poder
  usar Claude en Chrome y navegar de verdad

## Instructions (pegar tal cual)

```
Generá el briefing pre-market de hoy para QQQ y NDX.

1. Andá a https://www.insiderfinance.io/gamma-exposure/QQQ (público, sin
   login). El filtro 0DTE NO son los botones de arriba (esos son
   porcentajes informativos, van a marcar 0.0% y no hay que tocarlos).
   El selector real es un desplegable que dice "All expirations" --
   abrilo y elegí "Today (0DTE)". Recién ahí anotá de la tabla de
   métricas: Spot, Net GEX, Call GEX, Put GEX, Call Wall, Put Wall, Zero
   Gamma, ATM IV, Skew. NO hace falta el gráfico de barras (Strike
   Profile) -- los números ya están en la tabla.
2. Andá a https://www.insiderfinance.io/gamma-exposure/NDX, mismo
   cambio de filtro a "Today (0DTE)", y anotá lo mismo para NDX.
3. Hacé GET a
   https://gex-terminal-api.onrender.com/market/premarket-briefing?symbol=QQQ
   (público, sin login -- puede tardar 30-60s la primera vez si el
   server estaba dormido, es normal). Usá SOLO la parte de VIX, VIX Term
   Structure, y calendario económico de la respuesta -- ignorá los
   niveles de gamma de ahí, para eso ya tenés InsiderFinance en los
   pasos 1-2, que es la fuente de mejor calidad.
4. Con todo eso, aplicá tus instrucciones del Project (marco Aleks,
   cruce QQQ/NDX si aplica) y escribime el briefing corto en el formato
   de siempre.

Reglas:
- Si algún paso falla (la página no carga, no encontrás un dato),
  decímelo explícitamente en vez de inventar un número.
- Dame UNA sola versión del briefing en tu respuesta -- nunca dos
  briefings completos en la misma respuesta aunque te autocorrijas a
  mitad de camino.
```

## Antes de confiarle el horario automático

Corré la tarea manualmente una vez ("Run now" si el panel lo tiene) y
revisá con calma:
- Que de verdad haya navegado a InsiderFinance y elegido el desplegable
  "Today (0DTE)", no los botones de arriba.
- Que los números coincidan con lo que ves si abrís esas páginas vos
  mismo en ese momento.
- Que sea UN solo briefing, no dos.
- Que se haya disparado a la hora esperada (ver nota de Frequency).

Recién después de eso pasá "Manually approve" a automático.
