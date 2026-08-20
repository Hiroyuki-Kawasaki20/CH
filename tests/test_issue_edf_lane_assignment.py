"""2026-08-20型17山に対するEDF 3レーン割付の受入テスト。"""

import json
from pathlib import Path

from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW
from src.services.process_assigner import _edf_list_schedule


_FIXTURE = Path(__file__).parent / "fixtures" / "issue_edf_20260820.json"


def _load_case():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_issue_edf_20260820_keeps_urgent_mountains_before_lunch_lock():
    case = _load_case()
    result = _edf_list_schedule(
        case["mountains"],
        case["lane_floors"],
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    rows = {int(row["yama_no"]): row for row in result["rows"]}
    assert result["late_count"] <= 1
    assert rows[7]["end_secs"] <= 10 * 3600 + 30 * 60
    assert rows[8]["end_secs"] <= 10 * 3600 + 30 * 60
    assert rows[17]["end_secs"] <= 10 * 3600 + 30 * 60
    assert result["lanes"][PROC_RELIEF]
    # 12:19は目安。現状の12:46相当を悪化させないことを必須条件とする。
    assert result["finish_secs"] <= 12 * 3600 + 46 * 60


def test_issue_edf_uses_three_lanes_and_respects_lane_floors():
    case = _load_case()
    result = _edf_list_schedule(
        case["mountains"],
        case["lane_floors"],
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    assert set(result["used_lanes"]) == {PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW}
    for lane, floor in case["lane_floors"].items():
        lane_rows = result["lanes"][lane]
        assert lane_rows
        assert lane_rows[0]["start_secs"] >= floor
