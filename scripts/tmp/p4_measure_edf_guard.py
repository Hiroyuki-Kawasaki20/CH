import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.services.process_assigner as process_assigner
from tests.test_issue_edf_integration import (
    _build_master,
    _build_proc_details,
    _hhmm_to_secs,
    _lane_floors,
    _load_case,
)


def _format_secs(value):
    value = int(value)
    return f"{value // 3600:02d}:{(value % 3600) // 60:02d}:{value % 60:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--without-guard", action="store_true")
    args = parser.parse_args()

    monkeypatch = None
    if args.without_guard:
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            process_assigner,
            "_makes_others_newly_late",
            lambda **_kwargs: False,
        )

    try:
        case = _load_case()
        result = process_assigner.assign_processes_by_arrival_time(
            _build_proc_details(case),
            _build_master(case),
            previous_lane_end_times=_lane_floors(case),
        )
    finally:
        if monkeypatch is not None:
            monkeypatch.undo()

    rows_by_yama = {int(row["山通番"]): row for row in result.to_dict(orient="records")}
    late_rows = []
    finish_secs = 0
    for mountain in case["mountains"]:
        yama_no = int(mountain["yama_no"])
        row = rows_by_yama.get(yama_no)
        if row is None:
            continue
        end_secs = _hhmm_to_secs(row.get("実終了時間", "00:00"))
        finish_secs = max(finish_secs, end_secs)
        deadline_secs = mountain["deadline_secs"]
        if deadline_secs is not None and end_secs > int(deadline_secs):
            late_rows.append((yama_no, int(deadline_secs), end_secs))

    print(f"guard_enabled={not args.without_guard}")
    print(f"late_count={len(late_rows)}")
    for yama_no, deadline_secs, end_secs in late_rows:
        print(
            f"yama={yama_no} deadline={_format_secs(deadline_secs)} "
            f"end={_format_secs(end_secs)} over_secs={end_secs - deadline_secs}"
        )
    print(f"finish={_format_secs(finish_secs)}")


if __name__ == "__main__":
    main()