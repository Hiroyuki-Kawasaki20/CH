"""Battery exchange path should reuse Hino 2-lane previous-bin logic."""

import pandas as pd

from src.services.process_assigner import (
    ARRIVAL_BUFFER_SECS,
    assign_processes_by_arrival_time,
    compute_proc_details,
    _seconds_to_hhmm,
    _time_to_seconds,
)
from src.services.scheduler import _mountain_context


def _build_hino_master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "13:10", "セットありフラグ": "0"},
            {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "17:05", "セットありフラグ": "0"},
            {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:20", "セットありフラグ": "1"},
        ]
    )


def test_mountain_context_hino_set_flag_true_uses_n_minus_2_in_battery_exchange_path():
    """Battery ON path must use same-lane previous bin (N-2) for Hino."""
    proc_details = pd.DataFrame(
        [
            {
                "山通番": 1,
                "移動工数": 0,
                "納入先": "日野",
                "NONYUHIBIN": "2026060103",
                "高さ": 300,
            }
        ]
    )

    info, _prev_floor_map, _work_map, _ddl_map = _mountain_context(proc_details, _build_hino_master())
    row = next(m for m in info if int(m["山通番"]) == 1)

    expected = _time_to_seconds("13:10") + ARRIVAL_BUFFER_SECS
    assert int(row["開始時間_秒"]) == expected


def test_legacy_assign_path_keeps_hino_n_minus_2_behavior_when_battery_off():
    """Battery OFF path remains unchanged and still references N-2 for Hino."""
    details = pd.DataFrame(
        [
            {
                "山通番": 1,
                "移動工数": 0,
                "納入先": "日野",
                "NONYUHIBIN": "2026060103",
                "高さ": 300,
            }
        ]
    )

    result = assign_processes_by_arrival_time(compute_proc_details(details), _build_hino_master())
    row = result.loc[result["山通番"] == 1].iloc[0]

    expected_hhmm = _seconds_to_hhmm(_time_to_seconds("13:10") + ARRIVAL_BUFFER_SECS)
    # 13:10+10分=13:20 は休憩(12:55-13:25)内のため、休憩明け+1分=13:26 に調整される
    assert str(row["実開始時間"]) == "13:26"
