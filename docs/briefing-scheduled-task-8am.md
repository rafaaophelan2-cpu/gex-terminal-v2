# Scheduled Task — Briefing pre-market (8:00 AM)

Instrucciones para crear la tarea programada en Claude Desktop (Pro).
**Importante**: creala desde DENTRO de una conversación del Project que
ya tiene `briefing-project-instructions.md` en sus instrucciones -- así
la tarea hereda ese marco sin que haga falta repetirlo acá. Si por algún
motivo la creás fuera del Project, pegale el contenido completo de
`briefing-project-instructions.md` antes de estos pasos.

## Campos del formulario

- **Name**: `Briefing pre-market`
- **Frequency**: Daily, `08:00` (hora de esta computadora -- confirmá que
  esté en horario de Lima)
- **Permissions**: `Manually approve` (dejalo así las primeras veces;
  cambialo a auto-approve solo cuando confirmes que el resultado es
  bueno de forma consistente)
- **Require this computer**: activado (ON) -- necesita esto para poder
  usar Claude en Chrome y navegar de verdad

## Instructions (pegar tal cual, o ajustar el ticker si hace falta)

```
Generá el briefing pre-market de hoy para QQQ y NDX.

1. Andá a https://www.insiderfinance.io/gamma-exposure/QQQ (público, sin
   login). Hacé click en el filtro "0DTE Exp" (arriba del todo, junto a
   Weekly/Monthly/All expirations) -- NUNCA uses Weekly/Monthly/All
   expirations, solo 0DTE. Anotá: Spot, Net GEX, Call GEX, Put GEX, Call
   Wall, Put Wall, Zero Gamma, ATM IV, Skew.
2. Andá a https://www.insiderfinance.io/gamma-exposure/NDX, click en
   "0DTE Exp" también, y anotá lo mismo para NDX.
3. Andá a https://gex-terminal-8vb.pages.dev, iniciá sesión si hace
   falta, andá a la pestaña News → Calendario económico, y anotá los
   próximos eventos macro de la semana (FOMC/CPI/NFP y similares).
4. Con todo eso, aplicá el marco de tus instrucciones de Project (fuente
   InsiderFinance porque es antes de las 08:30, cruce QQQ/NDX si aplica)
   y escribime el briefing corto en el formato de siempre.

Si algún paso falla (la página no carga, no encontrás un dato), decímelo
explícitamente en vez de inventar un número -- preferible un briefing
incompleto pero honesto a uno con datos falsos.
```

## Antes de confiarle el horario automático

Corré la tarea manualmente una vez (la mayoría de los paneles de
Scheduled Tasks tienen un botón "Run now" o similar) y revisá el
resultado con calma -- confirmá que:
- Realmente navegó a las 3 URLs (no alucinó los datos).
- Los números que dice coinciden con lo que ves vos mismo en esas
  páginas en ese momento.
- El formato de salida es el esperado (2-4 oraciones por instrumento,
  sin tabla, sin secciones).

Recién después de eso yo dejaría "Manually approve" cambiado a
automático, si es que ese trámite manual te sigue pareciendo necesario.
