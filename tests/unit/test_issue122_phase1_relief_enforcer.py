# -*- coding: utf-8 -*-
"""Issue #122 Phase 1: 絶対締切(入車-20分)の強制退避の回帰テスト。

題材は 2026-09-03 08:42 バッチの実データ。織機04便(入車10:30・セットあり)は
§4.3の緩和で内部締切が15:20となり、メイン工程で12:16完了でも是正されなかった。
"""

from src.models.constants import PROC_MAIN, PROC_OVERFLOW, PROC_RELIEF
from src.services.process_assigner import (
    _adjust_start_for_breaks,
    _breaks_for_proc,
    _calc_work_end_with_breaks,
    _seconds_to_hhmm,
    _time_to_seconds,
)
from src.services.relief_enforcer import ReliefEnforcementContext

DAY = 86400
ORIKI_04_DEADLINE = 10 * 3600 + 10 * 60   # 入車10:30 - 20分
ORIKI_04_FLOOR = 8 * 3600 + 40 * 60       # 前便(織機03 08:30) + 10分
HINO_13_DEADLINE = 11 * 3600 + 45 * 60    # 入車12:05 - 20分

WORK = {1: 500, 5: 256, 8: 664}
STRICT = {1: HINO_13_DEADLINE, 5: ORIKI_04_DEADLINE, 8: ORIKI_04_DEADLINE}
FLOOR = {1: 0, 5: ORIKI_04_FLOOR, 8: ORIKI_04_FLOOR}


def _deadline_for_eval(deadline_val, ref_secs):
    if deadline_val is None:
        return None
    ddl = int(deadline_val)
    if ref_secs is not None and int(ref_secs) >= DAY and ddl < DAY:
        return ddl + DAY
    return ddl


def _schedule_lane(rows, proc_label, prefer_deadline_order=False,
                   respect_existing_start=True, lane_floor_secs=None):
    """本番の _schedule_proc_rows と同じ責務の簡易版(締切優先・順次詰め)。"""
    breaks = _breaks_for_proc(proc_label)
    ordered = sorted(rows, key=lambda r: (STRICT.get(int(r["山通番"])) or float("inf"),
                                          int(r["山通番"])))
    prev_end = int(lane_floor_secs or 0)
    for idx, row in enumerate(ordered):
        yama_no = int(row["山通番"])
        work = int(WORK.get(yama_no, 0))
        inspection = 180 if (idx >= 2 and idx % 2 == 0) else 0
        candidate = max(prev_end + inspection, int(FLOOR.get(yama_no, 0)))
        start = _adjust_start_for_breaks(candidate, work, breaks)
        row["実開始時間"] = _seconds_to_hhmm(start)
        prev_end = _calc_work_end_with_breaks(start, work, breaks)
        row["_end_secs"] = int(prev_end)
        row["照合追加180秒"] = bool(inspection)


def _context():
    return ReliefEnforcementContext(
        proc_main=PROC_MAIN,
        proc_relief=PROC_RELIEF,
        proc_overflow=PROC_OVERFLOW,
        strict_deadline_map=STRICT,
        work_map=WORK,
        arrival_floor_map=FLOOR,
        start_floor_map=FLOOR,
        lane_floor_map={PROC_MAIN: 0, PROC_RELIEF: 0, PROC_OVERFLOW: 0},
        schedule_lane=_schedule_lane,
        adjust_start=_adjust_start_for_breaks,
        calc_end=_calc_work_end_with_breaks,
        breaks_for_proc=_breaks_for_proc,
        deadline_for_eval=_deadline_for_eval,
        time_to_secs=_time_to_seconds,
        seconds_to_hhmm=_seconds_to_hhmm,
    )


def _row(yama_no, proc, start_hhmm):
    return {"山通番": yama_no, "山工程": proc, "実開始時間": start_hhmm,
            "前倒し": False, "照合追加180秒": False}


def test_oriki04_late_on_main_is_evacuated_to_relief():
    """実データ再現: 織機04の2山がメインで超過 → リリーフへ退避し超過0件。"""
    rows = [
        _row(1, PROC_MAIN, "09:43"),   # 日野13: 締切11:45 に間に合う
        _row(5, PROC_MAIN, "10:18"),   # 織機04: 10:22完了 → 絶対締切10:10超過
        _row(8, PROC_MAIN, "12:05"),   # 織機04: 12:16完了 → 入車後(致命)
    ]
    ctx = _context()
    assert ctx.late_yamas(rows, only_proc=PROC_MAIN) == {5, 8}   # 修正前の状態

    assert ctx.enforce(rows) is True

    assert ctx.late_yamas(rows, only_proc=PROC_MAIN) == set()    # メインに超過なし
    assert ctx.late_yamas(rows) == set()                         # 全レーンで超過0件
    moved = {int(r["山通番"]): r["山工程"] for r in rows if int(r["山通番"]) in (5, 8)}
    assert moved == {5: PROC_RELIEF, 8: PROC_RELIEF}
    assert next(r for r in rows if int(r["山通番"]) == 1)["山工程"] == PROC_MAIN


def test_on_time_main_rows_are_untouched():
    """間に合っている山は一切動かさない(過剰なリリーフ化をしない)。"""
    rows = [_row(1, PROC_MAIN, "09:43")]
    ctx = _context()
    assert ctx.enforce(rows) is False
    assert rows[0]["山工程"] == PROC_MAIN
    assert rows[0]["実開始時間"] == "09:43"


def test_unrescuable_yama_never_stays_on_main():
    """どのレーンでも救えない山も、メインには残さない(業務要件)。"""
    rows = [_row(8, PROC_MAIN, "12:05")]
    ctx = ReliefEnforcementContext(**{
        **_context().__dict__,
        "strict_deadline_map": {8: 7 * 3600},   # 07:00 = 床より前で救済不能
    })
    ctx.enforce(rows)
    assert rows[0]["山工程"] in (PROC_RELIEF, PROC_OVERFLOW)