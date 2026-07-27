# -*- coding: utf-8 -*-
"""Issue #36: メイン/リリーフ/あふれ3レーン同時発生時のレーン内直列化(時間重複ゼロ)回帰テスト。

設計方針:
- 実マスタxlsxに依存しない(合成DataFrameのみ使用。Issue #34の教訓)。
- 各山は1パレット・単一納入先×単一便とし、分割救済(_can_relief_if_split)を不能にする。
- 3レーンが同時発生しない場合はテスト失敗とする(空振り=INCONCLUSIVE禁止)。
- 表示は分丸め(HH:MM)のため、重複判定は60秒の丸め誤差のみ許容する(Issue #36 v5検証ロジック準拠)。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from src.services.process_assigner import (
    _calc_work_end_with_breaks,
    _time_to_seconds,
    assign_processes_by_arrival_time,
    compute_proc_details,
)
from src.models.constants import (
    BASE_ONE_TIME,
    BASE_PER_PAL,
    MIDDLE_WORK,
    PROC_MAIN,
    PROC_OVERFLOW,
    PROC_RELIEF,
)

ROUNDING_TOLERANCE_SECS = 60


def _work_secs(cost: float, pal: int = 1) -> int:
    return int(np.round(cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0))


def _cost_for_work_secs(target_secs: int, pal: int = 1) -> float:
    base = BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL)
    return float(max(0.0, target_secs - base))


def _build_three_lane_case():
    cost_30min = _cost_for_work_secs(30 * 60)
    df = pd.DataFrame({
        "山通番": [1, 2, 3, 4, 5, 6],
        "移動工数": [cost_30min, cost_30min, cost_30min, cost_30min, 0.0, 0.0],
        "納入先": ["B", "C", "A", "G", "E", "F"],
        "NONYUHIBIN": ["02", "02", "02", "02", "02", "02"],
        "高さ": [300, 300, 300, 300, 300, 300],
    })
    master_df = pd.DataFrame({
        "OData_納入先": ["B", "B", "C", "C", "A", "A", "G", "G", "E", "E", "F", "F"],
        "NONYUHIBIN": ["01", "02", "01", "02", "01", "02", "01", "02", "01", "02", "01", "02"],
        "入車時間": [
            "13:00", "14:00",
            "13:00", "14:00",
            "13:30", "14:20",
            "13:30", "14:20",
            "14:00", "14:05",
            "15:00", "15:05",
        ],
        "セットありフラグ": ["0"] * 12,
    })
    return df, master_df


def test_issue36_three_lanes_occur_and_are_serialized_without_overlap():
    df, master_df = _build_three_lane_case()
    out_df = assign_processes_by_arrival_time(compute_proc_details(df), master_df)

    lanes = set(out_df["山工程"].tolist())
    assert {PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW} <= lanes, (
        f"3レーン同時発生が再現できていない(テスト前提崩れ): {lanes}"
    )

    work_map = {}
    for yama, sub in df.groupby("山通番"):
        pal = int(sub.shape[0])
        cost = float(pd.to_numeric(sub["移動工数"], errors="coerce").max())
        work_map[int(yama)] = _work_secs(cost, pal)

    for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        rows = out_df[out_df["山工程"] == lane]
        recs = []
        for _, r in rows.iterrows():
            st = _time_to_seconds(str(r["実開始時間"]))
            assert st is not None, f"[{lane}] 山{r['山通番']} の実開始時間が不正: {r['実開始時間']}"
            en = int(_calc_work_end_with_breaks(int(st), work_map[int(r["山通番"])]))
            recs.append((int(r["山通番"]), int(st), en))
        recs.sort(key=lambda t: t[1])

        for (y1, s1, e1), (y2, s2, e2) in zip(recs, recs[1:]):
            assert s2 + ROUNDING_TOLERANCE_SECS >= e1, (
                f"[{lane}] 時間重複: 山{y1}(終{e1}秒) > 山{y2}(始{s2}秒) 差{e1 - s2}秒"
            )
            assert s2 >= s1, f"[{lane}] 開始時刻の単調増加違反: 山{y1}→山{y2}"
