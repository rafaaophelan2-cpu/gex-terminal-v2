from app.domain.drift import compute_drift_series, compute_volume_premium_drift_series


def test_compute_drift_series_sums_strikes_per_snapshot():
    snapshots = [
        {
            "time": "09:30", "spot": 100.0, "net_gex": -2.0,
            "strikes": [
                {"strike": 95.0, "call_gex": 3.0, "put_gex": -1.0},
                {"strike": 100.0, "call_gex": 1.0, "put_gex": -5.0},
            ],
        },
        {
            "time": "09:31", "spot": 100.5, "net_gex": 4.0,
            "strikes": [
                {"strike": 95.0, "call_gex": 5.0, "put_gex": -1.0},
            ],
        },
    ]
    result = compute_drift_series(snapshots)
    assert result["time"] == ["09:30", "09:31"]
    assert result["spot"] == [100.0, 100.5]
    assert result["call_gex"] == [4.0, 5.0]
    assert result["put_gex"] == [-6.0, -1.0]
    assert result["net_gex"] == [-2.0, 4.0]


def test_compute_drift_series_empty_input():
    result = compute_drift_series([])
    assert result == {"time": [], "spot": [], "call_gex": [], "put_gex": [], "net_gex": []}


def test_compute_drift_series_missing_strikes_defaults_to_zero():
    snapshots = [{"time": "09:30", "spot": 100.0}]
    result = compute_drift_series(snapshots)
    assert result["call_gex"] == [0.0]
    assert result["put_gex"] == [0.0]
    assert result["net_gex"] == [0.0]


def test_compute_drift_series_otm_only_filters_against_snapshot_spot():
    # Réplica del toggle "OTM" de Aleks Rosme: con spot=100, la call de
    # strike 95 (ITM) debe descartarse y la de 105 (OTM) sumarse; espejado
    # para puts (95 OTM se suma, 105 ITM se descarta).
    snapshots = [
        {
            "time": "09:30", "spot": 100.0,
            "strikes": [
                {"strike": 95.0, "call_gex": 3.0, "put_gex": -1.0},   # call ITM, put OTM
                {"strike": 105.0, "call_gex": 2.0, "put_gex": -7.0},  # call OTM, put ITM
            ],
        },
    ]
    result = compute_drift_series(snapshots, otm_only=True)
    assert result["call_gex"] == [2.0]   # solo la call de 105 (strike >= spot)
    assert result["put_gex"] == [-1.0]   # solo la put de 95 (strike <= spot)
    assert result["net_gex"] == [1.0]


def test_compute_drift_series_otm_only_uses_each_snapshots_own_spot():
    # El filtro debe usar el spot DE CADA instante, no el spot actual --
    # acá el spot sube de 100 a 106 entre snapshots, así que 105 pasa de
    # ser "call OTM" a "call ITM" (descartada) en el segundo instante.
    snapshots = [
        {"time": "09:30", "spot": 100.0, "strikes": [{"strike": 105.0, "call_gex": 2.0, "put_gex": 0.0}]},
        {"time": "09:31", "spot": 106.0, "strikes": [{"strike": 105.0, "call_gex": 2.0, "put_gex": 0.0}]},
    ]
    result = compute_drift_series(snapshots, otm_only=True)
    assert result["call_gex"] == [2.0, 0.0]


def test_compute_drift_series_default_still_sums_all_strikes():
    # otm_only por defecto es False -- el comportamiento existente
    # (usado por el resto de la app hasta ahora) no debe cambiar.
    snapshots = [
        {
            "time": "09:30", "spot": 100.0,
            "strikes": [
                {"strike": 95.0, "call_gex": 3.0, "put_gex": -1.0},
                {"strike": 105.0, "call_gex": 2.0, "put_gex": -7.0},
            ],
        },
    ]
    result = compute_drift_series(snapshots)
    assert result["call_gex"] == [5.0]
    assert result["put_gex"] == [-8.0]


def _vol_snap(time, spot, strikes):
    return {"time": time, "spot": spot, "strikes": strikes}


def test_volume_premium_drift_needs_two_snapshots_to_produce_a_point():
    # El primer snapshot del dia no tiene un anterior con el que sacar un
    # delta de volumen -- la serie arranca recien en el segundo punto.
    snapshots = [
        _vol_snap("09:30", 100.0, [{"strike": 100.0, "volume_c": 1000, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
    ]
    result = compute_volume_premium_drift_series(snapshots)
    assert result == {"time": [], "spot": [], "call_gex": [], "put_gex": [], "net_gex": []}


def test_volume_premium_drift_computes_delta_times_mark():
    snapshots = [
        _vol_snap("09:30", 100.0, [{"strike": 100.0, "volume_c": 1000, "volume_p": 500, "mark_c": 1.0, "mark_p": 2.0}]),
        _vol_snap("09:31", 100.5, [{"strike": 100.0, "volume_c": 1200, "volume_p": 550, "mark_c": 1.5, "mark_p": 2.5}]),
    ]
    result = compute_volume_premium_drift_series(snapshots)
    # 200 contratos nuevos de calls * 1.5 mark * 100 = 30000
    # 50 contratos nuevos de puts * 2.5 mark * 100 = 12500
    assert result["time"] == ["09:31"]
    assert result["spot"] == [100.5]
    assert result["call_gex"] == [30000.0]
    assert result["put_gex"] == [-12500.0]
    assert result["net_gex"] == [30000.0 - 12500.0]


def test_volume_premium_drift_accumulates_across_multiple_intervals():
    snapshots = [
        _vol_snap("09:30", 100.0, [{"strike": 100.0, "volume_c": 1000, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
        _vol_snap("09:31", 100.0, [{"strike": 100.0, "volume_c": 1100, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
        _vol_snap("09:32", 100.0, [{"strike": 100.0, "volume_c": 1300, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
    ]
    result = compute_volume_premium_drift_series(snapshots)
    # 100 contratos, despues 200 mas -- acumulado: 100, 300 (*1.0*100 cada uno)
    assert result["call_gex"] == [10000.0, 30000.0]
    assert result["put_gex"] == [0.0, 0.0]


def test_volume_premium_drift_ignores_volume_decrease_between_polls():
    # Un volumen que BAJA (ej. reset/rollover del contador de Schwab) no
    # debe restarse del acumulado -- se descarta ese punto, igual que el
    # prototipo probado en vivo.
    snapshots = [
        _vol_snap("09:30", 100.0, [{"strike": 100.0, "volume_c": 1000, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
        _vol_snap("09:31", 100.0, [{"strike": 100.0, "volume_c": 900, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
    ]
    result = compute_volume_premium_drift_series(snapshots)
    assert result["call_gex"] == [0.0]


def test_volume_premium_drift_skips_strikes_missing_required_fields():
    # Snapshots viejos (sin volume_c/mark_c) no deben romper el calculo --
    # simplemente no aportan a ningun delta.
    snapshots = [
        _vol_snap("09:30", 100.0, [{"strike": 100.0, "call_gex": 1.0, "put_gex": -1.0}]),
        _vol_snap("09:31", 100.0, [{"strike": 100.0, "volume_c": 1100, "volume_p": 500, "mark_c": 1.0, "mark_p": 1.0}]),
    ]
    result = compute_volume_premium_drift_series(snapshots)
    assert result["time"] == ["09:31"]
    assert result["call_gex"] == [0.0]  # strike 100 no tenia par en el snapshot anterior con esos campos


def test_volume_premium_drift_otm_only_filters_against_snapshot_spot():
    snapshots = [
        _vol_snap("09:30", 100.0, [
            {"strike": 95.0, "volume_c": 0, "volume_p": 0, "mark_c": 1.0, "mark_p": 1.0},
            {"strike": 105.0, "volume_c": 0, "volume_p": 0, "mark_c": 1.0, "mark_p": 1.0},
        ]),
        _vol_snap("09:31", 100.0, [
            {"strike": 95.0, "volume_c": 100, "volume_p": 100, "mark_c": 1.0, "mark_p": 1.0},  # call ITM, put OTM
            {"strike": 105.0, "volume_c": 100, "volume_p": 100, "mark_c": 1.0, "mark_p": 1.0},  # call OTM, put ITM
        ]),
    ]
    result = compute_volume_premium_drift_series(snapshots, otm_only=True)
    # Solo la call de 105 (OTM) y la put de 95 (OTM) cuentan.
    assert result["call_gex"] == [100 * 1.0 * 100.0]
    assert result["put_gex"] == [-(100 * 1.0 * 100.0)]
