from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.session_profile import (
    SESSION_TZ,
    cash_key_for,
    format_session_profile,
    overnight_key_for,
)

LIMA = ZoneInfo("America/Lima")

PROFILE = {
    "poc": 20100.0, "vah": 20150.0, "val": 20050.0,
    "hvn": [20100.0, 20125.0], "lvn": [20075.0],
    "delta_outliers": [{"price": 20080.0, "delta": 1250.0}],
    "tpo_poc": 20105.0, "tpo_lvn": [20060.0],
}


def test_overnight_key_after_start_uses_todays_date():
    now = datetime(2026, 9, 12, 20, 0, tzinfo=LIMA)  # 20:00, después de las 17:00
    assert overnight_key_for(now) == "overnight_2026-09-12"


def test_overnight_key_before_cash_start_uses_previous_days_date():
    now = datetime(2026, 9, 12, 3, 0, tzinfo=LIMA)  # 03:00 -- la sesión arrancó AYER a las 17:00
    assert overnight_key_for(now) == "overnight_2026-09-11"


def test_overnight_key_during_cash_session_still_uses_previous_days_date():
    # A las 10:00 (dentro de Cash) la última sesión Overnight relevante
    # sigue siendo la de la madrugada de HOY, que arrancó AYER a las 17:00.
    now = datetime(2026, 9, 12, 10, 0, tzinfo=LIMA)
    assert overnight_key_for(now) == "overnight_2026-09-11"


def test_cash_key_during_session_uses_todays_date():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=LIMA)
    assert cash_key_for(now) == "cash_2026-09-12"


def test_cash_key_before_open_uses_previous_days_date():
    now = datetime(2026, 9, 12, 7, 0, tzinfo=LIMA)  # antes de las 08:30
    assert cash_key_for(now) == "cash_2026-09-11"


def test_keys_convert_other_timezones_to_lima():
    # Mismo instante, pasado en UTC -- debe dar la misma clave que en Lima.
    now_utc = datetime(2026, 9, 13, 1, 0, tzinfo=ZoneInfo("UTC"))  # == 2026-09-12 20:00 Lima
    assert overnight_key_for(now_utc) == "overnight_2026-09-12"


def test_format_session_profile_none_says_no_data_yet():
    text = format_session_profile("Overnight", None)
    assert "sin datos disponibles" in text


def test_format_session_profile_includes_all_fields():
    text = format_session_profile("Overnight (Asia/London/pre-market)", PROFILE)
    assert "20100.00" in text  # POC
    assert "20150.00" in text  # VAH
    assert "20050.00" in text  # VAL
    assert "20125.00" in text  # HVN
    assert "20075.00" in text  # LVN
    assert "20080.00" in text and "+1250" in text  # delta outlier
    assert "20105.00" in text  # TPO POC
    assert "20060.00" in text  # TPO LVN


def test_format_session_profile_empty_lists_say_ninguno():
    empty_profile = {"poc": 100.0, "vah": 101.0, "val": 99.0, "hvn": [], "lvn": [], "delta_outliers": [], "tpo_poc": 100.0, "tpo_lvn": []}
    text = format_session_profile("Cash", empty_profile)
    assert text.count("ninguno") == 4  # HVN, LVN, delta outliers, TPO LVN
