from app.domain.ai_fallback import generate_local_diagnosis

METRICS = {
    "cw1": 485.0, "cw2": 490.0, "cw3": 495.0, "pw1": 475.0, "pw2": 470.0, "pw3": 465.0,
    "zero_gamma": 478.5, "net_gex_total": -1284000000.0,
    "regime_str": "negative regime", "condition_str": "Negative – dealers short gamma",
    "iv_str": "22.50%", "iv_rank_str": "64th percentile",
}


def test_generate_local_diagnosis_has_all_sections_and_table():
    text = generate_local_diagnosis("QQQ", 481.23, METRICS, vix_val=18.5)
    for heading in ["Estado Actual", "Niveles Operativos", "Order Flow", "Escenarios Operativos", "Resumen Rápido"]:
        assert heading in text
    assert "| Setup | Dirección" in text
    assert "Rebote" in text and "Ruptura y Retesteo" in text
    assert "478.50" in text
    assert "22.50%" in text
    assert "64th percentile" in text
