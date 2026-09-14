from app.domain.ai_prompt import (
    build_daily_briefing_user_prompt,
    build_default_user_prompt,
    build_intraday_context,
    build_system_prompt,
    classify_vix,
    format_economic_calendar,
    format_implied_range,
    format_vix_term_structure,
)

METRICS = {
    "cw1": 485.0, "cw2": 490.0, "cw3": 495.0, "pw1": 475.0, "pw2": 470.0, "pw3": 465.0,
    "zero_gamma": 478.5, "net_gex_total": -1284000000.0, "call_gex_sum": 400000.0, "put_gex_sum": -1600000.0,
    "net_dex_val": 152300.0, "net_tex_val": -88400.0, "net_vex_val": 231000.0,
    "net_chex_val": -1200.0, "net_vanna_val": 8700.0,
    "regime_str": "negative regime", "condition_str": "Negative – dealers short gamma",
    "iv_str": "22.50%", "iv_rank_str": "64th percentile",
}


def test_build_intraday_context_empty_candles():
    assert "Sin datos" in build_intraday_context([], 480.0)


def test_build_intraday_context_describes_range_and_move():
    candles = [
        {"time": "09:30", "open": 478.0, "high": 479.0, "low": 477.5, "close": 478.5},
        {"time": "09:31", "open": 478.5, "high": 481.0, "low": 478.0, "close": 480.5},
    ]
    ctx = build_intraday_context(candles, 481.0)
    assert "Apertura de hoy: 478.00" in ctx
    assert "Máximo del día: 481.00" in ctx
    assert "Mínimo del día: 477.50" in ctx
    assert "al alza" in ctx


def test_classify_vix_buckets():
    assert classify_vix(12.0)[0] == "Baja Volatilidad"
    assert classify_vix(20.0)[0] == "Volatilidad Media"
    assert classify_vix(28.0)[0] == "Volatilidad Alta"
    assert classify_vix(35.0)[0] == "Muy Alta Volatilidad"


def test_build_system_prompt_embeds_key_numbers():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "481.23" in prompt
    assert "478.50" in prompt
    assert "contexto de prueba" in prompt
    assert "Rebote" in prompt and "Ruptura y Retesteo" in prompt and "Entrada Contraria" in prompt
    # La única aparición de "$$" debe ser la propia regla que la prohíbe.
    assert prompt.count("$$") == 1
    assert "22.50%" in prompt
    assert "64th percentile" in prompt


def test_build_system_prompt_includes_gamma_mechanics_and_conversational_mode():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    # Conocimiento base de mecánica de gamma/hedging de dealers.
    assert "GAMMA EXPOSURE" in prompt
    assert "ZERO GAMMA" in prompt or "GAMMA FLIP" in prompt
    assert "CHARM" in prompt
    assert "VANNA" in prompt
    # No debe forzar el informe completo ante un saludo/conversación.
    assert "conversacional" in prompt.lower()
    # Order flow: debe aclarar que no hay datos en vivo, y pedir un
    # checklist de confirmación, no afirmar que "ve" absorción.
    assert "checklist" in prompt.lower()
    assert "PROHIBIDO" in prompt


def test_build_system_prompt_without_session_profiles_keeps_no_data_disclaimer():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "NO tienes esos datos en vivo" in prompt
    # La sección de perfiles (con los datos en sí) no debe armarse sin
    # datos -- el trader profile SÍ puede mencionar "PERFILES DE SESIÓN"
    # como referencia general, por eso se busca el encabezado completo de
    # la sección, no el substring suelto.
    assert "PERFILES DE SESIÓN -- VOLUME/DELTA/TPO PROFILE" not in prompt


def test_build_system_prompt_with_session_profiles_includes_real_levels():
    overnight = {
        "poc": 20100.0, "vah": 20150.0, "val": 20050.0,
        "hvn": [20100.0], "lvn": [20075.0],
        "delta_outliers": [{"price": 20080.0, "delta": 1250.0}],
        "tpo_poc": 20105.0, "tpo_lvn": [20060.0],
    }
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        overnight_profile=overnight, cash_profile=None,
    )
    assert "PERFILES DE SESIÓN" in prompt
    assert "20100.00" in prompt  # POC del overnight
    assert "tienes acceso a datos reales" in prompt.lower()
    # El disclaimer de "NO tienes esos datos" ya no debe aparecer tal cual
    # cuando SÍ hay perfiles -- solo el matiz sobre el footprint en vivo.
    assert "NO tienes esos datos en vivo todavía" not in prompt


def test_format_vix_term_structure_contango():
    text = format_vix_term_structure({"vix": 15.0, "vix3m": 18.0, "state": "contango"})
    assert "Contango" in text
    assert "15.00" in text and "18.00" in text


def test_format_vix_term_structure_backwardation():
    text = format_vix_term_structure({"vix": 22.0, "vix3m": 19.0, "state": "backwardation"})
    assert "BACKWARDATION" in text
    assert "estrés" in text.lower()


def test_format_vix_term_structure_missing_data():
    assert "sin dato" in format_vix_term_structure(None).lower()
    assert "sin dato" in format_vix_term_structure({}).lower()


def test_format_implied_range_with_data():
    text = format_implied_range(
        {"expected_move": 5.0, "one_sd": {"low": 475.0, "high": 485.0}, "two_sd": {"low": 470.0, "high": 490.0}},
        ticker="QQQ",
    )
    assert "475.00" in text and "485.00" in text
    assert "470.00" in text and "490.00" in text


def test_format_implied_range_missing_data():
    assert "sin dato" in format_implied_range(None, ticker="QQQ").lower()


def test_build_system_prompt_includes_clc_framework():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "CONTEXT" in prompt and "LOCATION" in prompt and "CONFIRMATION" in prompt
    assert "Law of Effort" in prompt
    assert "ZONAS" in prompt


def test_build_system_prompt_includes_gamma_wall_when_present():
    metrics_with_wall = {**METRICS, "dominant_wall": 483.0}
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=metrics_with_wall, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "Gamma Wall=" in prompt


def test_build_system_prompt_includes_ndx_cross_check_and_implied_range():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        vix_term_structure={"vix": 15.0, "vix3m": 18.0, "state": "contango"},
        implied_range={"expected_move": 5.0, "one_sd": {"low": 475.0, "high": 485.0}, "two_sd": {"low": 470.0, "high": 490.0}},
        ndx_cross_check="CRUCE CON NDX (niveles compuestos): texto de prueba de cruce.",
    )
    assert "Contango" in prompt
    assert "475.00" in prompt
    assert "CRUCE CON NDX" in prompt


def test_build_system_prompt_includes_macro_levels_when_present():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        macro_levels={"cw1": 500.0, "cw2": 505.0, "cw3": 510.0, "pw1": 460.0, "pw2": 455.0, "pw3": 450.0, "zero_gamma": 478.0},
    )
    assert "Rango Semanal/Macro" in prompt
    assert "Call Resistance=500.00" in prompt
    assert "Put Support=460.00" in prompt


def test_build_system_prompt_omits_macro_levels_line_when_empty():
    # "Rango Semanal/Macro" aparece igual en la descripción fija del marco
    # CONTEXT->LOCATION->CONFIRMATION -- lo que NO debe aparecer sin datos
    # es la línea formateada con los números reales.
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        macro_levels={},
    )
    assert "Call Resistance=" not in prompt


def test_build_system_prompt_includes_vix_gamma_levels_as_inverse_signal():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        vix_gamma_levels={"cw1": 20.0, "pw1": 15.0, "zero_gamma": 17.5, "vix_spot": 16.8},
    )
    assert "Niveles de Gamma de VIX" in prompt
    assert "correlación NEGATIVA" in prompt
    assert "VIX Call Wall=20.00" in prompt


def test_build_system_prompt_includes_pinning_mechanics():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "PINNING HACIA EL CIERRE" in prompt
    assert "dominant_wall" in prompt or "Gamma Wall/strike de mayor open interest" in prompt


def test_build_system_prompt_includes_economic_calendar_events():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        economic_calendar=[
            {"date": "2026-09-13", "time": "08:30", "event": "CPI m/m", "impact": "high", "actual": None, "forecast": "0.3%", "previous": "0.2%"},
        ],
    )
    assert "Calendario económico de esta semana" in prompt
    assert "CPI m/m" in prompt
    assert "impacto ALTO" in prompt


def test_build_system_prompt_omits_economic_calendar_line_when_empty():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        economic_calendar=[],
    )
    assert "sin eventos de impacto medio/alto en EE.UU." in prompt


def test_format_economic_calendar_with_events_groups_by_day_and_precomputes_days_until():
    text = format_economic_calendar(
        [
            {"date": "2026-09-13", "time": "08:30", "event": "CPI m/m", "impact": "high", "actual": None, "forecast": "0.3%", "previous": "0.2%"},
            {"date": "2026-09-13", "time": "10:00", "event": "ISM Services PMI", "impact": "medium", "actual": "54.2", "forecast": "54.1", "previous": "54.0"},
            {"date": "2026-09-16", "time": "14:00", "event": "FOMC Rate Decision", "impact": "high", "actual": None, "forecast": None, "previous": None},
        ],
        today_str="2026-09-13",
    )
    assert "HOY (2026-09-13):" in text
    assert "08:30 NY -- CPI m/m [impacto ALTO]" in text
    assert "esperado=0.3%" in text
    assert "10:00 NY -- ISM Services PMI [impacto medio]" in text
    assert "real=54.2" in text
    # El evento futuro trae los días ya calculados EN PYTHON, no se le
    # pide al modelo que reste fechas (mismo motivo que el resto de la
    # aritmética de este prompt).
    assert "en 3 días (2026-09-16):" in text
    assert "FOMC Rate Decision" in text


def test_format_economic_calendar_excludes_low_impact_to_save_tokens():
    # Pedido de presupuesto de tokens (ver ai_prompt.py): 'low' se filtra
    # SOLO acá (la pestaña News sigue mostrando los 3 niveles, ver
    # test_forexfactory_client.py) -- Groq cuenta prompt+max_tokens contra
    # el límite de TPM de la cuenta, confirmado en vivo que una semana con
    # muchos eventos de bajo impacto hacía superar ese límite en cada
    # pedido.
    text = format_economic_calendar(
        [
            {"date": "2026-09-13", "time": "09:00", "event": "Minor Data", "impact": "low", "actual": None, "forecast": None, "previous": None},
            {"date": "2026-09-13", "time": "10:00", "event": "ISM Services PMI", "impact": "medium", "actual": None, "forecast": None, "previous": None},
        ],
        today_str="2026-09-13",
    )
    assert "Minor Data" not in text
    assert "ISM Services PMI" in text


def test_format_economic_calendar_only_low_impact_events_reads_as_no_relevant_events():
    text = format_economic_calendar(
        [{"date": "2026-09-13", "time": "09:00", "event": "Minor Data", "impact": "low", "actual": None, "forecast": None, "previous": None}],
        today_str="2026-09-13",
    )
    assert "sin eventos de impacto medio/alto" in text


def test_format_economic_calendar_empty_is_normal_not_an_error():
    text = format_economic_calendar(None)
    assert "sin eventos de impacto medio/alto en EE.UU." in text
    assert format_economic_calendar([]) == text


def test_build_system_prompt_skew_high_note():
    metrics_with_skew = {**METRICS, "skew": 0.05}
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=metrics_with_skew, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "Skew Put/Call" in prompt
    assert "miedo de caída ya construido" in prompt


def test_build_system_prompt_skew_omitted_when_none():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "Skew Put/Call" not in prompt


def test_build_daily_briefing_user_prompt_requests_short_mode():
    prompt = build_daily_briefing_user_prompt()
    assert "briefing corto" in prompt
    assert "informe completo" in prompt


def test_build_default_user_prompt_requests_full_report_with_three_setups():
    prompt = build_default_user_prompt("Posibles Escenarios")
    assert "Posibles Escenarios" in prompt
    assert "Rebote" in prompt
    assert "Ruptura y Retesteo Fallido" in prompt


def test_build_system_prompt_includes_daily_briefing_style_section():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "ESTILO DE BRIEFING DIARIO" in prompt
    assert "Pivot Point" in prompt


def test_build_system_prompt_warns_when_oi_is_volume_proxy():
    prompt = build_system_prompt(
        ticker="NDX", spot=29368.44, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        oi_is_volume_proxy=True,
    )
    assert "ADVERTENCIA DE CALIDAD DE DATO" in prompt
    assert "VOLUMEN DEL" in prompt


def test_build_system_prompt_no_warning_when_oi_is_real():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
        oi_is_volume_proxy=False,
    )
    assert "ADVERTENCIA DE CALIDAD DE DATO" not in prompt


# response_mode gatea qué secciones de estilo/reglas se arman -- ver
# docstring de build_system_prompt. El motivo es de presupuesto: el
# prompt base (chat, todas las secciones) mide ~20.700 caracteres antes
# de sumar ningún dato de mercado real, ya cerca del límite de 8000
# Tokens Por Minuto de la cuenta de Groq -- cada botón de Briefings YA
# sabe qué formato quiere, así que no hace falta mandarle a Groq las
# instrucciones de LOS OTROS DOS formatos.
def test_build_system_prompt_default_mode_is_chat_and_includes_everything():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    assert "CÓMO DECIDIR EL FORMATO" in prompt
    assert "ESTILO DE BRIEFING DIARIO" in prompt
    assert "ESTILO CORTO PLAZO" in prompt
    assert "REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO" in prompt


def test_build_system_prompt_daily_briefing_mode_omits_other_formats():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba", response_mode="daily_briefing",
    )
    assert "ESTILO DE BRIEFING DIARIO" in prompt
    assert "Pivot Point" in prompt
    assert "ESTILO CORTO PLAZO" not in prompt
    assert "REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO" not in prompt
    assert "CÓMO DECIDIR EL FORMATO" not in prompt
    # Sin setups numéricos en este modo -- no hace falta la mecánica de
    # los 3 setups ni las reglas duras de coherencia de precios.
    assert "PERFIL DEL TRADER" not in prompt
    assert "REGLA DE DIRECCIONALIDAD" not in prompt


def test_build_system_prompt_short_term_mode_omits_other_formats():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba", response_mode="short_term",
    )
    assert "ESTILO CORTO PLAZO" in prompt
    assert "extremos grandes del rango del día" in prompt
    assert "ESTILO DE BRIEFING DIARIO" not in prompt
    assert "REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO" not in prompt
    assert "CÓMO DECIDIR EL FORMATO" not in prompt
    # Este modo SÍ propone un setup con entrada/TP -- necesita la mecánica
    # de los 3 setups y las reglas duras de coherencia de precios.
    assert "PERFIL DEL TRADER" in prompt
    assert "REGLA DE DIRECCIONALIDAD" in prompt


def test_build_system_prompt_full_mode_omits_short_and_daily_styles():
    prompt = build_system_prompt(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba", response_mode="full",
    )
    assert "REGLAS DE RESPUESTA CUANDO SÍ CORRESPONDE EL ANÁLISIS COMPLETO" in prompt
    assert "PERFIL DEL TRADER" in prompt
    assert "REGLA DE DIRECCIONALIDAD" in prompt
    assert "ESTILO DE BRIEFING DIARIO" not in prompt
    assert "ESTILO CORTO PLAZO" not in prompt
    assert "CÓMO DECIDIR EL FORMATO" not in prompt


def test_build_system_prompt_mode_gating_shrinks_the_static_baseline():
    # El hallazgo original: el prompt base (modo "chat", sin datos de
    # mercado reales) medía ~27.500 caracteres -- ya por encima del
    # límite de 8000 TPM de Groq por sí solo. Cada modo de botón debe
    # quedar sustancialmente más chico que el modo "chat" sin recortar,
    # o el gateo por modo no está cumpliendo su propósito.
    kwargs = dict(
        ticker="QQQ", spot=481.23, metrics=METRICS, vix_val=18.5,
        intraday_context="contexto de prueba",
    )
    chat_len = len(build_system_prompt(**kwargs, response_mode="chat"))
    for mode in ("full", "daily_briefing", "short_term"):
        mode_len = len(build_system_prompt(**kwargs, response_mode=mode))
        assert mode_len < chat_len
    # El briefing diario (2-4 frases de prosa, sin setups) es el más
    # liviano de los tres por un margen amplio.
    daily_len = len(build_system_prompt(**kwargs, response_mode="daily_briefing"))
    full_len = len(build_system_prompt(**kwargs, response_mode="full"))
    assert daily_len < full_len
