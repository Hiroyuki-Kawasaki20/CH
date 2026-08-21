"""Issue #85/#87: public assign_processes_by_arrival_time が EDF 候補を劣化させないことを検証。

フィクスチャは 8/20 の実バッチから捕捉した実 proc_details・実 入車時間マスタ・
_legacy 内部の edf_input（実工数／実解禁床／実締切）。比較対象の EDF 候補も同じ実入力から
生成するため、公開 API と同条件の比較になる。
"""

import json
from pathlib import Path

import pandas as pd

from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW
from src.services.process_assigner import _edf_list_schedule, assign_processes_by_arrival_time

_FIXTURE = Path(__file__).parent / "fixtures" / "issue_edf_20260820_v2.json"


def _load_case():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _hhmm_to_secs(value):
    s = str(value).strip()
    if not s or s.lower() == "nan":
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
        end = _hhmm_to_secs(row.get("実終了時間", "00:00"))
        deadline = mountain["deadline_secs"]
        finish_secs = max(finish_secs, end)
        if deadline is not None and end > int(deadline):
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


def _build_master(case):
    return pd.DataFrame(case["master_rows"])


def _build_proc_details(case):
    return pd.DataFrame(case["proc_rows"])


def _lane_floors(case):
    return {lane: int(case["lane_floors"][lane]) for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW)}


def _edf_yamas(case):
    return [
        {**m, "日野便番号セット": set(m.get("日野便番号セット") or [])}
        for m in case["mountains"]
    ]


def test_assign_processes_by_arrival_time_should_not_worsen_edf_candidate():
    case = _load_case()

    result = assign_processes_by_arrival_time(
        _build_proc_details(case),
        _build_master(case),
        previous_lane_end_times=_lane_floors(case),
    )

    edf_candidate = _edf_list_schedule(
        _edf_yamas(case),
        _lane_floors(case),
        enabled_lanes=(PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW),
    )

    existing_score = _score_case(result, case)
    edf_score = _score_case(_edf_rows_to_result(edf_candidate["rows"]), case)

    assert existing_score <= edf_score, (
        f"assign_processes_by_arrival_time が EDF候補を劣化させています: "
        f"existing={existing_score}, edf={edf_score}"
    )


def test_assign_processes_by_arrival_time_meets_absolute_criteria():
    """公開 API の出力が絶対合格基準を満たすことを検証。"""
    case = _load_case()

    result = assign_processes_by_arrival_time(
        _build_proc_details(case),
        _build_master(case),
        previous_lane_end_times=_lane_floors(case),
    )

    rows = result.to_dict(orient="records")
    by_yama = {int(r["山通番"]): r for r in rows}

    # (1) 締切超過件数 ≤ 2
    late_count = 0
    for mountain in case["mountains"]:
        yama_no = int(mountain["yama_no"])
        row = by_yama.get(yama_no)
        if row is None:
            continue
        end = _hhmm_to_secs(row.get("実終了時間", "00:00"))
        deadline = mountain["deadline_secs"]
        if deadline is not None and end > int(deadline):
            late_count += 1

    assert late_count <= 2, f"締切超過件数が基準を超過: {late_count} > 2"

    # (2) 全山完了時刻 ≤ 45000 (12:30)
    max_finish_secs = 0
    for mountain in case["mountains"]:
        yama_no = int(mountain["yama_no"])
        row = by_yama.get(yama_no)
        if row is None:
            continue
        end = _hhmm_to_secs(row.get("実終了時間", "00:00"))
        max_finish_secs = max(max_finish_secs, end)

    assert max_finish_secs <= 45000, (
        f"最終完了時刻が基準超過: {_secs_to_hhmm(max_finish_secs)} > 12:30"
    )

    # (3) リリーフレーンに 1 山以上
    relief_count = len([r for r in rows if str(r.get("山工程", "")) == PROC_RELIEF])
    assert relief_count >= 1, f"リリーフレーンが空: {relief_count} 山"

    # (4) 各レーンの開始時刻が床以上
    lane_floors = _lane_floors(case)
    for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        lane_rows = [r for r in rows if str(r.get("山工程", "")) == lane]
        floor = lane_floors[lane]
        for r in lane_rows:
            start = _hhmm_to_secs(r.get("実開始時間", "00:00"))
            assert start >= floor, (
                f"{lane}レーン 山{int(r['山通番'])}: 開始時刻 {r['実開始時間']} "
                f"< 床 {_secs_to_hhmm(floor)}"
            )

    # (5) 同一レーン内の直列性（開始時刻順に、前山完了 ≤ 次山開始）
    for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        lane_rows = [r for r in rows if str(r.get("山工程", "")) == lane]
        lane_rows.sort(key=lambda r: _hhmm_to_secs(r.get("実開始時間", "00:00")))
        for i in range(len(lane_rows) - 1):
            prev_row = lane_rows[i]
            next_row = lane_rows[i + 1]
            prev_end = _hhmm_to_secs(prev_row.get("実終了時間", "00:00"))
            next_start = _hhmm_to_secs(next_row.get("実開始時間", "00:00"))
            assert prev_end <= next_start, (
                f"{lane}レーン: 山{int(prev_row['山通番'])} 完了 {prev_row['実終了時間']} "
                f"> 山{int(next_row['山通番'])} 開始 {next_row['実開始時間']}"
            )
