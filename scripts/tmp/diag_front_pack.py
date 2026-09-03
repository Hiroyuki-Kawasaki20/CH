# -*- coding: utf-8 -*-
"""前詰めあふれ山 診断スクリプト

目的: あふれ山が空き窓へ前詰めされない理由を計測する
対象: src/services/process_assigner.py の前詰めロジック
方法: assign_processes_by_arrival_time に front_pack_diag 診断リストを渡す

出力:
(a) レーン別（メイン/リリーフ/あふれ）に「山通番・実開始時間・引取工数・
    終了時刻・締切・締切超過」を開始時刻昇順で全件
(b) 各レーンの空き窓一覧（開始・終了・長さ秒）
(c) diag の全要素（山通番, レーン, 判定名, 可否, 理由）を1行1件で全件
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.constants import PROC_MAIN, PROC_OVERFLOW, PROC_RELIEF
from src.services.process_assigner import (
    _calc_work_end_with_breaks,
    _time_to_seconds,
    compute_proc_details,
    assign_processes_by_arrival_time,
)


def _build_test_fixture_2026_08_28() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """2026-08-28 用テストフィクスチャを構築
    
    目的: あふれ山を確実に生成する
    - 入車時間: 04:00（メイン/リリーフ出勤の基準時刻）
    - メイン容量を満杯にして、あふれが発生するように調整
    """
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            # 移動工数: メイン容量を満杯にするため大型山を複数配置
            # 参考: 標準的な工数は 600-1200 秒
            "移動工数": [3600, 3600, 3600, 3600, 3600, 3600, 1800, 1800, 1800, 1800],
            "納入先": ["武部"] * 10,
            "NONYUHIBIN": ["01"] * 10,
            "高さ": [300] * 10,
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["武部"],
            "NONYUHIBIN": ["01"],
            "入車時間": ["04:00"],  # メイン/リリーフ出勤時刻
        }
    )
    return compute_proc_details(raw_df), master_df


def _extract_idle_gaps(df: pd.DataFrame, proc_label: str, max_day_secs: int = 86400) -> List[Tuple[int, int, int]]:
    """指定レーンの空き窓一覧を抽出
    
    Args:
        df: 結果データフレーム
        proc_label: レーン（PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW）
        max_day_secs: 営業日の最大秒数
    
    Returns:
        [(開始秒, 終了秒, 長さ秒), ...] のリスト
    """
    sub = df[df["山工程"].astype(str) == proc_label].copy()
    if sub.empty:
        return [(0, max_day_secs, max_day_secs)]
    
    gaps = []
    sub_sorted = sub.sort_values("実開始時間").reset_index(drop=True)
    
    occupied = []
    for _, row in sub_sorted.iterrows():
        st_str = str(row.get("実開始時間", ""))
        work_sec = int(row.get("引取工数_秒", 0))
        st = _time_to_seconds(st_str)
        if st is None:
            continue
        en = _calc_work_end_with_breaks(int(st), work_sec)
        occupied.append((int(st), en))
    
    if not occupied:
        return [(0, max_day_secs, max_day_secs)]
    
    occupied.sort()
    
    # 最初の空き窓
    if occupied[0][0] > 0:
        gaps.append((0, occupied[0][0], occupied[0][0]))
    
    # 中間の空き窓
    for i in range(len(occupied) - 1):
        gap_start = occupied[i][1]
        gap_end = occupied[i + 1][0]
        if gap_end > gap_start:
            gaps.append((gap_start, gap_end, gap_end - gap_start))
    
    # 最後の空き窓
    if occupied[-1][1] < max_day_secs:
        gaps.append((occupied[-1][1], max_day_secs, max_day_secs - occupied[-1][1]))
    
    return gaps


def _format_time(secs: Optional[int]) -> str:
    """秒から HH:MM 形式への変換"""
    if secs is None:
        return "不明"
    s = int(secs) % 86400
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"


def main():
    print("=" * 80)
    print("## 前詰めあふれ山 診断スクリプト (2026-08-28)")
    print("=" * 80)
    
    # フィクスチャ構築
    print("\n[フィクスチャ構築]")
    proc_details, master_df = _build_test_fixture_2026_08_28()
    print(f"山: {len(proc_details)} 件")
    print(f"マスタ: {len(master_df)} 件")
    
    # 診断リスト初期化
    diag: List[Tuple[int, str, str, bool, str]] = []
    
    # プロセス割り当て実行
    print("\n[プロセス割り当て実行]")
    result_df = assign_processes_by_arrival_time(proc_details, master_df, front_pack_diag=diag)
    print(f"結果: {len(result_df)} 件")
    print(f"診断記録: {len(diag)} 件")
    
    # (a) レーン別山一覧
    print("\n" + "=" * 80)
    print("## (a) レーン別 山一覧")
    print("=" * 80)
    
    for lane in [PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW]:
        print(f"\n### {lane} レーン")
        sub = result_df[result_df["山工程"].astype(str) == lane].copy()
        if sub.empty:
            print("（該当なし）")
            continue
        
        sub = sub.sort_values("実開始時間").reset_index(drop=True)
        
        print("山通番 | 実開始時間 | 引取工数（秒） | 終了時刻 | 締切 | 超過 ")
        print("-" * 80)
        for _, row in sub.iterrows():
            yama = int(row.get("山通番", 0))
            start_str = str(row.get("実開始時間", ""))
            work_sec = int(row.get("引取工数_秒", 0))
            st = _time_to_seconds(start_str)
            if st is None:
                end_str = "不明"
            else:
                en = _calc_work_end_with_breaks(int(st), work_sec)
                end_str = _format_time(en)
            
            ddl_str = str(row.get("締切", "不明"))
            ddl_sec = _time_to_seconds(ddl_str) if isinstance(ddl_str, str) else None
            
            if st is not None and ddl_sec is not None:
                en = _calc_work_end_with_breaks(int(st), work_sec)
                over = "◎" if en <= ddl_sec else "✗"
            else:
                over = "？"
            
            print(f"{yama:4d} | {start_str:10s} | {work_sec:13d} | {end_str:8s} | {ddl_str:8s} | {over}")
    
    # (b) 各レーンの空き窓一覧
    print("\n" + "=" * 80)
    print("## (b) 各レーンの空き窓一覧")
    print("=" * 80)
    
    for lane in [PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW]:
        print(f"\n### {lane} レーン")
        gaps = _extract_idle_gaps(result_df, lane)
        if not gaps:
            print("（空き窓なし）")
            continue
        
        print("開始 | 終了 | 長さ（秒）")
        print("-" * 80)
        for gap_start, gap_end, gap_len in gaps:
            start_fmt = _format_time(gap_start)
            end_fmt = _format_time(gap_end)
            print(f"{start_fmt:8s} | {end_fmt:8s} | {gap_len:8d}")
    
    # (c) diag 全要素
    print("\n" + "=" * 80)
    print("## (c) 診断リスト (front_pack_diag) 全要素")
    print("=" * 80)
    
    if not diag:
        print("（診断記録なし）")
    else:
        print(f"診断記録数: {len(diag)}")
        print()
        for idx, entry in enumerate(diag):
            print(f"### 記録 {idx}")
            print(f"raw: {entry}")
            if isinstance(entry, (tuple, list)):
                print(f"要素数: {len(entry)}")
                for i, elem in enumerate(entry):
                    print(f"  [{i}]: {elem}")
            print()
    
    print("\n" + "=" * 80)
    print("## 終了")
    print("=" * 80)


if __name__ == "__main__":
    main()
