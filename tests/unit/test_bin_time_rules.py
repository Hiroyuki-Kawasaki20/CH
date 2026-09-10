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
    assert deadline == 13 * 3600 + 10 * 60   # 入車13:30 − 20分


def test_bin01_has_no_floor_and_missing_arrival_has_no_deadline():
    m = build_bin_time_map(_master([("拠点B", "01", "12:20")]))
    floor, deadline = unit_floor_deadline("拠点B", "01", "12:20", m)
    assert floor == 0
    assert deadline == 12 * 3600
    assert unit_floor_deadline("拠点X", "05", "", m) == (0, None)


def _takaoka_like_master():
    """01便が深夜・05便が最終便という高岡便のような周期スケジュール（#96 穴2）。"""
    return _master([
        ("拠点D", "01", "22:59"),
        ("拠点D", "02", "06:45"),
        ("拠点D", "03", "10:51"),
        ("拠点D", "04", "14:40"),
        ("拠点D", "05", "18:46"),
    ])


def test_bin01_prev_wraps_to_last_bin_of_vendor():
    """01便の前便は最終便（05便）＝18:46＋10分になる（河崎様確認済みルール）。"""
    m = build_bin_time_map(_takaoka_like_master())
    floor, deadline = unit_floor_deadline("拠点D", "01", "22:59", m)
    assert floor == 18 * 3600 + 46 * 60 + 10 * 60  # 05便18:46 + 10分
    assert deadline == 22 * 3600 + 59 * 60 - 20 * 60


def test_prev_bin_across_midnight_does_not_invert_floor_past_deadline():
    """前便が深夜(22:59)・現行便が翌早朝(06:45)でも floor が締切を超えない（#96 穴2）。"""
    m = build_bin_time_map(_takaoka_like_master())
    floor, deadline = unit_floor_deadline("拠点D", "02", "06:45", m)
    assert floor <= deadline
    assert floor == 0  # 前便22:59は前日側と判定され-24h補正後0（下限なし相当）

def test_prev_bin_same_day_no_crossing_matches_naive_calculation():
    """日跨ぎが無い通常ケース（03便の前便=02便）は従来の素朴な加算と同じ結果になる（regression）。"""
    m = build_bin_time_map(_takaoka_like_master())
    floor, deadline = unit_floor_deadline("拠点D", "03", "10:51", m)
    assert floor == 6 * 3600 + 45 * 60 + 10 * 60  # 02便06:45 + 10分
    assert deadline == 10 * 3600 + 51 * 60 - 20 * 60
