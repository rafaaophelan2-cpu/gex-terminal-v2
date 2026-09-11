from app.domain.ai_prompt import build_intraday_context, build_system_prompt, classify_vix

METRICS = {
    "cw1": 485.0, "cw2": 490.0, "cw3": 495.0, "pw1": 475.0, "pw2": 470.0, "pw3": 465.0,
    "zero_gamma": 478.5, "net_gex_total": -1284000000.0, "call_gex_sum": 400000.0, "put_gex_sum": -1600000.0,
    "net_dex_val": 152300.0, "net_tex_val": -88400.0, "net_vex_val": 231000.0,
    "net_chex_val": -1200.0, "net_vanna_val": 8700.0,
    "regime_str": "negative regime", "condition_str": "Negative – dealers short gamma",
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
    assert "Escenario A" in prompt and "Escenario B" in prompt and "Escenario C" in prompt
    # La única aparición de "$$" debe ser la propia regla que la prohíbe.
    assert prompt.count("$$") == 1


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
