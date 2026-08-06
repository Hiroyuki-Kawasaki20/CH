# -*- coding: utf-8 -*-
"""Issue #67: 前回終了時刻引き継ぎ（push_lane_end_times）へ渡る終了時刻の正当性検証

- 対象: assign_processes_by_arrival_time(..., return_lane_end_times=True) が返す
  lane_end_times（工程別終了時刻・int秒）
- 検証: 各レーンの終了時刻が「そのレーン最終山の実開始時間＋引取工数
  （休憩・照合180秒を含む実装計算）」と一致すること
- 実装本体（src/services/process_assigner.py）を経由。モック不使用。
- 実ファイル（入車時間マスタ.xlsx）は読まない。GUI（tkinter）も import しない。
"""
import pandas as pd

from src.models.constants import (
    BASE_ONE_TIME,
    MIDDLE_WORK,
    BASE_PER_PAL,
    PROC_MAIN,
    PROC_RELIEF,
    PROC_OVERFLOW,
)
from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    _calc_work_end_with_breaks,
    _time_to_seconds,
    _to_operational_timeline_secs,
)
from src.services.lane_end_times_history import (
    push_lane_end_times,
    select_lane_end_times,
)


# ──────────────────────── ヘルパー ────────────────────────

def _build_inputs(mountains, arrivals):
    """テスト入力を生成する。

    mountains: list[(山通番, 便番号2桁str, 移動工数, パレット数)]
    arrivals:  dict[便番号2桁str] = "HH:MM"（入車時間マスタ相当のDataFrameを生成）
    """
    rows = []
    for yama, bin_no, cost, pals in mountains:
        for _ in range(pals):
            rows.append({
                "山通番": yama,
                "納入先": "テスト社",
                "NONYUHIBIN": f"99{bin_no}",  # 末尾2桁が便番号として解釈される
                "移動工数": cost,
            })
    proc_details = pd.DataFrame(rows)
    master_df = pd.DataFrame([
        {"OData_納入先": "テスト社", "NONYUHIBIN": b, "入車時間": t}
        for b, t in arrivals.items()
    ])
    return proc_details, master_df


def _work_secs(cost, pals):
    """実装と同じ式で山の引取工数（秒）を再計算する。"""
    return int(round(cost + BASE_ONE_TIME + (pals - 1) * MIDDLE_WORK + pals * BASE_PER_PAL))


def _lane_rows_in_start_order(out_df, lane_label, work_map):
    """指定レーンの行を運用タイムライン秒の開始順に (start, end, row) で返す。"""
    items = []
    for _, r in out_df[out_df["山工程"] == lane_label].iterrows():
        st = _to_operational_timeline_secs(_time_to_seconds(str(r.get("実開始時間", ""))))
        if st is None:
            continue
        en = _calc_work_end_with_breaks(int(st), work_map[int(r["山通番"])])
        items.append((int(st), int(en), r))
    items.sort(key=lambda x: x[0])
    return items


def _run(mountains, arrivals, prev=None):
    proc_details, master_df = _build_inputs(mountains, arrivals)
    out_df, lane_end_times = assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times=prev,
        return_lane_end_times=True,
    )
    work_map = {y: _work_secs(c, p) for (y, b, c, p) in mountains}
    return out_df, lane_end_times, work_map


_GENEROUS_MOUNTAINS = [
    (1, "01", 60, 2),
    (2, "02", 60, 2),
    (3, "03", 60, 2),
    (4, "04", 60, 2),
]
_GENEROUS_ARRIVALS = {"01": "09:00", "02": "10:00", "03": "11:00", "04": "12:00"}


# ──────────────────────── テスト本体 ────────────────────────

class TestLaneEndTimesVerification:
    """Issue #67 ①: push_lane_end_times へ渡る終了時刻の正当性"""

    def test_lane_end_times_equals_last_mountain_end(self):
        """全レーンで lane_end_times = 最終山の開始＋引取工数（再計算値）と一致する。"""
        out_df, lane_end_times, work_map = _run(_GENEROUS_MOUNTAINS, _GENEROUS_ARRIVALS)

        for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
            items = _lane_rows_in_start_order(out_df, lane, work_map)
            if items:
                expected = max(en for _, en, _ in items)
                assert lane_end_times[lane] == expected, (
                    f"{lane}: pushされる終了時刻 {lane_end_times[lane]} が"
                    f" 開始+工数から再計算した {expected} と不一致"
                )
            else:
                assert lane_end_times[lane] == 0, f"{lane}: 山なしレーンは0であるべき"

    def test_serial_chain_and_inspection_delay(self):
        """レーン内で山が重ならず、3,5,7…山目の前に照合180秒が確保される。"""
        out_df, lane_end_times, work_map = _run(_GENEROUS_MOUNTAINS, _GENEROUS_ARRIVALS)
        items = _lane_rows_in_start_order(out_df, PROC_MAIN, work_map)
        assert len(items) >= 3, "前提: 3山以上がメイン工程に残ること"

        for idx in range(1, len(items)):
            delay = 180 if (idx >= 2 and idx % 2 == 0) else 0
            prev_end = items[idx - 1][1]
            start = items[idx][0]
            assert start >= prev_end + delay, (
                f"{idx + 1}山目の開始 {start} が 前山完了 {prev_end}+照合{delay}秒 より早い"
            )

        flags = [bool(r.get("照合追加180秒", False)) for _, _, r in items]
        for idx, flag in enumerate(flags):
            expected_flag = (idx >= 2 and idx % 2 == 0)
            assert flag == expected_flag, (
                f"開始順{idx + 1}山目の照合追加180秒フラグが {flag}（期待: {expected_flag}）"
            )

    def test_lane_end_times_roundtrip_via_history(self):
        """lane_end_times を push → select「最新」で取り出すと同一値が返る。"""
        _, lane_end_times, _ = _run(_GENEROUS_MOUNTAINS, _GENEROUS_ARRIVALS)
        history = push_lane_end_times([], dict(lane_end_times))
        restored = select_lane_end_times(history, "最新")
        assert restored == lane_end_times
