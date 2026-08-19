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


class TestRegression20260805:
    """Issue #67 ②: 2026-08-05 実運用パターンの簡略化回帰テスト

    旧実装（PR #65 以前）は締切超過時に山を重ね置きし、過小な終了時刻
    （実際23:09のところ20:12）を履歴へ保存していた（履歴汚染）。
    現行実装では常に後ろ倒しされ、pushされる終了時刻は正直な最終完了時刻になる。
    """

    def test_no_compressed_end_times_under_heavy_evening_load(self):
        """夜間高負荷（山が締切に収まらない状況）でも、
        ①レーン内で山が重ならない ②pushされる終了時刻が圧縮されない。"""
        mountains = [
            (1, "01", 1800, 4),
            (2, "02", 1800, 4),
            (3, "03", 1800, 4),
            (4, "04", 1800, 4),
        ]
        arrivals = {"01": "21:30", "02": "21:50", "03": "22:10", "04": "22:30"}
        out_df, lane_end_times, work_map = _run(mountains, arrivals)

        for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
            items = _lane_rows_in_start_order(out_df, lane, work_map)
            # ① 重ね置き（旧バグ）の再発防止
            for idx in range(1, len(items)):
                assert items[idx][0] >= items[idx - 1][1], (
                    f"{lane}: 山が時間的に重なっている（旧バグの再発）"
                )
            # ② pushされる終了時刻 = 実際の最終完了時刻（圧縮なし）
            if items:
                assert lane_end_times[lane] == max(en for _, en, _ in items), (
                    f"{lane}: 履歴へ渡る終了時刻が実際の最終完了時刻と不一致（履歴汚染の温床）"
                )

    def test_previous_end_time_floor_is_respected(self):
        """前回終了時刻（previous_lane_end_times）より前にメイン工程の山が
        開始しないこと（回またぎ割り込みの直接検証）。

        ※ このテストが失敗した場合、最適化フェーズで前回終了時刻の床値が
           失われる実装バグの可能性がある。テストを弱めず失敗内容を報告すること。

        ※ Issue #83 修正で前回終了時刻が探索フェーズにも正しく反映されるようになった。
           本フィクスチャは床23:09を守る限りどのレーンでも締切23:30に間に合わない
           （休憩跨ぎで終了23:45）ため、旧アサーションの「メイン配置」は探索が床を
           無視していたバグによってのみ成立していた。本来の検証意図（前回終了時刻の
           床の尊重）に合わせ、全レーン床＋レーン不問の開始下限検証へ更新した。
        """
        prev_main_end = 23 * 3600 + 9 * 60  # 23:09（2026-08-05 の実測最終完了時刻）
        mountains = [(1, "01", 60, 1)]
        arrivals = {"01": "23:50"}
        out_df, lane_end_times, work_map = _run(
            mountains, arrivals,
            prev={
                PROC_MAIN: prev_main_end,
                PROC_RELIEF: prev_main_end,
                PROC_OVERFLOW: prev_main_end,
            },
        )
        assert not out_df.empty
        for _, row in out_df.iterrows():
            start = _to_operational_timeline_secs(_time_to_seconds(str(row["実開始時間"])))
            assert start >= prev_main_end, (
                f"山{int(row['山通番'])}({row['山工程']})が前回終了(23:09)より前に開始: "
                f"{row['実開始時間']}"
            )
            assert bool(row.get("締切超過", False))
