# -*- coding: utf-8 -*-
"""Issue #122 Phase 1 — 絶対締切(入車-20分)に間に合わない山をリリーフへ強制退避。

背景
----
process_assigner の締切は docs/仕分け・割り振りルール.md §4.3「セットあり便の
締切補正」により effective_deadline = max(入車-20分, 直ごとのメイン工程上限)
へ緩められる(1直=15:20)。このため織機04便(入車10:30・セットあり)のように
「15:20 までに終わればよい」と評価され、メイン工程の後方へ押し出されても
既存の安全弁 _enforce_main_deadline_strict() が発火しなかった(原因1・原因3)。

現場運用では入車時刻を過ぎた引取は積み込めない。本モジュールは緩和前の
絶対締切(strict deadline = 入車-20分)を基準に「メイン工程では間に合わない山」を
検出し、必ずリリーフ(不可ならあふれ)へ退避させる。メインには残さない。

設計方針
--------
- process_assigner._legacy_assign_processes_by_arrival_time() の内部状態
  (工数/締切/床/レーン再スケジュール関数)へ依存しないよう、必要な参照は
  すべて呼び出し側から注入する。単体テスト可能な純ロジックとして保つ。
- 既存の「締切超過」表示判定(緩和後の締切)には手を入れない。本モジュールが
  変えるのは "どのレーンに置くか" だけ。
- 退避により他山が新たに絶対締切を割る場合、その退避先は採用しない。
"""

from typing import Callable, Dict, List, Optional, Set
import copy
import logging

_logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 3


def _reset_row_to_lane(row: dict, proc_label: str) -> None:
    """レーン変更に伴い、時刻・アンカー・照合フラグを初期化する。"""
    row["山工程"] = proc_label
    row["実開始時間"] = ""
    row["前倒し"] = False
    row["照合追加180秒"] = False
    row["_is_anchored"] = False


class ReliefEnforcementContext:
    """絶対締切の判定と強制退避に必要な依存を保持するコンテナ。"""

    def __init__(
        self,
        *,
        proc_main: str,
        proc_relief: str,
        proc_overflow: str,
        strict_deadline_map: Dict[int, Optional[int]],
        work_map: Dict[int, int],
        arrival_floor_map: Dict[int, int],
        start_floor_map: Dict[int, Optional[int]],
        lane_floor_map: Dict[str, int],
        schedule_lane: Callable,
        adjust_start: Callable,
        calc_end: Callable,
        breaks_for_proc: Callable,
        deadline_for_eval: Callable,
        time_to_secs: Callable,
        seconds_to_hhmm: Callable,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.proc_main = proc_main
        self.proc_relief = proc_relief
        self.proc_overflow = proc_overflow
        self.strict_deadline_map = strict_deadline_map
        self.work_map = work_map
        self.arrival_floor_map = arrival_floor_map
        self.start_floor_map = start_floor_map
        self.lane_floor_map = lane_floor_map
        self.schedule_lane = schedule_lane
        self.adjust_start = adjust_start
        self.calc_end = calc_end
        self.breaks_for_proc = breaks_for_proc
        self.deadline_for_eval = deadline_for_eval
        self.time_to_secs = time_to_secs
        self.seconds_to_hhmm = seconds_to_hhmm
        self.logger = logger or _logger

    # ── 判定 ──────────────────────────────────────────────
    def start_secs(self, row: dict) -> Optional[int]:
        start = self.time_to_secs(str(row.get("実開始時間", "")))
        return None if start is None else int(start)

    def end_secs(self, row: dict) -> Optional[int]:
        start = self.start_secs(row)
        if start is None:
            return None
        yama_no = int(row["山通番"])
        return int(self.calc_end(
            start,
            int(self.work_map.get(yama_no, 0)),
            self.breaks_for_proc(str(row.get("山工程", ""))),
        ))

    def late_yamas(self, rows: List[dict], only_proc: Optional[str] = None) -> Set[int]:
        """絶対締切(入車-20分)を割っている山通番の集合を返す。"""
        late: Set[int] = set()
        for row in rows:
            proc = str(row.get("山工程", ""))
            if only_proc is not None and proc != only_proc:
                continue
            yama_no = int(row["山通番"])
            strict = self.strict_deadline_map.get(yama_no)
            if strict is None:
                continue
            start = self.start_secs(row)
            end = self.end_secs(row)
            if start is None or end is None:
                continue
            strict_eval = self.deadline_for_eval(int(strict), start)
            if strict_eval is not None and end > int(strict_eval):
                late.add(yama_no)
        return late

    # ── 退避 ──────────────────────────────────────────────
    def _trial(self, rows: List[dict], yama_no: int, lane: str) -> Optional[List[dict]]:
        """対象山を lane へ移した試行を返す(元 rows は変更しない)。"""
        trial = copy.deepcopy(rows)
        target = next((r for r in trial if int(r["山通番"]) == int(yama_no)), None)
        if target is None:
            return None
        _reset_row_to_lane(target, lane)
        work = int(self.work_map.get(int(yama_no), 0))

        if lane == self.proc_relief:
            # リリーフは締切優先で全山を再配置(既存の再スケジュールと同一経路)。
            relief_rows = [r for r in trial if str(r.get("山工程", "")) == self.proc_relief]
            self.schedule_lane(
                relief_rows,
                self.proc_relief,
                prefer_deadline_order=True,
                lane_floor_secs=int(self.lane_floor_map.get(self.proc_relief, 0) or 0),
            )
        else:
            # あふれは既存実装と同じく「前便入車+10分」の床起点で置く。
            floor = max(
                int(self.arrival_floor_map.get(int(yama_no)) or 0),
                int(self.start_floor_map.get(int(yama_no)) or 0),
                int(self.lane_floor_map.get(lane, 0) or 0),
            )
            breaks = self.breaks_for_proc(lane)
            start = int(self.adjust_start(floor, work, breaks))
            target["実開始時間"] = self.seconds_to_hhmm(start)
            target["_end_secs"] = int(self.calc_end(start, work, breaks))

        if self.start_secs(target) is None:
            return None
        return trial

    def enforce_once(self, rows: List[dict]) -> bool:
        """メイン工程に残った絶対締切超過の山を退避させる。1周分。"""
        main_late = self.late_yamas(rows, only_proc=self.proc_main)
        if not main_late:
            return False

        ordered = sorted(
            main_late,
            key=lambda y: (self.strict_deadline_map.get(y) or float("inf"), int(y)),
        )
        changed = False
        for yama_no in ordered:
            row = next((r for r in rows if int(r["山通番"]) == int(yama_no)), None)
            if row is None or str(row.get("山工程", "")) != self.proc_main:
                continue  # 直前の退避で解消済み

            before = self.late_yamas(rows)
            trials = []
            for lane in (self.proc_relief, self.proc_overflow):
                trial = self._trial(rows, yama_no, lane)
                if trial is None:
                    continue
                trials.append((lane, trial, self.late_yamas(trial)))
            if not trials:
                continue

            # ① 対象山を救済でき、他山を新たに割らない退避先(リリーフ優先)
            rescued = [t for t in trials if int(yama_no) not in t[2] and not (t[2] - before)]
            if rescued:
                lane, trial, after = rescued[0]
                self.logger.info(
                    "[PHASE1] evacuate yama=%s lane=%s strict_late=%s->%s",
                    yama_no, lane, sorted(before), sorted(after),
                )
            else:
                # ② 完全救済不能でもメインには残さない(超過最小・リリーフ優先)
                lane, trial, after = min(
                    trials,
                    key=lambda t: (len(t[2]), 0 if t[0] == self.proc_relief else 1),
                )
                self.logger.warning(
                    "[PHASE1] forced evacuation (not fully rescued) yama=%s lane=%s "
                    "strict_late=%s->%s",
                    yama_no, lane, sorted(before), sorted(after),
                )
            rows[:] = trial
            changed = True
        return changed

    def enforce(
        self,
        rows: List[dict],
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        serialize_lanes: Optional[Callable] = None,
    ) -> bool:
        """退避と直列化が安定するまで繰り返す。"""
        changed_any = False
        for _ in range(max(1, int(max_rounds))):
            if not self.enforce_once(rows):
                break
            changed_any = True
            if serialize_lanes is not None:
                serialize_lanes(rows)
        return changed_any


def enforce_until_stable(
    rows: List[dict],
    *,
    serialize_lanes: Optional[Callable] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    **dependencies,
) -> bool:
    """process_assigner から呼ぶ薄いエントリ。変更があれば True。"""
    context = ReliefEnforcementContext(**dependencies)
    return context.enforce(rows, max_rounds=max_rounds, serialize_lanes=serialize_lanes)