from app.domain.parsing import parse_schwab_chain

SAMPLE_CHAIN = {
    "callExpDateMap": {
        "2026-09-10:0": {
            "95.0": [{"openInterest": 100, "gamma": 0.05, "delta": 0.80, "theta": -0.10, "vega": 0.20, "volatility": 22.0}],
            "100.0": [{"openInterest": 500, "gamma": 0.09, "delta": 0.50, "theta": -0.20, "vega": 0.30, "volatility": 20.0}],
            "105.0": [{"openInterest": 50, "gamma": 0.04, "delta": 0.20, "theta": -0.08, "vega": 0.15, "volatility": 24.0}],
        }
    },
    "putExpDateMap": {
        "2026-09-10:0": {
            "95.0": [{"openInterest": 50, "gamma": 0.05, "delta": -0.20, "theta": -0.09, "vega": 0.18, "volatility": 22.0}],
            "100.0": [{"openInterest": 300, "gamma": 0.09, "delta": -0.50, "theta": -0.19, "vega": 0.29, "volatility": 20.0}],
            "105.0": [{"openInterest": 100, "gamma": 0.04, "delta": -0.80, "theta": -0.07, "vega": 0.14, "volatility": 24.0}],
        }
    },
}


def test_parse_schwab_chain_shape():
    df, exp_key = parse_schwab_chain(SAMPLE_CHAIN)
    assert exp_key == "2026-09-10:0"
    assert len(df) == 3
    assert set(df['strike']) == {95.0, 100.0, 105.0}
    assert (df['dte'] == 0).all()


def test_parse_schwab_chain_open_interest_split():
    df, _ = parse_schwab_chain(SAMPLE_CHAIN)
    row100 = df[df['strike'] == 100.0].iloc[0]
    assert row100['openInterest_c'] == 500
    assert row100['openInterest_p'] == 300


def test_parse_schwab_chain_iv_percent_normalized():
    # volatility=20.0 llega como porcentaje (Schwab) -> se normaliza a 0.20
    df, _ = parse_schwab_chain(SAMPLE_CHAIN)
    row100 = df[df['strike'] == 100.0].iloc[0]
    assert abs(row100['iv_c'] - 0.20) < 1e-9
    assert abs(row100['iv_p'] - 0.20) < 1e-9


def test_parse_schwab_chain_put_delta_is_negative():
    df, _ = parse_schwab_chain(SAMPLE_CHAIN)
    row100 = df[df['strike'] == 100.0].iloc[0]
    assert row100['delta_c'] > 0
    assert row100['delta_p'] < 0


def test_parse_schwab_chain_empty_input():
    df, exp_key = parse_schwab_chain({})
    assert df.empty
    assert exp_key is None

    df2, exp_key2 = parse_schwab_chain(None)
    assert df2.empty
    assert exp_key2 is None
