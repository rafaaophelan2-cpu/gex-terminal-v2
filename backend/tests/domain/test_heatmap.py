from app.domain.heatmap import compute_heatmap_matrix


def test_compute_heatmap_matrix_builds_strike_by_time_grid():
    snapshots = [
        {"time": "09:30", "spot": 100.0, "strikes": [{"strike": 95.0, "net_gex": 1.0}, {"strike": 100.0, "net_gex": 2.0}]},
        {"time": "09:31", "spot": 100.5, "strikes": [{"strike": 100.0, "net_gex": 3.0}]},
    ]
    result = compute_heatmap_matrix(snapshots)

    assert result["times"] == ["09:30", "09:31"]
    assert result["strikes"] == [95.0, 100.0]
    assert result["spot"] == [100.0, 100.5]
    # fila strike=95.0: presente en t0, ausente (0.0) en t1
    assert result["z"][0] == [1.0, 0.0]
    # fila strike=100.0: presente en ambos
    assert result["z"][1] == [2.0, 3.0]


def test_compute_heatmap_matrix_filters_outside_session():
    snapshots = [
        {"time": "05:00", "spot": 100.0, "strikes": [{"strike": 100.0, "net_gex": 1.0}]},
        {"time": "10:00", "spot": 100.0, "strikes": [{"strike": 100.0, "net_gex": 2.0}]},
    ]
    result = compute_heatmap_matrix(snapshots)
    assert result["times"] == ["10:00"]


def test_compute_heatmap_matrix_empty_input():
    result = compute_heatmap_matrix([])
    assert result == {"times": [], "strikes": [], "z": [], "spot": []}
