import pandas as pd
import pytest

from app.domain.gex_math import (
    DEFAULT_IV,
    DEFAULT_T_EXP,
    compute_call_put_walls,
    compute_gamma_flip,
    compute_gamma_wall,
    compute_greeks_exposures,
    compute_zero_crossing,
    compute_zero_gamma,
    recalculate_gex_for_spot,
)


def _sample_df():
    return pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'openInterest_c': [100, 500, 50],
        'openInterest_p': [50, 300, 100],
        'delta_c': [0.80, 0.50, 0.20],
        'delta_p': [-0.20, -0.50, -0.80],
        'theta_c': [-0.10, -0.20, -0.08],
        'theta_p': [-0.09, -0.19, -0.07],
        'vega_c': [0.20, 0.30, 0.15],
        'vega_p': [0.18, 0.29, 0.14],
    })


def test_recalculate_gex_gamma_peaks_atm():
    df = recalculate_gex_for_spot(_sample_df(), spot_t=100.0, t_exp=7 / 365, iv=0.20)
    gamma_by_strike = df.set_index('strike')['gamma']
    # Propiedad conocida de Black-Scholes: la gamma es máxima cerca del ATM
    assert gamma_by_strike[100.0] > gamma_by_strike[95.0]
    assert gamma_by_strike[100.0] > gamma_by_strike[105.0]


def test_recalculate_gex_call_gex_includes_contract_multiplier():
    # Bug real (ver gex_terminal_v2_lessons): call_gex/put_gex/net_gex usaban
    # gamma * OI * spot^2 * 0.01, sin el multiplicador de contrato (100) que
    # SI usan net_dex/net_tex/net_vex/net_chex/net_vanna en
    # compute_greeks_exposures (mismo archivo) -- inconsistente con la
    # convencion estandar de "Gamma Exposure" (gamma * OI * 100 * spot^2 *
    # 0.01, el $ que cambia el hedge de dealers por cada 1% de movimiento).
    df = recalculate_gex_for_spot(_sample_df(), spot_t=100.0, t_exp=7 / 365, iv=0.20)
    row100 = df[df['strike'] == 100.0].iloc[0]
    gamma = row100['gamma']
    expected_call_gex = gamma * 500 * 100 * (100.0 ** 2) * 0.01
    expected_put_gex = gamma * 300 * 100 * (100.0 ** 2) * (-0.01)
    assert abs(row100['call_gex'] - expected_call_gex) < 1e-6
    assert abs(row100['put_gex'] - expected_put_gex) < 1e-6


def test_recalculate_gex_call_positive_put_negative():
    df = recalculate_gex_for_spot(_sample_df(), spot_t=100.0, t_exp=7 / 365, iv=0.20)
    assert (df['call_gex'] >= 0).all()
    assert (df['put_gex'] <= 0).all()
    assert (df['net_gex'] == df['call_gex'] + df['put_gex']).all()


def test_recalculate_gex_empty_or_invalid_spot():
    empty = pd.DataFrame()
    assert recalculate_gex_for_spot(empty, 100.0, 0.02, 0.2).empty
    df = _sample_df()
    result = recalculate_gex_for_spot(df, spot_t=0.0, t_exp=0.02, iv=0.2)
    assert result is df  # devuelve el input sin tocar si spot <= 0


def test_compute_greeks_exposures_net_dex_matches_manual_calc():
    df = compute_greeks_exposures(_sample_df(), spot_price=100.0, t_exp=7 / 365, atm_iv=0.20)
    row100 = df[df['strike'] == 100.0].iloc[0]
    expected_call_dex = 0.50 * 500 * 100 * 100.0 / 1e6
    expected_put_dex = -0.50 * 300 * 100 * 100.0 / 1e6
    assert abs(row100['call_dex'] - expected_call_dex) < 1e-9
    assert abs(row100['net_dex'] - (expected_call_dex + expected_put_dex)) < 1e-9


def test_compute_call_put_walls_ranks_by_magnitude():
    df_grouped = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0, 110.0],
        'net_gex': [8.0, 3.0, -2.0, -9.0],
    })
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(df_grouped, spot_ref=100.0)
    assert cw1 == 95.0  # mayor net_gex positivo
    assert cw2 == 100.0
    assert pw1 == 110.0  # net_gex más negativo
    assert pw2 == 105.0


def test_compute_call_put_walls_empty_returns_none():
    # Antes: spot + 5 / spot - 5, walls inventados sin open interest detrás
    # que llegaban a la web y a Quantower como si fueran reales.
    assert compute_call_put_walls(pd.DataFrame(), spot_ref=100.0) == (None,) * 6


def test_compute_call_put_walls_partial_returns_none_for_missing_levels():
    # Un solo strike real de cada lado: CW1/PW1 reales, el resto no existe.
    # Antes se rellenaban con CW1 + 5, CW1 + 10, etc.
    df_grouped = pd.DataFrame({'strike': [95.0, 105.0], 'net_gex': [8.0, -9.0]})
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(df_grouped, spot_ref=100.0, gap=2.0)
    assert (cw1, cw2, cw3) == (95.0, None, None)
    assert (pw1, pw2, pw3) == (105.0, None, None)


def test_compute_gamma_wall_uses_absolute_exposure_not_net():
    # 100: 10M calls + 10M puts -> se cancela a 0 en net_gex pero es |20M|
    # en gamma absoluto -- eso lo hace el Gamma Wall pese a no ganar en
    # ningun lado. 95 tiene 12M netos en calls, mas que cualquier lado de
    # 100, pero menos que el total absoluto de 100.
    df_grouped = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'net_gex': [12.0, 0.0, -9.0],
        'call_gex': [12.0, 10.0, 0.0],
        'put_gex': [0.0, -10.0, -9.0],
    })
    assert compute_gamma_wall(df_grouped, spot_ref=100.0) == 100.0


def test_compute_gamma_wall_empty_is_none():
    assert compute_gamma_wall(pd.DataFrame(), spot_ref=123.45) is None


def test_compute_gamma_wall_without_call_put_columns_is_none():
    df_grouped = pd.DataFrame({'strike': [95.0, 105.0], 'net_gex': [8.0, -9.0]})
    assert compute_gamma_wall(df_grouped, spot_ref=100.0) is None


# --- Zero Gamma / Gamma Flip ---------------------------------------------

def test_compute_zero_gamma_without_oi_uses_interpolated_cumsum_crossing():
    df = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'net_gex': [5.0, -3.0, -10.0],
    })
    # Acumulada por strike: 5, 2, -8 -> cruza entre 100 (2) y 105 (-8),
    # en 100 + 5 * 2/10 = 101. Antes idxmin(|acumulada|) daba 100.
    assert compute_zero_gamma(df, spot_ref=100.0) == pytest.approx(101.0)


def test_compute_zero_gamma_empty_is_none():
    assert compute_zero_gamma(pd.DataFrame(), spot_ref=123.45) is None


def test_compute_zero_gamma_falls_back_to_raw_sign_change_when_cumsum_never_crosses():
    # Bug real confirmado en vivo (15-sep-2026) con datos reales de QQQ:
    # net_gex negativo en TODO el rango visible (698-715) y recien
    # positivo desde 716 -- la acumulada nunca vuelve a cruzar cero (se
    # va mas y mas negativa), asi que idxmin(|cumsum|) devolvia el borde
    # inferior del rango (698) sin que ahi hubiera ningun cruce real.
    # Simplificado (menos strikes, mismo patron: todo negativo, un salto
    # grande, y recien positivo al final).
    df = pd.DataFrame({
        'strike': [698.0, 699.0, 700.0, 715.0, 716.0, 717.0],
        'net_gex': [-118_327.0, -178_469.0, -344_857.0, -152_430.0, 2_168.0, 61_500.0],
    })
    zg = compute_zero_gamma(df, spot_ref=710.0)
    assert zg == 716.0  # el cruce real (crudo), no el borde del rango (698)


def test_compute_zero_gamma_cumsum_that_dips_near_zero_without_crossing_is_not_the_flip():
    # Bug real (26-sep-2026), con los net_gex reales de /live_levels ese día
    # (en millones): la acumulada cruza de verdad entre 741 (-32.05) y 742
    # (+11.81), después baja a +1.13 en 744 SIN cruzar y vuelve a subir.
    # idxmin(|acumulada|) devolvía 744 (el ATM); el cruce real es 741.73.
    df = pd.DataFrame({
        'strike': [738.0, 739.0, 740.0, 741.0, 742.0, 743.0, 744.0, 745.0],
        'net_gex': [-91.61, -6.28, 56.22, 9.62, 43.86, 14.88, -25.56, 38.91],
    })
    zg = compute_zero_gamma(df, spot_ref=744.5)
    assert 741.0 < zg < 742.0
    assert zg != 744.0


def test_compute_zero_gamma_no_crossing_anywhere_is_none():
    # Ni la acumulada ni el valor crudo cruzan de signo en ningun punto
    # (todo negativo). Antes devolvía el spot, que se mostraba como flip.
    df = pd.DataFrame({
        'strike': [100.0, 105.0, 110.0],
        'net_gex': [-5.0, -3.0, -1.0],
    })
    assert compute_zero_gamma(df, spot_ref=107.0) is None


def test_compute_zero_crossing_is_generic_over_value_col():
    # Misma matemática con otra columna (net_chex, Charm Zero).
    df = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'net_chex': [5.0, -3.0, -10.0],
    })
    assert compute_zero_crossing(df, 'net_chex', spot_ref=100.0) == pytest.approx(101.0)


def test_compute_zero_crossing_missing_column_is_none():
    df = pd.DataFrame({'strike': [95.0, 100.0], 'net_gex': [1.0, -1.0]})
    assert compute_zero_crossing(df, 'net_chex', spot_ref=42.0) is None


# Open interest real de /live_levels (QQQ, spot 744.50, 26-sep-2026):
# strike, call OI, put OI.
_LIVE_OI_2026_09_26 = [
    (733, 209, 1864), (734, 260, 1343), (735, 1386, 4758), (736, 1053, 1576),
    (737, 1233, 719), (738, 1104, 2189), (739, 981, 1269), (740, 4642, 2275),
    (741, 1620, 1242), (742, 2118, 481), (743, 908, 372), (744, 710, 1614),
    (745, 2870, 1497), (746, 1236, 442), (747, 779, 553), (748, 1917, 339),
    (749, 4819, 147), (750, 3357, 258), (751, 605, 77), (752, 480, 89),
    (753, 635, 33), (754, 1575, 16), (755, 8476, 24), (756, 760, 3), (757, 2310, 2),
]


def _live_oi_df() -> pd.DataFrame:
    return pd.DataFrame(_LIVE_OI_2026_09_26, columns=['strike', 'openInterest_c', 'openInterest_p']).astype(float)


def test_compute_zero_gamma_with_oi_is_the_price_profile_crossing_on_real_data():
    # Con open interest, el flip es donde cruza cero el gamma total al
    # mover el precio (definición estándar). Ese día la app mostraba 744.00;
    # el cruce real del perfil está en ~735.6 (~345 pts de MNQ más abajo).
    flip = compute_zero_gamma(_live_oi_df(), spot_ref=744.5)
    assert flip == pytest.approx(735.59, abs=0.05)


def test_compute_gamma_flip_matches_the_gamma_price_profile_chart():
    # El flip tiene que caer donde cruza cero la curva del gráfico "Gamma
    # Price Profile" (mismo supuesto de IV/T, misma fórmula).
    df = _live_oi_df()
    flip = compute_gamma_flip(df, spot_ref=744.5)
    for price, sign in ((flip - 0.5, -1), (flip + 0.5, 1)):
        total = recalculate_gex_for_spot(df, spot_t=price, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)['net_gex'].sum()
        assert (total > 0) == (sign > 0)


def test_compute_gamma_flip_none_when_gamma_never_changes_sign():
    df = pd.DataFrame({'strike': [95.0, 100.0, 105.0], 'openInterest_c': [100, 100, 100], 'openInterest_p': [10, 10, 10]})
    assert compute_gamma_flip(df, spot_ref=100.0) is None


def test_compute_gamma_flip_picks_the_crossing_nearest_to_spot():
    # Dos cruces: uno cerca de 90 y otro cerca de 110. Con spot en 108 debe
    # ganar el de 110; con spot en 92, el de 90.
    df = pd.DataFrame({
        'strike': [85.0, 95.0, 105.0, 115.0],
        'openInterest_c': [0, 100, 100, 0],
        'openInterest_p': [100, 0, 0, 100],
    })
    assert compute_gamma_flip(df, spot_ref=108.0) == pytest.approx(110.0, abs=0.5)
    assert compute_gamma_flip(df, spot_ref=92.0) == pytest.approx(90.0, abs=0.5)
