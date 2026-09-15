# Uso diario del Briefing

Esto va DENTRO del Project que ya tiene `briefing-project-instructions.md`
en sus instrucciones.

## Si tenés Claude en Chrome activo (recomendado)

Simplemente escribí:

```
Briefing
```

Claude ya sabe (por las instrucciones del Project) qué fuente usar según
la hora, qué URLs visitar, y qué formato darte. Para la corrida
automática de las 8:00 AM ver `briefing-scheduled-task-8am.md` -- eso
configura una Scheduled Task que hace este mismo paso solo, todos los
días.

## Fallback manual (sin navegación, o si algo falló)

Si Claude no pudo navegar solo (sin la extensión activa, o algún sitio
no cargó), completá esto a mano:

**Antes de las 08:30** — abrí vos mismo:
- `https://www.insiderfinance.io/gamma-exposure/QQQ`
- `https://www.insiderfinance.io/gamma-exposure/NDX` (opcional, para el cruce)

y pegá acá los valores relevantes (Spot, Net GEX, Call/Put GEX, Call
Wall, Put Wall, Zero Gamma, ATM IV, Skew) de cada uno.

**Desde las 08:30** — abrí vos mismo:
```
https://gexdash-5b885-default-rtdb.firebaseio.com/live_levels.json
```
y pegá el resultado. Además, andá a la pestaña **Utilidad** de
https://gex-terminal-8vb.pages.dev → sección "Briefing" → **Generar** →
**Copiar**, y pegá acá abajo lo que copiaste:

```
(pegar acá el string del botón "Briefing Complement")
```

**Siempre** — pegá una captura de pantalla del calendario económico
(pestaña News) si Claude no pudo navegar solo hasta ahí.

---

Con lo que hayas juntado: **Briefing.**
