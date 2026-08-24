"""Issue #96: bin_time_rules（床・締切共通ヘルパー）の単体テスト。"""

import pandas as pd

from src.services.bin_time_rules import (
    build_bin_time_map, timeline_secs, unit_floor_deadline,
)


def _master(rows):
    return pd.DataFrame(
        [{"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t} for v, b, t in rows]
    )


def test_timeline_secs_uses_0300_rollover_axis():
    assert timeline_secs("03:00") == 3 * 3600            # 当日帯
    assert timeline_secs("02:30") == (2 * 3600 + 30 * 60) + 24 * 3600  # 翌日帯へ
    assert timeline_secs("") is None


def test_floor_comes_from_master_even_if_prev_bin_absent_from_daily_data():
    """前便がマスタにだけ存在しても床が立つこと（#96 穴1の番人）。"""
    m = build_bin_time_map(_master([("拠点A", "06", "13:00"), ("拠点A", "07", "13:30")]))
    floor, deadline = unit_floor_deadline("拠点A", "07", "13:30", m)
    assert floor == 13 * 3600 + 10 * 60      # 前便13:00 + 10分
    assert deadline == 13 * 3600 + 20 * 60   # 入車13:30 − 10分


def test_bin01_has_no_floor_and_missing_arrival_has_no_deadline():
    m = build_bin_time_map(_master([("拠点B", "01", "12:20")]))
    floor, deadline = unit_floor_deadline("拠点B", "01", "12:20", m)
    assert floor == 0
    assert deadline == 12 * 3600 + 10 * 60
    assert unit_floor_deadline("拠点X", "05", "", m) == (0, None)
