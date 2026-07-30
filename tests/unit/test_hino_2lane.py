"""Unit tests for Hino 2-lane wraparound scheduling behavior."""

import inspect

import pytest
import pandas as pd

from src.services.process_assigner import (
    compute_proc_details,
    assign_processes_by_arrival_time,
    _legacy_assign_processes_by_arrival_time,
    ARRIVAL_BUFFER_SECS,
    SHIFT_FIRST_TRIP_BUFFER_SECS,
    _time_to_seconds,
    _to_operational_timeline_secs,
    _seconds_to_hhmm,
    _shift_start_secs,
)
from src.models.constants import PROC_MAIN


def _run_once(detail_rows: list, master_rows: list) -> pd.DataFrame:
    details = pd.DataFrame(detail_rows)
    master_df = pd.DataFrame(master_rows)
    return assign_processes_by_arrival_time(compute_proc_details(details), master_df)


class TestHino2LaneWraparound:
    def test_hino_real_master_set_off_order9_is_clamped_to_shift_floor_main(self):
        """実マスタ値: セットなし9便は07便(00:24)参照でも開始が07:00未満にならない。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026070709", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "00:24", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "06:29", "セットありフラグ": "1"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "07:54", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "09:02", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        start_secs = _time_to_seconds(str(row["実開始時間"]))
        floor_secs = _shift_start_secs(0) + SHIFT_FIRST_TRIP_BUFFER_SECS
        assert start_secs is not None
        assert start_secs >= floor_secs
        assert str(row["実開始時間"]) == "07:00"

    def test_hino_real_master_set_true_keeps_reference_priority(self):
        """実マスタ値: セットあり8便は参照時刻優先(下限クランプなし)のまま。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026070708", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "00:24", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "06:29", "セットありフラグ": "1"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "07:54", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "09:02", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_time_to_seconds("09:02") + ARRIVAL_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_hino_split_loop_has_set_off_floor_clamp(self):
        """yama_split_units_map側にも set_flag=False の06:40下限クランプが必要。"""
        src = inspect.getsource(_legacy_assign_processes_by_arrival_time)
        split_part = src.split("yama_split_units_map", 1)[1]
        assert "if not set_flag:" in split_part
        assert "shift_floor = _shift_start_secs(shift_idx) + SHIFT_FIRST_TRIP_BUFFER_SECS" in split_part
        assert "st = max(int(st), int(shift_floor))" in split_part

    def test_hino_set_flag_true_uses_same_lane_previous_order_plus_buffer(self):
        """日野(2レーン)のセットあり便は order-2 の入車時間+10分を使う。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060103", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "13:10", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "17:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "1"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_time_to_seconds("13:10") + ARRIVAL_BUFFER_SECS)
        # 13:10+10分=13:20 は休憩(12:55-13:25)内のため、休憩明け+1分=13:26 に調整される
        assert str(row["実開始時間"]) == "13:26"

    def test_non_hino_set_flag_true_uses_previous_order_plus_buffer(self):
        """日野以外(1レーン)のセットあり便は order-1 の入車時間+10分を使う。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "織機", "NONYUHIBIN": "2026060103", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "織機", "NONYUHIBIN": "01", "入車時間": "13:10", "セットありフラグ": "0"},
                {"OData_納入先": "織機", "NONYUHIBIN": "02", "入車時間": "17:05", "セットありフラグ": "0"},
                {"OData_納入先": "織機", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "1"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_time_to_seconds("17:05") + ARRIVAL_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_hino_set_flag_off_first_trip_uses_shift_start_plus_buffer(self):
        """セットなしの先頭便は各直開始+35分を開始下限にする。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "07:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_shift_start_secs(0) + SHIFT_FIRST_TRIP_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_hino_set_flag_off_order9_uses_order8_not_order7(self):
        """セットなしの日野9便は同レーン直前便を参照しつつ、2直開始+35分を下回らない。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060109", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "24:40", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "17:10", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "18:30", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_shift_start_secs(1) + SHIFT_FIRST_TRIP_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_hino_order10_uses_order8_even_when_set_flag_off(self):
        """日野10便はセットなしでも同レーン直前便(order-2=08)を参照する。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026070710", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "07:18", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "07:54", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "08:14", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_time_to_seconds("07:18") + ARRIVAL_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_hino_order10_uses_order8_even_without_set_flag_column(self):
        """セットありフラグ列が無くても、日野10便は同レーン直前便(order-2=08)を参照する。"""
        details = pd.DataFrame(
            [
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026070710", "高さ": 300},
            ]
        )
        master_df = pd.DataFrame(
            [
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "07:18"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "07:54"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "08:14"},
            ]
        )
        result = assign_processes_by_arrival_time(compute_proc_details(details), master_df)
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_time_to_seconds("07:18") + ARRIVAL_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_relief_split_loop_has_hino_2lane_branch(self):
        """リリーフ救済用(yama_split_units_map)にも日野2レーン分岐が必要。"""
        src = inspect.getsource(_legacy_assign_processes_by_arrival_time)
        split_part = src.split("yama_split_units_map", 1)[1]
        assert "_is_hino_2lane_target(vendor)" in split_part

    def test_oriki_set_flag_off_first_trip_keeps_shift_floor(self):
        """セットなし織機の1便目は 07:00 未満にならない。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "織機", "NONYUHIBIN": "2026060101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "織機", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "0"},
                {"OData_納入先": "織機", "NONYUHIBIN": "02", "入車時間": "07:10", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        expected = _seconds_to_hhmm(_shift_start_secs(0) + SHIFT_FIRST_TRIP_BUFFER_SECS)
        assert str(row["実開始時間"]) == expected

    def test_wrap_target_is_dynamic_when_max_bin_is_13(self):
        """当月最終便が13のケースでも同レーン最終便を動的取得できる。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "1"},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "07:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "07:35", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "07:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "06", "入車時間": "08:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "13:52", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "14:10", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "17:30", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "17:45", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "11", "入車時間": "18:00", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "12", "入車時間": "18:15", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "00:20", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "24:30"

    def test_0230_is_normalized_to_2630_without_rollover(self):
        """深夜02:30は03:00境界で+24hされ、26:30表記を維持する。"""
        secs = _to_operational_timeline_secs(2 * 3600 + 30 * 60)
        assert _seconds_to_hhmm(secs) == "26:30"

    def test_hino_set_flag_wrap_from_0629_stays_same_day_0639(self):
        """巻き戻り先が06:29なら+24hせず、開始は06:39の当日表記になる。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060103", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:29", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "1"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "06:39"

    def test_0600_remains_0600_without_wrap(self):
        """03:00以降の通常時刻06:00は補正せず06:00のまま。"""
        secs = _to_operational_timeline_secs(6 * 3600)
        assert _seconds_to_hhmm(secs) == "06:00"

    def test_hino01_without_flag_does_not_wrap_and_uses_shift_plus_buffer(self):
        """フラグなし先頭便は巻き戻らず、従来どおり各直開始+35分(07:00)になる。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "07:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "13:52", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "17:30", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "11", "入車時間": "18:00", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "22:00", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "15", "入車時間": "00:24", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert str(row["実開始時間"]) == "07:00"


class TestBackwardCompatibility:
    def test_hino_eh_uses_hino_lane_count_rule(self):
        """セットなしの日野EHは同レーン参照を使わず、従来どおりN-1便+10分を使う。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野EH", "NONYUHIBIN": "2026060102", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野EH", "NONYUHIBIN": "01", "入車時間": "08:26", "セットありフラグ": "0"},
                {"OData_納入先": "日野EH", "NONYUHIBIN": "02", "入車時間": "10:56", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "09:01"  # 8:36は休憩(8:30-9:00)内→休憩明け+1分

    def test_non_hino_uses_existing_n_minus_1_behavior(self):
        """非日野は従来どおりN-1便+10分を開始下限にする。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "A", "NONYUHIBIN": "2026060102", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "A", "NONYUHIBIN": "01", "入車時間": "06:40", "セットありフラグ": "0"},
                {"OData_納入先": "A", "NONYUHIBIN": "02", "入車時間": "07:00", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        # 山工程は工数/締切条件で変動し得るため固定しない。
        assert str(row["実開始時間"]) == "06:50"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
