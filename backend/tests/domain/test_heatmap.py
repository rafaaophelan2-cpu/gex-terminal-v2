from app.domain.heatmap import BAND_HALF_WIDTH, compute_heatmap_matrix


def test_compute_heatmap_matrix_builds_narrow_separated_bands():
    # Strikes lejos entre sí (95 y 100, separación 5 >> 2*BAND_HALF_WIDTH)
    # deben quedar como dos bandas angostas con una franja vacía (todo
    # cero) entre ambas -- no una fila continua que ocupe todo el rango.
    snapshots = [
        {"time": "09:30", "spot": 100.0, "strikes": [{"strike": 95.0, "net_gex": 1.0}, {"strike": 100.0, "net_gex": 2.0}]},
        {"time": "09:31", "spot": 100.5, "strikes": [{"strike": 95.0, "net_gex": 1.5}, {"strike": 100.0, "net_gex": 3.0}]},
    ]
    result = compute_heatmap_matrix(snapshots)

    assert result["times"] == ["09:30", "09:31"]
    assert result["spot"] == [100.0, 100.5]
    assert len(result["z"]) == len(result["strikes"])
    assert all(len(row) == 2 for row in result["z"])

    # Cada punto del eje Y debe caer dentro de la banda de ALGÚN strike
    # real, o quedar fuera del rango de ambas bandas -- no debe haber
    # ningún punto "a medio camino" entre 95 y 100 con valor real.
    for y, row in zip(result["strikes"], result["z"]):
        near_95 = abs(y - 95.0) <= BAND_HALF_WIDTH + 1e-6
        near_100 = abs(y - 100.0) <= BAND_HALF_WIDTH + 1e-6
        if not near_95 and not near_100:
            assert all(v == 0.0 for v in row), f"y={y} fuera de cualquier banda debería ser 0"

    # Debe existir al menos un punto en la franja vacía entre ambas bandas.
    gap_points = [y for y in result["strikes"] if 95.0 + BAND_HALF_WIDTH < y < 100.0 - BAND_HALF_WIDTH]
    assert gap_points, "debería haber puntos en la franja vacía entre las dos bandas"


def test_compute_heatmap_matrix_all_zero_stays_zero():
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
