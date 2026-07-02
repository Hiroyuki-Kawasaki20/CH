"""Unit tests for Hino 2-lane wraparound scheduling behavior."""

import pytest
import pandas as pd

from src.services.process_assigner import (
    compute_proc_details,
    assign_processes_by_arrival_time,
    _to_operational_timeline_secs,
    _seconds_to_hhmm,
)
from src.models.constants import PROC_MAIN


def _run_once(detail_rows: list, master_rows: list) -> pd.DataFrame:
    details = pd.DataFrame(detail_rows)
    master_df = pd.DataFrame(master_rows)
    return assign_processes_by_arrival_time(compute_proc_details(details), master_df)


class TestHino2LaneWraparound:
    def test_hino01_set_flag_true_wraps_to_hino15_and_starts_0034(self):
        """日野01(セットあり)は同レーン最終便15(00:24)を参照し00:34開始になる。"""
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
                {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "22:00", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "14", "入車時間": "23:40", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "15", "入車時間": "00:24", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "24:34"

    def test_hino09_set_flag_true_uses_hino07_and_starts_1402(self):
        """日野09(セットあり)は日野07(13:52)参照で14:02開始になる。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060109", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "07:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "07:35", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "07:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "06", "入車時間": "08:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "13:52", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "14:10", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "17:30", "セットありフラグ": "1"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "14:02"

    def test_even_lane_head_wraps_to_latest_even_bin(self):
        """偶数レーン先頭便(02)は当月最終偶数便へ巻き戻る。"""
        result = _run_once(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026060102", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "07:05", "セットありフラグ": "1"},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "07:35", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "07:50", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "06", "入車時間": "08:05", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "18:00", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "21:10", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "12", "入車時間": "23:40", "セットありフラグ": "0"},
                {"OData_納入先": "日野", "NONYUHIBIN": "14", "入車時間": "00:40", "セットありフラグ": "0"},
            ],
        )
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "24:50"

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

    def test_hino01_without_flag_does_not_wrap_and_uses_shift_plus_15(self):
        """フラグなし先頭便は巻き戻らず、従来どおり各直開始+15分(06:40)になる。"""
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
        assert str(row["実開始時間"]) == "06:40"


class TestBackwardCompatibility:
    def test_hino_eh_stays_on_existing_path(self):
        """日野EHは2レーン対象外のため従来N-1制約を使う。"""
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
        assert str(row["実開始時間"]) == "08:41"

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
