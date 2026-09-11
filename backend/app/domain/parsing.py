import pandas as pd


def _extract_iv(opt_dict: dict) -> float:
    vol = float(opt_dict.get('volatility', opt_dict.get('impliedVolatility', 0.0)))
    if vol > 2.0:
        vol = vol / 100.0
    return max(vol, 0.001)


def _clean_greek(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        if v != v or v in (float('inf'), float('-inf')) or v <= -500.0 or v >= 500.0:
            return default
        return v
    except (ValueError, TypeError):
        return default


def parse_schwab_chain(chain_data: dict) -> tuple[pd.DataFrame, str | None]:
    """Parsea el JSON crudo de un option chain de Schwab (callExpDateMap/
    putExpDateMap) a un DataFrame por strike/expiración. Port directo de
    parse_schwab_chain en app.py (líneas ~1011-1094), sin dependencias de
    Streamlit."""
    if not isinstance(chain_data, dict):
        return pd.DataFrame(), None

    call_map = chain_data.get('callExpDateMap') or {}
    put_map = chain_data.get('putExpDateMap') or {}

    all_exp_keys = sorted(set(list(call_map.keys()) + list(put_map.keys())))
    if not all_exp_keys:
        return pd.DataFrame(), None

    selected_exp = all_exp_keys[0]
    all_records = []

    for exp_key in all_exp_keys:
        parts = exp_key.split(':')
        exp_date_str = parts[0] if len(parts) > 0 else exp_key
        try:
            dte_val = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            dte_val = 0

        calls_for_exp = call_map.get(exp_key) or {}
        puts_for_exp = put_map.get(exp_key) or {}
        records: dict[float, dict] = {}

        def _ensure_record(strike: float) -> dict:
            if strike not in records:
                records[strike] = {
                    'strike': strike, 'exp_key': exp_key, 'exp_date': exp_date_str, 'dte': dte_val,
                    'openInterest_c': 0, 'openInterest_p': 0,
                    'gamma_c': 0.0, 'gamma_p': 0.0, 'delta_c': 0.0, 'delta_p': 0.0,
                    'theta_c': 0.0, 'theta_p': 0.0, 'vega_c': 0.0, 'vega_p': 0.0,
                    'vanna_c': 0.0, 'vanna_p': 0.0, 'iv_c': 0.0, 'iv_p': 0.0,
                    'volume_c': 0, 'volume_p': 0,
                }
            return records[strike]

        for strike_str, opt_list in calls_for_exp.items():
            if not opt_list:
                continue
            opt = opt_list[0]
            strike = float(strike_str)
            r = _ensure_record(strike)
            r['openInterest_c'] = int(opt.get('openInterest', 0))
            r['gamma_c'] = _clean_greek(opt.get('gamma'))
            r['delta_c'] = abs(_clean_greek(opt.get('delta')))
            r['theta_c'] = _clean_greek(opt.get('theta'))
            r['vega_c'] = _clean_greek(opt.get('vega'))
            r['iv_c'] = _extract_iv(opt)
            r['volume_c'] = int(opt.get('totalVolume', 0) or 0)

        for strike_str, opt_list in puts_for_exp.items():
            if not opt_list:
                continue
            opt = opt_list[0]
            strike = float(strike_str)
            r = _ensure_record(strike)
            r['openInterest_p'] = int(opt.get('openInterest', 0))
            r['gamma_p'] = _clean_greek(opt.get('gamma'))
            r['delta_p'] = -abs(_clean_greek(opt.get('delta')))
            r['theta_p'] = _clean_greek(opt.get('theta'))
            r['vega_p'] = _clean_greek(opt.get('vega'))
            r['iv_p'] = _extract_iv(opt)
            r['volume_p'] = int(opt.get('totalVolume', 0) or 0)

        all_records.extend(records.values())

    df = (
        pd.DataFrame(all_records).sort_values(['dte', 'strike']).reset_index(drop=True)
        if all_records else pd.DataFrame()
    )
    return df, selected_exp
