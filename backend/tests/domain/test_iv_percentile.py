from app.domain.iv_percentile import compute_iv_percentile


def test_returns_none_with_insufficient_history():
    assert compute_iv_percentile(0.25, [0.20, 0.22, 0.18]) is None


def test_returns_none_with_empty_history():
    assert compute_iv_percentile(0.25, []) is None


def test_computes_real_percentile_with_enough_history():
    history = [0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.24, 0.26, 0.28]
    result = compute_iv_percentile(0.20, history)
    assert result is not None
    assert "histórico real" in result
    assert "10d" in result
    # 6 de 10 valores son <= 0.20 (0.10..0.20) -> 60th percentile
    assert result.startswith("60th")


def test_current_iv_above_all_history_is_100th_percentile():
    history = [0.10, 0.12, 0.14, 0.16, 0.18, 0.10, 0.12, 0.14, 0.16, 0.18]
    result = compute_iv_percentile(0.50, history)
    assert result.startswith("100th")


def test_current_iv_below_all_history_is_0th_percentile():
    history = [0.30, 0.32, 0.34, 0.36, 0.38, 0.30, 0.32, 0.34, 0.36, 0.38]
    result = compute_iv_percentile(0.05, history)
    assert result.startswith("0th")
