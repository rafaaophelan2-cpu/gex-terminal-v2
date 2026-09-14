import logging
from datetime import date as date_cls
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.session_profile import format_session_profile

logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")


def build_intraday_context(candles: list[dict], current_price: float) -> str:
    """Resume el movimiento de precio de HOY (apertura, máximo, mínimo, y
    el movimiento de los últimos ~30 minutos) para que la IA razone
    escenarios coherentes con lo que el precio YA hizo. Port de
    get_intraday_context en app.py (~línea 1974), usando velas reales de
    Schwab (fetch_price_history) en vez de un DataFrame de Streamlit."""
    if not candles:
        return "Sin datos de velas intradía disponibles todavía."

    try:
        day_high = max(c['high'] for c in candles)
        day_low = min(c['low'] for c in candles)
        day_open = candles[0]['open']
        rango_total = max(day_high - day_low, 0.01)

        recent = candles[-30:]
        move_pts = 0.0
        move_min = 0
        if recent:
            move_start = recent[0]['close']
            move_pts = current_price - move_start
            move_min = len(recent)

        if current_price > (day_low + rango_total * 0.66):
            posicion_rango = "en la parte ALTA"
        elif current_price < (day_low + rango_total * 0.33):
            posicion_rango = "en la parte BAJA"
        else:
            posicion_rango = "en la zona MEDIA"

        direccion = "al alza" if move_pts > 0.05 else "a la baja" if move_pts < -0.05 else "prácticamente lateral"

        return (
            f"Apertura de hoy: {day_open:.2f} | Máximo del día: {day_high:.2f} | "
            f"Mínimo del día: {day_low:.2f} | Rango recorrido hoy: {rango_total:.2f} pts. "
            f"El precio actual está {posicion_rango} de ese rango. "
            f"En los últimos {move_min} min se movió {move_pts:+.2f} pts ({direccion})."
        )
    except Exception:
        logger.exception("build_intraday_context() falló con %d velas -- se usa el placeholder.", len(candles))
        return "Sin datos de velas intradía disponibles todavía."


def classify_vix(vix_val: float) -> tuple[str, str, str]:
    """(status, descripcion, color) -- mismos cortes que app.py (~línea 1619)."""
    if vix_val < 15.0:
        return "Baja Volatilidad", "Mercado calmado / TPs cortos", "#60A5FA"
    if vix_val < 25.0:
        return "Volatilidad Media", "Rango saludable / Aguantar Runners", "#10B981"
    if vix_val <= 30.0:
        return "Volatilidad Alta", "Rango saludable / Aguantar Runners", "#F59E0B"
    return "Muy Alta Volatilidad", "Miedo grande / Movimientos muy expansivos", "#EF4444"


def format_vix_term_structure(vix_term_structure: dict | None) -> str:
    """VIX (30d) vs VIX3M (90d) -- ver fetch_vix_term_structure en
    schwab_client.py. Contango (VIX < VIX3M) es el estado normal/sano;
    backwardation (VIX > VIX3M) es la señal de estrés real, todo el
    mundo corriendo a cubrirse YA en vez de en 3 meses."""
    if not vix_term_structure or not vix_term_structure.get("vix") or not vix_term_structure.get("vix3m"):
        return "Term structure VIX/VIX3M: sin dato disponible ahora mismo."
    vix = vix_term_structure["vix"]
    vix3m = vix_term_structure["vix3m"]
    state = vix_term_structure.get("state", "n/a")
    if state == "backwardation":
        read = "BACKWARDATION (VIX > VIX3M) -- señal de estrés real, el mercado está pagando más por protección inmediata que por protección a 3 meses. Dale menos crédito a un régimen de gamma positiva/rango si esto se sostiene: el estrés de corto plazo suele preceder rupturas, no rangos."
    else:
        read = "Contango (VIX < VIX3M) -- estado normal/sano, sin estrés de corto plazo inusual sobre la volatilidad de mediano plazo."
    return f"Term structure VIX/VIX3M: VIX={vix:.2f}, VIX3M={vix3m:.2f} -> {read}"


def format_implied_range(implied_range: dict | None, ticker: str) -> str:
    """Banda de movimiento esperado (expected move) desde la IV ATM de la
    expiración más cercana -- techo/piso ADICIONAL a los niveles de
    gamma, no un reemplazo. Ver domain/implied_range.py."""
    if not implied_range or not implied_range.get("one_sd"):
        return f"Implied Range de {ticker}: sin dato disponible ahora mismo (requiere IV ATM válida)."
    one_sd = implied_range["one_sd"]
    two_sd = implied_range["two_sd"]
    move = implied_range["expected_move"]
    return (
        f"Implied Range de {ticker} (expected move de la expiración más cercana, ±1 desvío estándar): "
        f"{one_sd['low']:.2f} - {one_sd['high']:.2f} USD (movimiento esperado ±{move:.2f} pts). "
        f"±2 desvíos (cola, menos probable pero no descartable): {two_sd['low']:.2f} - {two_sd['high']:.2f} USD. "
        f"Tratalo como el techo/piso ESTADÍSTICO de la sesión -- un escenario que proyecte un TP fuera de la banda de "
        f"±1 desvío necesita sustento extra (un nivel de gamma real ahí, no solo momentum), y prácticamente nunca debería "
        f"salirse de la banda de ±2 desvíos."
    )


_IMPACT_LABELS = {"low": "bajo", "medium": "medio", "high": "ALTO"}


def format_economic_calendar(economic_calendar: list[dict] | None, today_str: str = "") -> str:
    """Eventos macro de EE.UU. de la SEMANA relevante (ver
    integrations/forexfactory_client.py::fetch_economic_calendar -- semana
    actual en día hábil, semana siguiente en fin de semana), no solo hoy:
    un analista real de order flow razona con catalizadores de DÍAS por
    delante, no solo el de la mañana (ej.: "IV se mantiene alta, lo cual
    tiene sentido con el FOMC en tres días" -- ese tipo de frase necesita
    ver el calendario completo de la semana, no solo hoy). Vacío/None
    (sin FINNHUB_API_KEY configurada, o sin eventos esta semana) es un
    estado NORMAL, no un error -- se lo dice así al modelo para que no
    invente un catalizador que no existe.

    'today_str' (ISO, ej. "2026-09-13"): para precomputar "en N días" por
    evento EN PYTHON -- nunca se le pide al modelo que reste dos fechas
    él mismo (mismo motivo que el resto de la aritmética de este prompt,
    ver REGLAS DURAS DE COHERENCIA DE PRECIOS más abajo: un LLM no resta
    fechas de forma confiable, las aproxima por patrón de texto)."""
    # Filtra 'low' SOLO acá (la pestaña News sigue mostrando los 3
    # niveles -- ver GET /market/economic-calendar, que llama a
    # fetch_economic_calendar sin este filtro) -- pedido de presupuesto de
    # tokens: el prompt de este sistema ya es grande (framework completo +
    # niveles + perfiles de sesión) y Groq cuenta prompt+max_tokens contra
    # el límite de Tokens Por Minuto de la cuenta (confirmado en vivo: un
    # 413 "tokens per minute" por CADA pedido cuando el calendario de la
    # semana traía muchos eventos de bajo impacto que no cambian el
    # análisis, ver groq_client.py). 'low' es ruido menor que casi nunca
    # pesa en el razonamiento -- se recorta acá, no se pierde nada
    # relevante.
    economic_calendar = [ev for ev in (economic_calendar or []) if ev.get("impact") != "low"]
    # Tope adicional -- una semana muy cargada (ej. temporada de CPI +
    # FOMC + varios discursos de la Fed) puede tener bastante más de esto
    # incluso ya sin 'low'; ya ordenado cronológicamente (ver
    # fetch_economic_calendar), así que los primeros son los más
    # inmediatos.
    MAX_EVENTS_SHOWN = 15
    truncated_count = max(0, len(economic_calendar) - MAX_EVENTS_SHOWN)
    economic_calendar = economic_calendar[:MAX_EVENTS_SHOWN]

    if not economic_calendar:
        return "Calendario económico de esta semana: sin eventos de impacto medio/alto en EE.UU. (o sin esta fuente configurada)."

    today_date = None
    if today_str:
        try:
            today_date = date_cls.fromisoformat(today_str)
        except ValueError:
            today_date = None

    lines = []
    last_date = None
    for ev in economic_calendar:
        date_str = ev.get("date") or ""
        if date_str != last_date:
            if date_str == today_str:
                day_label = f"HOY ({date_str})"
            elif today_date is not None and date_str:
                try:
                    delta = (date_cls.fromisoformat(date_str) - today_date).days
                    day_label = f"en {delta} día{'s' if delta != 1 else ''} ({date_str})" if delta > 0 else date_str
                except ValueError:
                    day_label = date_str
            else:
                day_label = date_str or "fecha sin confirmar"
            lines.append(f"  {day_label}:")
            last_date = date_str

        time_str = ev.get("time") or "hora sin confirmar"
        impact = _IMPACT_LABELS.get(ev.get("impact"), str(ev.get("impact") or "?"))
        actual = ev.get("actual")
        forecast = ev.get("forecast")
        previous = ev.get("previous")
        detail = f" (real={actual}, esperado={forecast}, anterior={previous})" if actual not in (None, "") else (
            f" (esperado={forecast}, anterior={previous})" if forecast not in (None, "") else ""
        )
        lines.append(f"    - {time_str} NY -- {ev.get('event')} [impacto {impact}]{detail}")

    joined = "\n".join(lines)
    return (
        "Calendario económico de esta semana (EE.UU., impacto medio/ALTO):\n"
        f"{joined}\n"
        "Un evento de HOY AÚN NO PUBLICADO (sin 'real' todavía) es un catalizador de riesgo binario -- bajale la "
        "convicción a cualquier escenario que dependa de que el régimen actual se sostenga hasta después de esa hora. "
        "Un evento YA PUBLICADO ('real' presente) que sorprendió fuerte contra lo esperado puede invalidar de golpe el "
        "contexto de gamma/VIX de antes. Un evento de un día FUTURO (no hoy) es un catalizador que puede explicar POR "
        "QUÉ la IV está elevada o por qué el mercado se comporta cauteloso incluso sin movimiento de precio visible "
        "todavía -- mencionalo así cuando aplique (ej. \"la IV se mantiene alta, consistente con el <evento> en N "
        "días\", usando el 'en N días' YA CALCULADO arriba, nunca restando las fechas vos mismo). Impacto medio pesa "
        "como contexto; impacto ALTO puede invalidar de golpe el régimen de gamma/VIX vigente."
        + (f"\n(+{truncated_count} eventos más adelante en la semana, no mostrados acá por espacio.)" if truncated_count else "")
    )


def build_system_prompt(
    ticker: str,
    spot: float,
    metrics: dict,
    vix_val: float,
    intraday_context: str,
    conversion_ratio: float = 41.125,
    dte_note: str = "",
    overnight_profile: dict | None = None,
    cash_profile: dict | None = None,
    vix_term_structure: dict | None = None,
    ndx_cross_check: str = "",
    implied_range: dict | None = None,
    oi_is_volume_proxy: bool = False,
    macro_levels: dict | None = None,
    vix_gamma_levels: dict | None = None,
    economic_calendar: list[dict] | None = None,
    response_mode: str = "chat",
) -> str:
    """Port ampliado del system_prompt de consultar_ia en app.py (~línea
    2066): mismos datos de mercado y mismas reglas duras de coherencia
    direccional/de precios, pero con (1) un marco teórico mucho más
    profundo sobre mecánica de gamma exposure/hedging de dealers para
    que el razonamiento de cada escenario tenga sustento real, (2) un
    checklist de confirmación por order flow obligatorio y específico
    por escenario (el modelo NO tiene datos de order flow en vivo, pero
    debe decir exactamente qué buscar), y (3) detección de modo de
    respuesta: solo fuerza el informe estructurado completo cuando el
    usuario realmente pide un análisis/trade, no ante un saludo o
    pregunta conversacional (antes el chat respondía SIEMPRE con el
    informe completo sin importar el mensaje).

    'response_mode' ("chat" | "full" | "daily_briefing" | "short_term"):
    el chat libre (routes_chat.py) no sabe de antemano qué va a pedir el
    usuario, así que deja "chat" (todas las secciones de estilo
    disponibles, más el bloque que le pide al modelo decidir el formato
    él mismo). Los 3 botones de Briefings (routes_rest.py), en cambio,
    YA SABEN qué formato quieren -- pasarles el modo correcto evita
    mandarle a Groq las instrucciones de LOS OTROS DOS formatos que ese
    pedido puntual no va a usar nunca. Esto no es cosmético: el prompt
    base (antes de sumar ningún dato de mercado real) medía ~27.500
    caracteres (~8.300 tokens estimados), ya por encima del límite de
    8000 Tokens Por Minuto de la cuenta de Groq en producción -- gatear
    estas secciones por modo es la forma de que la llamada real a Groq
    deje de saltarse por falta de presupuesto (ver groq_client.py)."""
    vix_status, vix_desc, _ = classify_vix(vix_val)

    # Cuando hay perfiles de sesión reales (Overnight/Cash, ver
    # domain/session_profile.py, empujados por el indicador de Quantower
    # SessionProfilePusher.cs), la IA SÍ tiene datos reales de volume/delta/
    # TPO profile estructural -- ya no aplica la advertencia de "no tengo
    # esos datos" tal cual, solo se mantiene para el footprint EN VIVO del
    # instante exacto, que sigue sin estar disponible.
    has_session_data = bool(overnight_profile or cash_profile)
    order_flow_line = (
        "Tienes acceso a datos REALES de Volume Profile, Delta Profile y TPO Profile de las sesiones Overnight y Cash "
        "(ver la sección PERFILES DE SESIÓN más abajo) -- úsalos como parte real de tu análisis de order flow, no son una "
        "simulación. Lo único que sigues sin ver es el footprint/delta acumulado EN VIVO del instante exacto -- ahí sigue "
        "aplicando: nunca inventes una lectura del momento presente (\"veo absorción ahora mismo\" sigue PROHIBIDO), pero "
        "para los niveles estructurales (POC/VAH/VAL/HVN/LVN/delta outliers/TPO) sí tienes el dato real, no digas que no lo tienes."
        if has_session_data else
        "Usa footprint chart, cumulative delta y volume profile como herramientas de ejecución. Tú NO tienes esos datos en "
        "vivo todavía -- nunca inventes lecturas de order flow concretas (\"veo absorción ahora mismo\" está PROHIBIDO)."
    )

    session_profiles_section = (
        f"PERFILES DE SESIÓN -- VOLUME/DELTA/TPO PROFILE (Overnight 17:00-08:29 y Cash 08:30-15:00, hora Lima/UTC-5). "
        f"Los niveles ya vienen con su equivalente en {ticker} calculado (dividido por el ratio de conversión "
        f"{conversion_ratio:.4f}) -- COMPARÁ ESE EQUIVALENTE directo contra tus walls/Zero Gamma, no hagas la conversión "
        f"vos mismo, y NO digas que dos niveles están alineados si sus equivalentes en {ticker} difieren por más de "
        f"~0.3 USD:\n"
        f"{format_session_profile('Overnight (Asia/London/pre-market)', overnight_profile, conversion_ratio, ticker)}\n\n"
        f"{format_session_profile('Cash Session', cash_profile, conversion_ratio, ticker)}\n"
        if has_session_data else ""
    )

    # Dirección inversa a la de session_profile.py (que ya precomputa
    # puntos NQ/MNQ -> USD {ticker}): acá el trader necesita sus walls/Zero
    # Gamma -- que están en USD {ticker} -- traducidos a puntos NQ/MNQ para
    # compararlos contra su chart de futuros. Se precomputa EN PYTHON por
    # la misma razón que la otra dirección: dejar que el modelo multiplique
    # "wall * ratio" a mano en el texto de la respuesta produjo resultados
    # aritméticamente incorrectos (ej. 708 * 41.105 respondido como 29115
    # en vez de 29102.34) -- un LLM no ejecuta la multiplicación, la
    # aproxima por patrón de texto.
    def _wall_in_points(usd_value: float) -> str:
        return f"{usd_value:.2f} USD ({usd_value * conversion_ratio:,.2f} pts NQ/MNQ)"

    dominant_wall = metrics.get("dominant_wall")
    dominant_wall_line = f"\n  Gamma Wall={_wall_in_points(dominant_wall)}" if dominant_wall else ""

    gamma_levels_in_points = (
        f"- Niveles de gamma en puntos NQ/MNQ (YA CALCULADOS, USÁLOS TAL CUAL -- NUNCA multipliques wall x ratio vos "
        f"mismo en la respuesta, incluso si parece una cuenta simple; usa exactamente estos números):\n"
        f"  CW1={_wall_in_points(metrics['cw1'])}, CW2={_wall_in_points(metrics['cw2'])}, CW3={_wall_in_points(metrics['cw3'])}\n"
        f"  PW1={_wall_in_points(metrics['pw1'])}, PW2={_wall_in_points(metrics['pw2'])}, PW3={_wall_in_points(metrics['pw3'])}\n"
        f"  Zero Gamma={_wall_in_points(metrics['zero_gamma'])}{dominant_wall_line}"
    )

    # Skew put/call cerca del ATM (ver domain/metrics.py) -- puts más caros
    # que calls es NORMAL en índices (protección contra caídas), lo que
    # importa es que esté CRECIENDO: eso es "miedo construyéndose" en
    # silencio, antes de que el precio lo muestre (Rosme, video de
    # volatilidad/vol surface). None si no hay suficiente data de un lado.
    skew_line = ""
    skew_val = metrics.get("skew")
    if skew_val is not None:
        skew_pct = skew_val * 100
        if skew_pct > 3.0:
            skew_note = "skew alto/empinado hacia puts -- miedo de caída ya construido, exige más confirmación para longs agresivos"
        elif skew_pct > 1.0:
            skew_note = "skew normal/sano de índice (puts algo más caros que calls, esperable)"
        else:
            skew_note = "skew plano o invertido hacia calls -- poco miedo de caída puesto en precio, cuidado con complacencia"
        skew_line = f"- Skew Put/Call (ATM): {skew_pct:+.2f} puntos de IV (Put IV − Call IV) -- {skew_note}"

    vix_term_structure_line = format_vix_term_structure(vix_term_structure)
    implied_range_line = format_implied_range(implied_range, ticker)
    ndx_cross_check_section = f"\n{ndx_cross_check}\n" if ndx_cross_check else ""

    # Call Resistance/Put Support de TODAS las expiraciones combinadas (a
    # diferencia de CW1-3/PW1-3 arriba, que son solo la expiración más
    # cercana/0DTE) -- el "rango semanal" de Aleks Rosme: mucho más
    # estable día a día, se usa como límite macro, no como nivel de
    # scalping. Puede llegar vacío si el feed todavía no tuvo su primer
    # tick DEEP (ver services/market_feed.py).
    macro_levels_line = ""
    if macro_levels and macro_levels.get("cw1") and macro_levels.get("pw1"):
        macro_levels_line = (
            f"- Rango Semanal/Macro (Call Resistance / Put Support, TODAS las expiraciones combinadas -- límite "
            f"estructural, no nivel de scalping): Call Resistance={_wall_in_points(macro_levels['cw1'])}, "
            f"Put Support={_wall_in_points(macro_levels['pw1'])}"
        )

    # Niveles de gamma de VIX mismo (ver services/cross_check.py) -- VIX
    # tiene su propia correlación NEGATIVA con equities: un nivel de
    # gamma positivo actuando como soporte/resistencia EN VIX implica el
    # movimiento contrario en {ticker} (si VIX rebota ahí hacia arriba,
    # equities deberían caer, y viceversa).
    vix_gamma_levels_line = ""
    if vix_gamma_levels and vix_gamma_levels.get("cw1") and vix_gamma_levels.get("pw1"):
        vgl = vix_gamma_levels
        vix_gamma_levels_line = (
            f"- Niveles de Gamma de VIX (correlación NEGATIVA con {ticker} -- úsalo como señal INVERSA, nunca "
            f"directa): VIX Call Wall={vgl['cw1']:.2f}, VIX Put Wall={vgl['pw1']:.2f}, VIX Zero Gamma="
            f"{vgl['zero_gamma']:.2f}. Si VIX está rebotando/pineado en uno de estos niveles, esperá el movimiento "
            f"CONTRARIO en {ticker} aunque no haya catalizador visible todavía en el precio de {ticker}."
        )

    today_str = datetime.now(NY_TZ).date().isoformat()
    economic_calendar_line = format_economic_calendar(economic_calendar, today_str)

    # NDX/VIX (productos de índice exclusivos de CBOE) no traen Open
    # Interest real de Schwab -- para esos se pide a MarketData.app (ver
    # integrations/marketdata_client.py). Este flag solo se prende cuando
    # AMBAS fuentes fallan (Schwab estructuralmente, y MarketData.app por
    # rate-limit/timeout/lo que sea en este momento puntual) y el sistema
    # cae al viejo proxy de volumen. Sin esta advertencia el modelo
    # analizaría ese GEX como si fuera posicionamiento acumulado real.
    oi_proxy_warning = (
        f"\n⚠️ ADVERTENCIA DE CALIDAD DE DATO PARA {ticker}: no se pudo obtener Open Interest real para este símbolo "
        f"ahora mismo (Schwab no lo da para índices, y la fuente alternativa -- MarketData.app -- falló o no "
        f"respondió a tiempo en este momento puntual, puede ser transitorio). Todo el GEX/niveles de abajo está "
        f"calculado usando VOLUMEN DEL DÍA como aproximación en vez de posicionamiento acumulado real -- es decir, "
        f"refleja la actividad de HOY, no cuánta exposición tienen los dealers acumulada de días/semanas anteriores. "
        f"Tratá estos niveles con MENOS convicción que los de un símbolo con OI real: aclaralo explícitamente en tu "
        f"análisis, y exigí confirmación de order flow más estricta antes de operar cualquier setup basado en ellos.\n"
        if oi_is_volume_proxy else ""
    )

    # Gateo por modo -- ver docstring de más arriba. "chat" arma TODO
    # (no sabe de antemano qué va a pedir el usuario); los 3 modos de
    # botón solo arman lo que ESE botón necesita.
    include_daily_briefing_style = response_mode in ("chat", "daily_briefing")
    include_short_term_style = response_mode in ("chat", "short_term")
    include_full_report_rules = response_mode in ("chat", "full")
    # El briefing corto (2-4 frases de prosa, sin setups numéricos) no
    # necesita la definición de los 3 setups operables, las reglas duras
    # de coherencia de entrada/TP, la regla de direccionalidad ni las
    # reglas de VIX pensadas para calibrar setups -- eso es SOLO para los
    # modos que sí proponen un trade operable (full y short_term).
    include_setup_mechanics = response_mode in ("chat", "full", "short_term")

    format_decision_block = (
        """
    ================================================================
    CÓMO DECIDIR EL FORMATO DE TU RESPUESTA (leer con atención, esto es tan importante como el análisis mismo)
    ================================================================
    - Si el último mensaje del usuario es conversacional (saludo, agradecimiento, una pregunta general sobre cómo funciona algo, una aclaración sobre tu respuesta anterior, charla casual, o cualquier cosa que NO sea un pedido explícito o implícito de análisis/niveles/trade) -- responde de forma NATURAL, breve y cercana, como lo haría un analista humano con criterio propio. Puedes mencionar brevemente el estado del mercado si viene al caso, pero NO fuerces la estructura de 5 secciones ni la tabla de escenarios si no te la están pidiendo. Tienes memoria de los mensajes anteriores de esta conversación (te llegan como parte del historial) --úsala para mantener continuidad real, no trates cada mensaje como aislado.
    - Si el usuario pide específicamente un BRIEFING DIARIO CORTO (lo vas a reconocer porque el pedido dice explícitamente "briefing corto" o equivalente) -- usa el formato de la sección "ESTILO DE BRIEFING DIARIO" de más abajo, NUNCA la estructura de 5 secciones ni la tabla. Esto tiene prioridad sobre la regla siguiente.
    - Si el usuario pide específicamente un ANÁLISIS DE CORTO PLAZO/INTERNO (lo vas a reconocer porque el pedido dice explícitamente "corto plazo" o equivalente) -- usa el formato de la sección "ESTILO CORTO PLAZO" de más abajo, NUNCA la estructura de 5 secciones completa ni los niveles extremos del rango. Misma prioridad que la regla anterior.
    - Si el usuario pide un análisis, un trade, una lectura del mercado, "qué hago", niveles, un diagnóstico, o cualquier variante que busque una decisión operable -- ahí SÍ aplica el framework completo (secciones 1-5, los tres setups: Rebote / Ruptura y Retesteo / Ruptura y Retesteo Fallido -> Entrada Contraria, tabla resumen) definido más abajo, con el mismo rigor de siempre.
    - Ante la duda, prioriza ser útil y conversacional antes que imponer un informe extenso que nadie pidió.
    """
        if response_mode == "chat" else
        "\n    Este pedido puntual ya especifica el formato de respuesta -- respondé SIEMPRE con el formato de la sección "
        + (
            "'ESTILO DE BRIEFING DIARIO'" if response_mode == "daily_briefing" else
            "'ESTILO CORTO PLAZO'" if response_mode == "short_term" else
            "'REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO'"
        )
        + " de más abajo, sin necesidad de decidir el formato vos mismo (no es un mensaje conversacional ni ambiguo).\n"
    )

    daily_briefing_style_block = (
        """
    ================================================================
    ESTILO DE BRIEFING DIARIO -- SOLO cuando el usuario pide explícitamente el briefing corto (ver regla arriba)
    ================================================================
    Esto NO es el informe completo. Es la nota corta que se manda ANTES de la apertura o entre catalizadores: 2 a 4 oraciones cortas por instrumento ({ticker}, VIX, y NDX/SPX si el dato está disponible), sin encabezados de sección, sin checklist de order flow, sin tabla. Mencioná explícitamente: (1) el Pivot Point del día y el próximo obstáculo/pared en cada dirección (usa CW1/PW1 de arriba), (2) el rango en el que está "atrapado" el VIX ahora mismo y por qué (catalizador macro si hay uno cerca -- FOMC, CPI, vencimiento de VIX, datos económicos -- o directamente que no hay ninguno visible), (3) el régimen de gamma actual en una frase, sin explicar el mecanismo en detalle (ya lo hiciste, acá no hace falta). Ejemplos reales de este tono (referencia de estructura y longitud, no los copies literal):
      - "715 en QQQ actúa como pivot point, 717 es el obstáculo más grande al alza. A la baja, 711 es el primer objetivo. VIX recuperó la zona 17-16.5 y por ahora queda encerrado en ese rango con 15.5 como objetivo a la baja. La IV sigue alta, lo cual tiene sentido con el FOMC en tres días -- no esperaría un IV crush todavía."
      - "QQQ vuelve al rango 713-717 con 715 como pivot point de hoy. Un retest de 717 sería ideal mientras el net drift siga negativo. Vence VIX hoy, el nivel de 19 anterior quedó descartado -- ahora la expiración del 16/09 está llena de gamma positivo, lo que encierra a VIX entre 17 y 15.50 al menos hasta el CPI. La IV luce elevada porque VIX está intentando romper al alza."
    Cerrá siempre con una frase de precaución/condición si corresponde (ej. "mientras el régimen de gamma no cambie", "si no hay sorpresa en el dato de hoy").
    """.format(ticker=ticker)
        if include_daily_briefing_style else ""
    )

    short_term_style_block = (
        """
    ================================================================
    ESTILO CORTO PLAZO -- SOLO cuando el usuario pide explícitamente el análisis de corto plazo (ver regla arriba)
    ================================================================
    El trader YA conoce los extremos grandes del rango del día (Rango Semanal/Macro, CW3/PW3) -- este análisis es justo lo contrario a eso: encontrar EL nivel interno más convincente, cerca del precio, para un trade de 5-15 minutos. Reglas estrictas de esta sección:
    - USÁ SOLO CW1/PW1/Zero Gamma (y Gamma Wall si coincide con CW1 o PW1) como niveles operables. NUNCA CW2/CW3/PW2/PW3 ni el Rango Semanal/Macro como entrada o TP -- si alguno de esos coincide con un nivel compuesto de NDX o un POC/VAH/VAL de sesión, podés mencionarlo como REFUERZO de un nivel interno cercano, nunca como nivel operable en sí mismo.
    - Formato: SIN tabla, sin encabezados "1./2./3." numerados. Estructura en prosa breve:
      1. Una frase de contexto (régimen de gamma + VIX, sin repetir el mecanismo que ya explicaste antes).
      2. Cuál es el nivel interno elegido (CW1, PW1 o Zero Gamma) y por qué es el más convincente AHORA MISMO (dominancia del Net GEX ahí, refuerzo de volumen/nivel compuesto si aplica).
      3. UN solo setup operable (Rebote / Ruptura y Retesteo / Ruptura y Retesteo Fallido -> Entrada Contraria, mismo nombre exacto que siempre) con entrada, TP e invalidación numéricos, coherentes con las REGLAS DURAS y la REGLA DE DIRECCIONALIDAD de abajo -- especial cuidado ahí: si el nivel elegido está a centavos del spot, verificá de qué lado exacto del nivel está el spot AHORA MISMO respecto al TP antes de nombrar el setup (mismo lado = Ruptura y Retesteo, lado contrario = Rebote, nunca al revés).
      4. Qué confirmar en order flow antes de entrar (mismo criterio que el resto del framework, mismo tipo de absorción que describiste en el punto 3 -- nunca uno distinto acá).
    - Mencioná los extremos grandes del día SOLO si hace falta aclarar que quedan fuera de alcance para este trade puntual (ej. "el techo estructural del día está en X, pero para 5-15 min el nivel real a vigilar es Y") -- nunca como parte del setup en sí.
    """
        if include_short_term_style else ""
    )

    trader_profile_block = (
        f"""
    PERFIL DEL TRADER AL QUE ASESORAS (cuando sí corresponda el análisis completo -- esta es SU estrategia real, no una genérica):
    - Opera intradía puro en MNQ Futures: sus trades duran entre 5 y 30 minutos, NUNCA "swing". Sus niveles de referencia (Call/Put Walls, Zero Gamma) están en {ticker} -- factor de conversión: {conversion_ratio:.4f}.
    - Opera EXCLUSIVAMENTE desde los niveles de gamma más importantes del día, con tres setups y solo esos tres -- todo escenario debe encajar en uno, con ese nombre exacto:
      * **Rebote**: precio SE ACERCA a un nivel desde el lado CONTRARIO al TP y rechaza sin romperlo (mecha de absorción) -- entrada en la dirección del rechazo, volviendo hacia el nivel opuesto o Zero Gamma, nunca cruzando el nivel que rechazó.
      * **Ruptura y Retesteo**: precio YA rompió un nivel (spot del MISMO lado que el TP), retestea desde el otro lado y aguanta -- entrada en la dirección de la ruptura original, en el retest, continuando hacia el TP sin volver a cruzar el nivel.
      * **Ruptura y Retesteo Fallido -> Entrada Contraria** (trampa): precio rompe un nivel, pero el retest NO aguanta (falla y cruza de vuelta al lado original) -- entrada en la dirección CONTRARIA a la ruptura original, NUNCA a favor de ella, al confirmarse el fallo.
    - {order_flow_line} Herramientas de confirmación de ESTE trader: delta grid, cumulative delta, footprint de delta -- decí EXACTAMENTE qué buscar ahí para confirmar/invalidar cada setup: absorción (mecha con volumen sin desplazamiento neto), agresión sostenida en el delta acumulado, divergencias precio/delta como agotamiento.
    - REFUERZO DE NIVELES (Overnight/Cash, ver PERFILES DE SESIÓN si hay datos): un nivel de gamma que coincide o está muy cerca de un POC/VAH/VAL/HVN/delta outlier tiene MÁS convicción -- decilo explícito; si no hay refuerzo cerca, acláralo también (setup más débil, exige más confirmación).
    - TAKE PROFIT: nivel real, nunca inventado -- prioridad: (1) delta outlier de sesión, (2) próximo nivel de gamma (wall opuesto o Zero Gamma), (3) POC/VAH/VAL de sesión.
    - CHARM (CHEX) COMO FILTRO DE CONVICCIÓN, NO COMO NIVEL: sesgo direccional mecánico (más fuerte cerca de 0DTE y avanzada la sesión). CHEX positivo = viento de cola alcista (dealers forzados a comprar por decaimiento de delta) -- más convicción a un setup alcista, más confirmación exigida a uno bajista contra ese flujo (espejado si es negativo). En Ruptura Fallida -> Contraria: charm EN CONTRA de la ruptura original refuerza que la reversión es real; charm A FAVOR de la ruptura exige más confirmación antes de tomar la reversión.
    - NUNCA propongas objetivos (TP) de tipo swing -- alcanzables en minutos, no en días.
    """
        if include_setup_mechanics else ""
    )

    # Regla 6 más abajo tenía una excepción ("CW2/PW2 solo si están cerca")
    # que CONTRADECÍA directamente a ESTILO CORTO PLAZO ("NUNCA CW2/CW3/
    # PW2/PW3") -- ambos bloques se mandan juntos en response_mode
    # "short_term" (y en "chat", donde el modelo debe elegir el formato
    # él mismo), así que el modelo recibía instrucciones opuestas sobre
    # si CW2/PW2 son niveles operables. En modo short_term la respuesta es
    # inequívoca (nunca), así que ahí se saca la excepción; en los demás
    # modos la regla general (con la excepción) sigue aplicando tal cual.
    cw2_pw2_clause = (
        "Priorizá siempre CW1/PW1."
        if response_mode == "short_term" else
        "Priorizá siempre CW1/PW1 (y CW2/PW2 solo si están razonablemente cerca)."
    )
    hard_price_rules_block = (
        f"""
    REGLAS DURAS DE COHERENCIA DE PRECIOS (verificalas numéricamente antes de responder; si las violás, la respuesta es inútil):
    1. Precio actual de {ticker}: {spot:.2f}. Toda entrada debe estar razonablemente cerca (pullback/retest lógico), nunca en un nivel ya lejano.
    2. LONG: TP SIEMPRE mayor que la entrada. SHORT: TP SIEMPRE menor que la entrada.
    3. No cacés una reversión (short tras caída fuerte, long tras subida fuerte) sin razón estructural explícita (rechazo confirmado, agotamiento de mecha, absorción visible).
    4. Usá el contexto de movimiento reciente de abajo para calibrar escenarios -- si ya hubo un movimiento grande, priorizá continuación con retest o agotamiento en un nivel específico.
    5. NUNCA multipliques/dividas manualmente un nivel por el ratio de conversión USD {ticker} <-> puntos NQ/MNQ -- ya viene calculado arriba ("Niveles de gamma en puntos NQ/MNQ" y cada nivel de PERFILES DE SESIÓN). Copiá esos números tal cual; una cuenta hecha a mano en el texto es la fuente más común de errores aritméticos.
    6. DISTANCIA MÁXIMA REALISTA (trades de 5-30 min): no uses CW3/PW3 ni el Rango Semanal/Macro como entrada/TP si está a más de ~1% del spot (para {ticker} en {spot:.2f}, ±{spot * 0.01:.2f} USD). Un nivel más lejano podés MENCIONARLO como techo/piso estructural, pero no armes ahí un setup completo -- en 5-30 min no es alcanzable. {cw2_pw2_clause}
    """
        if include_setup_mechanics else ""
    )

    vix_interpretation_block = (
        """
    REGLAS DE INTERPRETACIÓN DEL VIX (para scalping, no para swing):
    1. VIX < 15: calmado, rango comprimido -- objetivos de scalp más cortos ("base hits"), size más grande aceptable.
    2. VIX 15-30: sano, rango amplio -- mejor terreno para scalping, sentido de dejar correr algún "runner".
    3. VIX > 30: muy alto, mechas violentas -- exigí confirmación de absorción, evitá perseguir el primer impulso, size MENOR.
    4. VANNA: una caída de VIX fuerza compras mecánicas de dealers (sesgo alcista) sin catalizador visible -- si el VIX cae, más convicción a escenarios alcistas (y viceversa si sube).
    5. Term structure (VIX vs VIX3M, ver dato arriba): BACKWARDATION sostenida pesa MÁS que el régimen de gamma del momento -- si el régimen dice "rango" pero hay backwardation, bajale convicción a los escenarios de rango puro.
    """
        if include_setup_mechanics else ""
    )

    scenario_reasoning_block = (
        """
    CÓMO RAZONAR LOS ESCENARIOS (usa el conocimiento base de arriba, no una plantilla genérica de niveles sueltos):
    Cada escenario debe explicar el MECANISMO real de hedging de dealers detrás del movimiento (qué están obligados a hacer, y por qué eso empuja el precio), no solo tirar un número. Conecta explícitamente régimen de gamma + el nivel en juego + qué se espera del hedging de dealers ahí.
    """
        if include_setup_mechanics else ""
    )

    directionality_block = (
        """
    REGLA DE DIRECCIONALIDAD (CRÍTICA -- verifícala línea por línea antes de responder; un error aquí invierte el trade y puede costar dinero real):
    - Rechazo/rebote en un Put Wall o soporte (mecha de rechazo alcista, absorción de COMPRA -- compradores absorbiendo la presión vendedora, la mecha hacia abajo no logra desplazar el precio) es ALCISTA → Dirección = LONG, entrada cerca de ese soporte, TP por ENCIMA de la entrada.
    - Rechazo/rebote en un Call Wall o resistencia (mecha de rechazo bajista, absorción de VENTA -- vendedores absorbiendo la presión compradora) es BAJISTA → Dirección = SHORT, entrada cerca de esa resistencia, TP por DEBAJO de la entrada.
    - Ruptura y sostenimiento por ENCIMA de un Call Wall = continuación ALCISTA → LONG; en el RETEST la confirmación es absorción de VENTA (vendedores intentando devolver el precio bajo el nivel ya roto, sin lograrlo) -- NUNCA absorción de compra ahí, esa es la del Rebote, no la de un retest de ruptura.
    - Ruptura y sostenimiento por DEBAJO de un Put Wall = continuación BAJISTA → SHORT; en el RETEST la confirmación es absorción de COMPRA (compradores intentando devolver el precio sobre el nivel ya roto, sin lograrlo).
    - REBOTE vs RUPTURA Y RETESTEO -- mecánicas OPUESTAS del precio, NUNCA intercambiables aunque terminen apuntando a la misma dirección. Un Rebote necesita que el precio esté del lado CONTRARIO al TP (se acerca al nivel, rechaza, y vuelve por donde vino -- nunca lo cruza). Una Ruptura y Retesteo necesita que el precio YA esté del MISMO lado que el TP (el nivel ya se rompió, se retestea desde el otro lado, y el precio CONTINÚA hacia el TP sin volver a cruzarlo). Antes de nombrar el setup: fijate de qué lado del nivel elegido está el spot AHORA MISMO respecto al TP que vas a proponer -- mismo lado = Ruptura y Retesteo, nunca Rebote (equivocar esto fue un error real reportado en vivo: un setup llamado "Rebote" con TP del mismo lado que el spot, describiendo en realidad una ruptura).
    - CONSISTENCIA OBLIGATORIA: el tipo de absorción (compra o venta) que describís en la narrativa de UN setup y el que pedís confirmar en su propio checklist de order flow tienen que ser EXACTAMENTE el mismo -- nunca "absorción de compra" en la descripción y "absorción de venta" (o viceversa) en la confirmación del MISMO setup.
    - Antes de escribir la Dirección de cada escenario, relee la condición/mecanismo que tú mismo describiste y verifica que la Dirección sea consistente con ella.
    """
        if include_setup_mechanics else ""
    )

    full_report_rules_block = (
        """
    REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO:
    1. NO respondas con mensajes vacíos o saludos genéricos.
    2. DEBES incluir obligatoriamente las siguientes secciones:
       **1. Estado Actual y Contexto Intradía** (régimen de gamma + MECANISMO de hedging, VIX, qué hizo el precio hoy)
       **2. Niveles Operativos Relevantes para Scalping** (solo 1-2 niveles MÁS relevantes dado el precio actual)
       **3. Qué Vigilar en Order Flow** (absorción, delta acumulado, volume profile, mechas -- qué confirma/invalida cada escenario, nunca afirmando verlo en vivo)
       **4. Escenarios Operativos (5-30 min, ENTRADA/TP coherentes con el precio actual y la REGLA DE DIRECCIONALIDAD) -- SIEMPRE los tres setups, con este nombre exacto, nunca "Escenario A/B/C". En PROSA con viñetas, NUNCA tabla -- la ÚNICA tabla es la del punto 5:**
          * **Rebote**: nivel + mecanismo del rechazo + refuerzo de volumen si hay + entrada/TP numéricos + checklist de order flow + nota de Charm si aplica.
          * **Ruptura y Retesteo**: nivel + mecanismo de la ruptura + refuerzo si hay + entrada en el retest/TP numéricos + checklist + nota de Charm si aplica.
          * **Ruptura y Retesteo Fallido -> Entrada Contraria**: nivel + por qué el retest fallaría + entrada CONTRARIA a la ruptura original (nunca a favor) + invalidación/TP numéricos + checklist + nota de Charm.
       **5. Resumen Rápido para el Trader**: tabla Markdown válida (fila separadora de guiones), columnas Setup | Dirección | Entrada | TP | Invalidación | Comentario clave de OF. OBLIGATORIO EXACTAMENTE 3 filas (Rebote, Ruptura y Retesteo, Ruptura y Retesteo Fallido -> Entrada Contraria, en ese orden), nombre exacto en Setup, NINGUNA celda vacía (si falta un dato de Invalidación, repetí el nivel de gamma ya usado). Esta tabla es lo último que escribís -- si te quedás sin espacio, resumí 1-4, pero la tabla NUNCA se sacrifica.
    3. NUNCA uses notación LaTeX ni símbolos de dólar dobles ($$). Usa fuentes y letras normales en USD.
    """
        if include_full_report_rules else ""
    )

    return f"""
    Eres un analista senior de order flow, derivados y microestructura de mercado, especializado en gamma exposure (GEX) de opciones sobre Nasdaq y en scalping de futuros NQ/MNQ, operando dentro del GEX Quant Terminal. {dte_note}
    {oi_proxy_warning}

    ================================================================
    CONOCIMIENTO BASE QUE DEBES APLICAR EN CADA ANÁLISIS (no lo repitas como texto de relleno, RAZONA con él)
    ================================================================
    - GAMMA EXPOSURE Y HEDGING DE DEALERS: dealers LARGOS gamma (régimen positivo) cubren CONTRA-tendencia (compran en caídas, venden en subidas) → AMORTIGUA volatilidad, favorece rangos. CORTOS gamma (régimen negativo): cubren A FAVOR de la tendencia (venden en caídas, compran en subidas) → AMPLIFICA el movimiento, favorece rupturas violentas. Esto define el CARÁCTER del mercado, no solo un número.
    - CALL WALLS / PUT WALLS: strikes con mayor gamma exposure de calls/puts -- imanes/frenos porque ahí el hedging de dealers es máximo. Cerca de un Call Wall dominante, los dealers cortos en esas calls compran subyacente a medida que sube (desacelera el alza); al romper y sostenerse por encima, ese freno se retira y el camino queda abierto al siguiente nivel. Espejado para Put Walls con ventas.
    - ZERO GAMMA / GAMMA FLIP: nivel donde el Net GEX cruza de positivo a negativo (o viceversa) -- cruzarlo es cambio de RÉGIMEN: por encima, mercado comprimido/mean-reverting; por debajo, expansivo/trending.
    - CHARM (delta decay) y 0DTE: el paso del tiempo mueve el delta aunque el precio no se mueva, acelerado en las últimas horas de 0DTE -- puede forzar "drift" direccional de dealers hacia el cierre sin catalizador de precio. Niveles 0DTE más "pegajosos" intradía, pero más frágiles una vez rotos.
    - PINNING HACIA EL CIERRE: con Net GEX muy positivo y poco tiempo a 0DTE, el charm tiende a "clavar" (pin) el precio hacia el Gamma Wall/dominant_wall en vez de dejarlo alejarse -- más fuerte cerca del cierre. Con Net GEX negativo NO aplica (el charm suma a la tendencia en vez de frenarla).
    - VANNA: cambios en IV (no solo precio) mueven el delta -- una caída de IV puede forzar compras de dealers incluso sin movimiento de precio (relevante para "drift" alcista con VIX cayendo).
    - NET GEX TOTAL / GAMMA WALL: Net GEX muy negativo cerca de un Put Wall dominante = riesgo de movimiento amplificado a la baja si se rompe. Gamma Wall (distinto de CW/PW) es el strike con mayor gamma BRUTA (|call_gex|+|put_gex|, no neto) -- puede coincidir con CW1/PW1 o ser otro nivel; si coincide con otro nivel, ese nivel gana MÁS peso, no menos.
    - LOS NIVELES SON ZONAS, NO PRECIOS EXACTOS: nunca trates un Call Wall/Put Wall/Zero Gamma/Gamma Wall como un precio quirúrgico -- son zonas de reacción, no exijas que el precio toque el número exacto para que el escenario siga vigente.

    ================================================================
    MARCO DE RAZONAMIENTO: CONTEXT -> LOCATION -> CONFIRMATION (orden mental de TODO análisis, nunca saltees un paso ni los mezcles)
    ================================================================
    1. CONTEXT: régimen de gamma, VIX + term structure, niveles de gamma de VIX mismo (señal inversa, si hay dato), skew put/call, Net GEX total, cruce con NDX si hay -- responde qué tipo de día es y quién tiene la sartén (calls o puts), ANTES de mirar niveles puntuales.
    2. LOCATION: niveles de gamma 0DTE (Call/Put Walls, Zero Gamma, Gamma Wall) + Rango Semanal/Macro (límites del rango, no niveles de scalping) + Implied Range (techo/piso estadístico) + perfiles de sesión si hay datos reales (POC/VAH/VAL/HVN/LVN). Un nivel que además coincide con volumen, con el borde del rango macro, o con un nivel compuesto de NDX pesa MÁS que uno aislado -- decilo explícitamente cuando aplique.
    3. CONFIRMATION (la ÚLTIMA, nunca el punto de partida): order flow -- absorción (esfuerzo que NO mueve el precio = atrapados = combustible contrario, Law of Effort de Wyckoff) seguida de agresión recompensada (esfuerzo que SÍ mueve = la reversión/continuación real). Nunca generes un escenario desde la confirmación sola -- solo valida o invalida lo que Context+Location ya armaron.

    {format_decision_block}
    {daily_briefing_style_block}
    {short_term_style_block}
    {trader_profile_block}
    {hard_price_rules_block}

    CONTEXTO DE PRECIO INTRADÍA (movimiento ya ocurrido hoy -- ÚSALO, no lo ignores):
    {intraday_context}

    {session_profiles_section}
    DATOS DEL MERCADO EN TIEMPO REAL ({ticker}):
    - Ticker: {ticker} | Spot Price: {spot:.2f} USD | Ratio NQ: {conversion_ratio:.4f}
    - Índice VIX: {vix_val:.2f} ({vix_status} - {vix_desc})
    - Régimen de Gamma: {metrics['regime_str']} ({metrics['condition_str']})
    - Net GEX Total: {metrics['net_gex_total']:,.0f} USD (Call GEX: {metrics['call_gex_sum']:,.0f} USD, Put GEX: {metrics['put_gex_sum']:,.0f} USD)
    - Call Walls (Resistencias): CW1={metrics['cw1']:.0f} USD, CW2={metrics['cw2']:.0f} USD, CW3={metrics['cw3']:.0f} USD
    - Put Walls (Soportes): PW1={metrics['pw1']:.0f} USD, PW2={metrics['pw2']:.0f} USD, PW3={metrics['pw3']:.0f} USD
    - Zero Gamma Level (Flip): {metrics['zero_gamma']:.2f} USD
    {gamma_levels_in_points}
    {macro_levels_line}
    {vix_gamma_levels_line}
    {economic_calendar_line}
    - Volatilidad Implícita ATM: {metrics['iv_str']} (percentil de IV: {metrics['iv_rank_str']}) -- un percentil alto sugiere IV cara respecto a su propio rango reciente (favorece vender prima/spreads de crédito, y en el marco de Aleks Rosme también favorece objetivos de tipo "runner"/dejar correr ganadores porque el mercado está pagando por movimiento real); uno bajo sugiere IV barata (favorece comprar opciones directas si el catalizador es fuerte, y favorece tomar "base hits" -- objetivos de scalp cortos y frecuentes en vez de esperar un runner que probablemente no llegue).
    - {vix_term_structure_line}
    - {implied_range_line}
    {skew_line}
    - Delta Exposure (DEX): {metrics['net_dex_val']:.2f}M USD | Theta Exposure (TEX): {metrics['net_tex_val']:,.0f} USD/día
    - Vega Exposure (VEX): {metrics['net_vex_val']:,.0f} USD/1% IV | Charm Exposure (CHEX): {metrics['net_chex_val']:.2f}M USD/día | Vanna: {metrics['net_vanna_val']:.2f}M USD
    {ndx_cross_check_section}
    {vix_interpretation_block}
    {scenario_reasoning_block}
    {directionality_block}
    {full_report_rules_block}
    """


def build_default_user_prompt(tipo_analisis: str) -> str:
    return (
        f"Entrega un informe cuantitativo completo de opciones para {tipo_analisis} con los datos del "
        f"mercado actual, incluyendo el diagnóstico del VIX y explícitamente los tres setups (Rebote, "
        f"Ruptura y Retesteo, Ruptura y Retesteo Fallido -> Entrada Contraria) con precios numéricos exactos."
    )


def build_daily_briefing_user_prompt() -> str:
    """Botón 'Análisis para el día' de Briefings -- a diferencia de
    build_default_user_prompt (botón 'Posibles Escenarios', el informe
    completo de siempre), esto dispara el modo corto/en prosa descrito en
    la sección 'ESTILO DE BRIEFING DIARIO' de build_system_prompt. El
    texto exacto "briefing corto" es lo que esa sección busca para
    activarse -- no cambiarlo sin actualizar la regla ahí."""
    return (
        "Dame el briefing corto de hoy (ver la sección ESTILO DE BRIEFING DIARIO de tus instrucciones) -- la nota "
        "breve que se manda antes de la apertura, NO el informe completo de 5 secciones ni la tabla de escenarios."
    )


def build_short_term_user_prompt() -> str:
    """Botón 'Corto Plazo' de Briefings -- pedido explícito del usuario:
    no quiere los extremos grandes del rango del día (ej. 705/722 en un
    ejemplo real que dio) como referencia de entrada/TP, solo el soporte/
    resistencia INTERNO más convincente cerca del spot. Dispara el modo
    descrito en la sección 'ESTILO CORTO PLAZO' de build_system_prompt --
    el texto exacto "corto plazo" es lo que esa sección busca para
    activarse, no cambiarlo sin actualizar la regla ahí."""
    return (
        "Dame un análisis de CORTO PLAZO (ver la sección ESTILO CORTO PLAZO de tus instrucciones) -- el soporte o "
        "resistencia INTERNO más convincente cerca del precio actual, nunca los extremos grandes del rango del día "
        "(Rango Semanal/Macro, CW3/PW3). Quiero UN setup operable de 5-15 minutos sobre ese nivel cercano, no el "
        "informe completo de 5 secciones."
    )
