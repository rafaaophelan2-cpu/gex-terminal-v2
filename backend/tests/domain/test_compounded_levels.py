from app.domain.compounded_levels import find_compounded_levels, translate_level


def test_translate_level_basic():
    # NDX a 29000, QQQ a 700 -- ratio ~41.43. Un nivel de NDX en 29350
    # debería traducirse a algo cerca de 708.4 en escala QQQ.
    ratio = 29000.0 / 700.0
    assert round(translate_level(29350.0, ratio), 1) == round(29350.0 / ratio, 1)


def test_translate_level_zero_ratio_returns_value_unchanged():
    assert translate_level(100.0, 0.0) == 100.0


def test_find_compounded_levels_detects_match_within_tolerance():
    primary_spot = 700.0
    ratio = 29000.0 / primary_spot  # ndx_spot / qqq_spot
    # Call Wall 1 de QQQ en 710, y el Call Wall 1 de NDX traducido cae
    # justo ahí (710 * ratio = 29414.28...) -- debe detectarse.
    primary_levels = {"Call Wall 1": 710.0, "Put Wall 1": 690.0}
    secondary_levels = {"Call Wall 1 NDX": 710.0 * ratio, "Put Wall 1 NDX": 500.0}

    matches = find_compounded_levels(primary_levels, secondary_levels, ratio, primary_spot)

    assert len(matches) == 1
    assert matches[0].primary_name == "Call Wall 1"
    assert matches[0].secondary_name == "Call Wall 1 NDX"
    assert round(matches[0].secondary_value_translated, 1) == 710.0


def test_find_compounded_levels_no_match_outside_tolerance():
    primary_spot = 700.0
    ratio = 29000.0 / primary_spot
    primary_levels = {"Call Wall 1": 710.0}
    secondary_levels = {"Call Wall 1 NDX": 750.0 * ratio}  # muy lejos de 710

    assert find_compounded_levels(primary_levels, secondary_levels, ratio, primary_spot) == []


def test_find_compounded_levels_ignores_none_values():
    assert find_compounded_levels({"cw1": None}, {"cw1_ndx": None}, ratio=41.0, primary_spot=700.0) == []


def test_find_compounded_levels_merges_primary_levels_sharing_the_same_value():
    # Reportado en vivo: Zero Gamma y Gamma Wall cayendo en el mismo
    # precio hacían que CADA nivel NDX coincidente saliera duplicado, una
    # fila por cada nombre primario. Con el mismo valor deben combinarse
    # en una sola fila "Zero Gamma / Gamma Wall", no dos filas idénticas.
    primary_spot = 700.0
    ratio = 29000.0 / primary_spot
    primary_levels = {"Zero Gamma": 710.0, "Gamma Wall": 710.0, "Call Wall 1": 690.0}
    secondary_levels = {"Call Wall 1 NDX": 710.0 * ratio}

    matches = find_compounded_levels(primary_levels, secondary_levels, ratio, primary_spot)

    assert len(matches) == 1
    assert matches[0].primary_name == "Zero Gamma / Gamma Wall"
    assert matches[0].primary_value == 710.0


def test_find_compounded_levels_invalid_ratio_or_spot():
    assert find_compounded_levels({"cw1": 700.0}, {"cw1_ndx": 700.0}, ratio=0.0, primary_spot=700.0) == []
    assert find_compounded_levels({"cw1": 700.0}, {"cw1_ndx": 700.0}, ratio=41.0, primary_spot=0.0) == []
