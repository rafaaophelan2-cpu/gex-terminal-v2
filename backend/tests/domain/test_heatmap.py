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
    # El blur gaussiano (BLUR_SIGMA) suaviza los valores exactos, pero la
    # forma de la matriz y el orden de magnitud relativo se mantienen: la
    # fila strike=100.0 (presente en ambos instantes, valores 2 y 3) debe
    # seguir siendo mayor que la fila strike=95.0 (presente solo en t0).
    assert len(result["z"]) == 2
    assert len(result["z"][0]) == 2
    assert sum(result["z"][1]) > sum(result["z"][0])


def test_compute_heatmap_matrix_blur_keeps_all_zero_at_zero():
    # Sanity check del blur: una grilla toda en cero sigue toda en cero
    # (nada que "inventar" desde el suavizado).
    snapshots = [
        {"time": "09:30", "spot": 100.0, "strikes": [{"strike": 95.0, "net_gex": 0.0}, {"strike": 100.0, "net_gex": 0.0}]},
        {"time": "09:31", "spot": 100.0, "strikes": [{"strike": 95.0, "net_gex": 0.0}, {"strike": 100.0, "net_gex": 0.0}]},
    ]
    result = compute_heatmap_matrix(snapshots)
    assert all(v == 0.0 for row in result["z"] for v in row)


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
