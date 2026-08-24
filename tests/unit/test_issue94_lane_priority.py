"""Issue #94: EDF のレーン節約とあふれ判定の回帰テスト。"""

import json
from pathlib import Path

import pandas as pd

from src.models.constants import PROC_MAIN, PROC_OVERFLOW, PROC_RELIEF
from src.services.process_assigner import (
    _edf_list_schedule,
    _schedule_edf_lane_rows,
    assign_processes_by_arrival_time,
)


_FIXTURE = Path(__file__).parents[1] / "fixtures" / "issue_edf_20260820.json"


def _load_case():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_light_load_keeps_all_mountains_on_main():
    mountains = [
        {"yama_no": 1, "work_secs": 600, "deadline_secs": 50_000},
        {"yama_no": 2, "work_secs": 600, "deadline_secs": 50_000},
        {"yama_no": 3, "work_secs": 600, "deadline_secs": 50_000},
    ]
    result = _edf_list_schedule(
        mountains,
        {PROC_MAIN: 0, PROC_RELIEF: 0, PROC_OVERFLOW: 0},
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    assert result["used_lanes"] == [PROC_MAIN]
    assert all(row["lane"] == PROC_MAIN for row in result["rows"])


def test_issue94_20260820_keeps_deadline_and_relief_guardrails():
    case = _load_case()
    result = _edf_list_schedule(
        case["mountains"],
        case["lane_floors"],
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    late_count = sum(row["late"] for row in result["rows"])
    assert late_count <= 4
    assert result["finish_secs"] <= 12 * 3600 + 51 * 60
    assert result["lanes"][PROC_RELIEF]


def test_overflow_rows_are_only_rows_that_miss_deadline_on_relief():
    case = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "issue_edf_20260820_v2.json").read_text(
            encoding="utf-8"
        )
    )
    assigned = assign_processes_by_arrival_time(
        pd.DataFrame(case["proc_rows"]),
        pd.DataFrame(case["master_rows"]),
        previous_lane_end_times=case["lane_floors"],
    )
    by_yama = {int(mountain["yama_no"]): mountain for mountain in case["mountains"]}

    relief_rows = []
    for _, row in assigned[assigned["山工程"] == PROC_RELIEF].drop_duplicates("山通番").iterrows():
        mountain = by_yama[int(row["山通番"])]
        relief_rows.append(
            {
                "yama_no": int(row["山通番"]),
                "work_secs": int(mountain["work_secs"]),
                "deadline_secs": mountain["deadline_secs"],
                "start_floor_secs": int(mountain["start_floor_secs"]),
            }
        )

    overflow_rows = assigned[assigned["山工程"] == PROC_OVERFLOW].drop_duplicates("山通番")
    for _, row in overflow_rows.iterrows():
        mountain = by_yama[int(row["山通番"])]
        trial_rows = _schedule_edf_lane_rows(
            relief_rows
            + [
                {
                    "yama_no": int(row["山通番"]),
                    "work_secs": int(mountain["work_secs"]),
                    "deadline_secs": mountain["deadline_secs"],
                    "start_floor_secs": int(mountain["start_floor_secs"]),
                }
            ],
            int(case["lane_floors"][PROC_RELIEF]),
        )
        relief_trial = next(item for item in trial_rows if item["yama_no"] == int(row["山通番"]))
        assert mountain["deadline_secs"] is not None
        assert relief_trial["end_secs"] > int(mountain["deadline_secs"]), (
            f"山{row['yama_no']} はリリーフで締切内に収まるため、あふれにできない"
        )
