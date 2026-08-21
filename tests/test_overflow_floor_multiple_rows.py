import pandas as pd

from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW
from src.services.process_assigner import assign_processes_by_arrival_time


def _secs(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 3600 + int(mm) * 60


def test_overflow_floor_applies_to_all_rows_in_overflow_lane():
    """あふれレーンに2山が入るケースでも、両方の開始時刻が overflow 床以上になる。"""
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["A", "A", "A"],
            "NONYUHIBIN": ["01", "02", "03"],
            "入車時間": ["09:00", "09:05", "09:20"],
        }
    )
    proc_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3],
            "納入先": ["A", "A", "A"],
            "NONYUHIBIN": ["01", "02", "03"],
            "移動工数": [300, 300, 300],
        }
    )

    result = assign_processes_by_arrival_time(
        proc_df,
        master_df,
        previous_lane_end_times={
            PROC_MAIN: 0,
            PROC_RELIEF: 0,
            PROC_OVERFLOW: _secs("09:00"),
        },
    )

    overflow_rows = result[result["山工程"] == PROC_OVERFLOW].sort_values("山通番")
    assert len(overflow_rows) >= 2
    start_times = [_secs(str(row["実開始時間"])) for _, row in overflow_rows.iterrows()]
    assert all(start >= _secs("09:00") for start in start_times), (
        f"overflow 床未満で開始している山がある: {overflow_rows[['山通番','実開始時間']].to_dict('records')}"
    )
