"""Issue #85/PR #86: public assign_processes_by_arrival_time が EDF 候補を劣化させないことを検証。"""

import json
from pathlib import Path

import pandas as pd

from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW
from src.services.process_assigner import _edf_list_schedule, assign_processes_by_arrival_time

_FIXTURE = Path(__file__).parent / "fixtures" / "issue_edf_20260820.json"


def _load_case():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _hhmm_to_secs(value):
    s = str(value).strip()
    if not s:
        return 0
    hh, mm = s.split(":")
    return int(hh) * 3600 + int(mm) * 60


def _score_case(result_df, case):
    late_count = 0
    finish_secs = 0
    rows = result_df.to_dict(orient="records")
    by_yama = {int(r["山通番"]): r for r in rows}
    for mountain in case["mountains"]:
        yama_no = int(mountain["yama_no"])
        row = by_yama.get(yama_no)
        if row is None:
            continue
        start = _hhmm_to_secs(row.get("実開始時間", "00:00"))
        end = _hhmm_to_secs(row.get("実終了時間", "00:00"))
        deadline = int(mountain["deadline_secs"])
        finish_secs = max(finish_secs, end)
        if end > deadline:
            late_count += 1
    return late_count, finish_secs


def _edf_rows_to_result(edf_rows):
    rows = []
    for row in edf_rows:
        rows.append(
            {
                "山通番": int(row["yama_no"]),
                "山工程": row["lane"],
                "実開始時間": f"{int(row['start_secs']) // 3600:02d}:{(int(row['start_secs']) % 3600) // 60:02d}",
                "実終了時間": f"{int(row['end_secs']) // 3600:02d}:{(int(row['end_secs']) % 3600) // 60:02d}",
            }
        )
    return pd.DataFrame(rows)


def _secs_to_hhmm(value):
    total = int(value)
    hh = total // 3600
    mm = (total % 3600) // 60
    return f"{hh:02d}:{mm:02d}"


def _build_master_from_fixture_deadlines(case):
    rows = []
    for mountain in sorted(case["mountains"], key=lambda m: int(m["yama_no"])):
        yama_no = int(mountain["yama_no"])
        pickup_secs = int(mountain["deadline_secs"]) + 20 * 60
        rows.append(
            {
                "OData_納入先": "TEST",
                "NONYUHIBIN": f"{yama_no:02d}",
                "入車時間": _secs_to_hhmm(pickup_secs),
            }
        )
    return pd.DataFrame(rows)


def test_assign_processes_by_arrival_time_should_not_worsen_edf_candidate():
    case = _load_case()
    proc_rows = [
        {
            "山通番": int(m["yama_no"]),
            "納入先": "TEST",
            "NONYUHIBIN": f"{int(m['yama_no']):02d}",
            "移動工数": int(m["work_secs"]),
        }
        for m in case["mountains"]
    ]
    master_df = _build_master_from_fixture_deadlines(case)

    result = assign_processes_by_arrival_time(
        pd.DataFrame(proc_rows),
        master_df,
        previous_lane_end_times={
            PROC_MAIN: int(case["lane_floors"][PROC_MAIN]),
            PROC_RELIEF: int(case["lane_floors"][PROC_RELIEF]),
            PROC_OVERFLOW: int(case["lane_floors"][PROC_OVERFLOW]),
        },
    )

    edf_candidate = _edf_list_schedule(
        case["mountains"],
        case["lane_floors"],
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    existing_score = _score_case(result, case)
    edf_score = _score_case(_edf_rows_to_result(edf_candidate["rows"]), case)

    assert existing_score <= edf_score, (
        f"assign_processes_by_arrival_time が EDF候補を劣化させています: "
        f"existing={existing_score}, edf={edf_score}"
    )
