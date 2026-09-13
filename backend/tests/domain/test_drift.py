from app.domain.drift import compute_drift_series


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
