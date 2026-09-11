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
