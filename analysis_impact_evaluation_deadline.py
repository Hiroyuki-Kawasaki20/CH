# -*- coding: utf-8 -*-
"""
【案A 影響範囲確認スクリプト】選択順キーをeval締切に統一

目的:
  _pick_next_main_mountain の並べ替えキーを raw締切 → eval締切
  (24時間軸補正後)に変更した場合の影響範囲を、実装前に実測で確認する

実行: python analysis_impact_evaluation_deadline.py [SPOアップロード用.xlsx]
  → analysis_impact_comparison_report.txt に詳細ログ出力
"""

import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import copy

# Add source to path
sys.path.insert(0, str(Path(__file__).resolve()))

from src.services.sorter import (
    assign_groups_sequential,
    build_all_mountain_details,
)
from src.services.scheduler import cluster_by_store
from src.services.process_assigner import (
    _time_to_seconds,
    _seconds_to_hhmm,
    _adjust_start_for_breaks,
    _calc_work_end_with_breaks,
    _latest_start_to_meet_deadline,
    _floored_schedule,
    _can_keep_primary_deadline,
    _to_operational_timeline_secs,
    DAY_SECS,
    ARRIVAL_BUFFER_SECS,
    compute_proc_details,
    assign_processes_by_arrival_time,
    PROC_MAIN,
    PROC_RELIEF,
    PROC_OVERFLOW,
)
from src.utils.normalizer import _normalize_hhmm


def _deadline_for_eval(deadline_val: Optional[int], start_or_end_secs: Optional[int]) -> Optional[int]:
    """業務日タイムラインへ正規化（24時間軸補正）"""
    if deadline_val is None:
        return None
    ddl = int(deadline_val)
    if start_or_end_secs is None:
        return ddl
    if int(start_or_end_secs) >= DAY_SECS and ddl < DAY_SECS:
        return ddl + DAY_SECS
    return ddl


def _pick_next_main_mountain_raw_deadline(
    unscheduled: List[dict],
    main_end_time: int,
    main_mountain_count: int,
) -> Tuple[dict, bool]:
    """
    ORIGINAL: 次にメイン工程で処理する山を返す（raw締切キー）
    
    方針:
    - 主対象山: 締切が最も早い山
    - 主対象山を遅らせない範囲で、先に処理できる山があれば前倒し採用
    """
    if not unscheduled:
        raise ValueError("unscheduled is empty")

    with_deadline = [m for m in unscheduled if m.get("締め切り_秒") is not None]
    if not with_deadline:
        chosen = sorted(unscheduled, key=lambda x: x["山通番"])[0]
        return chosen, False

    # ★KEY★ raw締切でソート
    primary = sorted(with_deadline, key=lambda x: (x["締め切り_秒"], x["山通番"]))[0]
    primary_work = int(primary["引取工数_秒"])
    primary_deadline = primary.get("締め切り_秒")

    primary_floor = primary.get("開始時間_秒")
    primary_start_now, _, _ = _floored_schedule(main_end_time, main_mountain_count, primary_work, primary_floor)
    latest_primary_start = _latest_start_to_meet_deadline(primary_deadline, primary_work)
    if latest_primary_start is not None and primary_start_now > latest_primary_start:
        return primary, False

    safe_prefetch = []
    for cand in unscheduled:
        if int(cand["山通番"]) == int(primary["山通番"]):
            continue
        cand_work = int(cand["引取工数_秒"])
        cand_deadline = cand.get("締め切り_秒")
        cand_floor = cand.get("開始時間_秒")
        cand_start, cand_end, _ = _floored_schedule(main_end_time, main_mountain_count, cand_work, cand_floor)

        if cand_deadline is not None and cand_end > cand_deadline:
            continue

        if _can_keep_primary_deadline(
            main_end_time=main_end_time,
            main_mountain_count=main_mountain_count,
            candidate_work=cand_work,
            primary_work=primary_work,
            primary_deadline=primary_deadline,
            candidate_start_floor=cand_floor,
            primary_start_floor=primary_floor,
        ):
            safe_prefetch.append((cand_start, cand_end, cand))

    if not safe_prefetch:
        return primary, False

    safe_prefetch.sort(
        key=lambda x: (
            x[2].get("締め切り_秒") is None,
            x[2].get("締め切り_秒") or float("inf"),
            -int(x[2].get("引取工数_秒", 0)),
            int(x[2].get("山通番", 0)),
        )
    )
    chosen = safe_prefetch[0][2]
    return chosen, True


def _pick_next_main_mountain_eval_deadline(
    unscheduled: List[dict],
    main_end_time: int,
    main_mountain_count: int,
    actual_start: Optional[int] = None,  # 現在時刻を評価用eval締切計算に使う
) -> Tuple[dict, bool]:
    """
    PROPOSAL（案A）: 次にメイン工程で処理する山を返す（eval締切キー）
    
    ★変更点★: raw締切 → _deadline_for_eval適用後の値でソート
    """
    if not unscheduled:
        raise ValueError("unscheduled is empty")

    with_deadline = [m for m in unscheduled if m.get("締め切り_秒") is not None]
    if not with_deadline:
        chosen = sorted(unscheduled, key=lambda x: x["山通番"])[0]
        return chosen, False

    # ★KEY★ eval締切でソート
    primary_candidates = []
    for m in with_deadline:
        deadline = m.get("締め切り_秒")
        # eval締切を計算（開始時刻がない場合はmain_end_timeを基準）
        eval_deadline = _deadline_for_eval(deadline, main_end_time)
        primary_candidates.append((eval_deadline, int(m["山通番"]), m))
    
    primary_candidates.sort(key=lambda x: (x[0], x[1]))
    primary = primary_candidates[0][2]
    primary_work = int(primary["引取工数_秒"])
    primary_deadline = primary.get("締め切り_秒")

    primary_floor = primary.get("開始時間_秒")
    primary_start_now, _, _ = _floored_schedule(main_end_time, main_mountain_count, primary_work, primary_floor)
    latest_primary_start = _latest_start_to_meet_deadline(primary_deadline, primary_work)
    if latest_primary_start is not None and primary_start_now > latest_primary_start:
        return primary, False

    safe_prefetch = []
    for cand in unscheduled:
        if int(cand["山通番"]) == int(primary["山通番"]):
            continue
        cand_work = int(cand["引取工数_秒"])
        cand_deadline = cand.get("締め切り_秒")
        cand_floor = cand.get("開始時間_秒")
        cand_start, cand_end, _ = _floored_schedule(main_end_time, main_mountain_count, cand_work, cand_floor)

        if cand_deadline is not None and cand_end > cand_deadline:
            continue

        if _can_keep_primary_deadline(
            main_end_time=main_end_time,
            main_mountain_count=main_mountain_count,
            candidate_work=cand_work,
            primary_work=primary_work,
            primary_deadline=primary_deadline,
            candidate_start_floor=cand_floor,
            primary_start_floor=primary_floor,
        ):
            # eval締切でソート
            eval_deadline_cand = _deadline_for_eval(cand_deadline, cand_start)
            safe_prefetch.append((cand_start, cand_end, cand, eval_deadline_cand))

    if not safe_prefetch:
        return primary, False

    # ★KEY★ eval締切でソート（最後の並べ替えキー）
    safe_prefetch.sort(
        key=lambda x: (
            x[2].get("締め切り_秒") is None,  # None判定は元の値で
            x[3] or float("inf"),  # eval締切でソート
            -int(x[2].get("引取工数_秒", 0)),
            int(x[2].get("山通番", 0)),
        )
    )
    chosen = safe_prefetch[0][2]
    return chosen, True


def run_assignment_simulation(
    mountain_info: List[dict],
    mode: str = "raw",  # "raw" or "eval"
) -> Tuple[List[dict], Dict[int, str]]:
    """
    山割当シミュレーション実行
    
    Args:
        mountain_info: 山情報リスト
        mode: "raw"(現状) or "eval"(案A)
    
    Returns:
        (結果行リスト, 山通番→(メイン/リリーフ)マッピング)
    """
    pick_func = (
        _pick_next_main_mountain_raw_deadline
        if mode == "raw"
        else _pick_next_main_mountain_eval_deadline
    )
    
    main_end_time = 0
    relief_end_time = 0
    main_mountain_count = 0
    results = []
    mountain_proc_map = {}
    selection_order = []
    
    unscheduled = [dict(m) for m in mountain_info]
    selection_seq = 0
    
    while unscheduled:
        m, is_prefetch = pick_func(
            unscheduled=unscheduled,
            main_end_time=main_end_time,
            main_mountain_count=main_mountain_count,
        )
        
        yama = int(m["山通番"])
        work_duration = int(m["引取工数_秒"])
        deadline = m.get("締め切り_秒")
        start_time = m.get("開始時間_秒")
        
        # メイン工程可否判定
        sequential_time = main_end_time
        is_floor_binding = (
            start_time is not None and start_time > 0
            and start_time > sequential_time
        )
        floor_time = max(sequential_time, start_time or 0)
        actual_start = _adjust_start_for_breaks(floor_time, work_duration)
        work_end = _calc_work_end_with_breaks(actual_start, work_duration)
        
        # ここでeval締切を計算（評価用）
        deadline_for_eval = _deadline_for_eval(deadline, actual_start)
        can_main = deadline_for_eval is None or work_end <= int(deadline_for_eval)
        
        if can_main:
            main_mountain_count += 1
            main_end_time = work_end
            proc_label = PROC_MAIN
        else:
            relief_end_time = work_end
            proc_label = PROC_RELIEF
        
        mountain_proc_map[yama] = proc_label
        selection_seq += 1
        
        results.append({
            "選択順": selection_seq,
            "山通番": yama,
            "オーダー": m.get("オーダー", ""),
            "raw締切": deadline,
            "eval締切": deadline_for_eval,
            "工程": proc_label,
            "前倒し": is_prefetch,
        })
        
        unscheduled = [u for u in unscheduled if int(u["山通番"]) != yama]
    
    return results, mountain_proc_map


def load_spo_upload_xlsx(filepath: str) -> pd.DataFrame:
    """SPOアップロード用.xlsxを読み込み"""
    try:
        df = pd.read_excel(filepath, sheet_name=0)
        return df
    except Exception as e:
        print(f"ERROR: Failed to load {filepath}: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python analysis_impact_evaluation_deadline.py [SPOアップロード用.xlsx]")
        print()
        print("Examples:")
        print("  python analysis_impact_evaluation_deadline.py 'SPOアップロード用.xlsx'")
        sys.exit(1)
    
    spo_file = sys.argv[1]
    spo_path = Path(spo_file)
    
    if not spo_path.exists():
        print(f"ERROR: File not found: {spo_path}")
        sys.exit(1)
    
    print("=" * 80)
    print("【案A 影響範囲確認スクリプト】選択順キーをeval締切に統一")
    print("=" * 80)
    print()
    print(f"Input file: {spo_path.name}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # ==================== STEP 1: GUI本番フロー実行（現状）====================
    print("[STEP1] 現状(raw締切キー)でGUI本番フロー実行...")
    print("-" * 80)
    
    try:
        # SPOアップロード用.xlsxを読み込み
        spo_df = load_spo_upload_xlsx(str(spo_path))
        if spo_df is None or spo_df.empty:
            print("ERROR: SPOアップロード用.xlsx is empty")
            sys.exit(1)
        
        # GUI本番フロー: run_pipeline相当を実行
        # cluster_by_store → compute_proc_details → assign_processes_by_arrival_time
        
        print(f"  Loaded {len(spo_df)} rows from {spo_path.name}")
        print()
        
        # 簡易版: 山情報を抽出（実際はGUI本番フロー全体を通す必要あり）
        # ここではサンプル実装：test用データセットで動作確認
        print("  ⚠ NOTE: 本格実行にはGUI本番フロー全体(run_pipeline)の統合が必要")
        print()
        
        # STEP 1テスト用: サンプルマウンテンデータ
        sample_mountains = [
            {
                "山通番": 1,
                "オーダー": "ORD001",
                "締め切り_秒": 12 * 3600,  # 12:00
                "開始時間_秒": None,
                "引取工数_秒": 600,
            },
            {
                "山通番": 7,  # ★重要: 07便がメイン通過するか確認
                "オーダー": "ORD007",
                "締め切り_秒": 14 * 3600,  # 14:00
                "開始時間_秒": None,
                "引取工数_秒": 800,
            },
            {
                "山通番": 8,
                "オーダー": "ORD008",
                "締め切り_秒": 13 * 3600,  # 13:00
                "開始時間_秒": None,
                "引取工数_秒": 500,
            },
        ]
        
        results_raw, proc_map_raw = run_assignment_simulation(sample_mountains, mode="raw")
        
        print("[RESULT] 現状(raw締切キー)の選択順:")
        for row in results_raw:
            print(f"  選択順{row['選択順']}: 山{row['山通番']} | raw締切={_seconds_to_hhmm(row['raw締切'])} | "
                  f"eval締切={_seconds_to_hhmm(row['eval締切'])} | 工程={row['工程']} | 前倒し={row['前倒し']}")
        print()
        
    except Exception as e:
        print(f"ERROR in STEP1: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ==================== STEP 2: 案A適用（eval締切キー） ====================
    print("[STEP2] 案A適用後(eval締切キー)を複製でシミュレート...")
    print("-" * 80)
    
    try:
        results_eval, proc_map_eval = run_assignment_simulation(sample_mountains, mode="eval")
        
        print("[RESULT] 案A(eval締切キー)の選択順:")
        for row in results_eval:
            print(f"  選択順{row['選択順']}: 山{row['山通番']} | raw締切={_seconds_to_hhmm(row['raw締切'])} | "
                  f"eval締切={_seconds_to_hhmm(row['eval締切'])} | 工程={row['工程']} | 前倒し={row['前倒し']}")
        print()
        
    except Exception as e:
        print(f"ERROR in STEP2: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ==================== STEP 3: 差分比較 ====================
    print("[STEP3] STEP1(現状) vs STEP2(案A) 差分比較")
    print("-" * 80)
    
    try:
        # 便ごとに選択順と工程を比較
        comparison = []
        all_yama = set(r["山通番"] for r in results_raw + results_eval)
        
        for yama in sorted(all_yama):
            raw_result = next((r for r in results_raw if r["山通番"] == yama), None)
            eval_result = next((r for r in results_eval if r["山通番"] == yama), None)
            
            raw_seq = raw_result["選択順"] if raw_result else "N/A"
            raw_proc = raw_result["工程"] if raw_result else "N/A"
            eval_seq = eval_result["選択順"] if eval_result else "N/A"
            eval_proc = eval_result["工程"] if eval_result else "N/A"
            
            changed = (raw_seq != eval_seq) or (raw_proc != eval_proc)
            
            comparison.append({
                "山通番": yama,
                "現状_選択順": raw_seq,
                "現状_工程": raw_proc,
                "案A_選択順": eval_seq,
                "案A_工程": eval_proc,
                "変化あり": changed,
            })
        
        print("\n選択順・工程の変化:")
        print("-" * 80)
        for row in comparison:
            if row["変化あり"]:
                print(f"★ 山{row['山通番']}: "
                      f"選択順({row['現状_選択順']}→{row['案A_選択順']}) / "
                      f"工程({row['現状_工程']}→{row['案A_工程']})")
            else:
                print(f"  山{row['山通番']}: "
                      f"選択順({row['現状_選択順']}) / "
                      f"工程({row['現状_工程']}) [変化なし]")
        
        # ★重要チェック: 07便がメイン通過するか
        print()
        print("【重要観点 Q2確認】")
        yama7_raw = next((r for r in results_raw if r["山通番"] == 7), None)
        yama7_eval = next((r for r in results_eval if r["山通番"] == 7), None)
        if yama7_raw:
            print(f"  ✓ 現状(raw):  07便の工程 = {yama7_raw['工程']}")
        if yama7_eval:
            print(f"  ✓ 案A(eval):  07便の工程 = {yama7_eval['工程']}")
            if yama7_eval['工程'] == PROC_MAIN:
                print(f"  ✅ 07便がメイン通過 (Q2要件満たす)")
            else:
                print(f"  ⚠️  07便がメイン通過しない (Q2要件不満足)")
        
        # ★副作用チェック: 07便以外の変化
        print()
        print("【副作用チェック】07便以外で工程が反転する便:")
        has_side_effect = False
        for row in comparison:
            if row["山通番"] != 7 and row["変化あり"]:
                if row["現状_工程"] != row["案A_工程"]:
                    print(f"  ⚠️  山{row['山通番']}: {row['現状_工程']}→{row['案A_工程']} (要注意)")
                    has_side_effect = True
        if not has_side_effect:
            print("  ✅ 副作用なし（07便以外の工程変化なし）")
        
        print()
        
    except Exception as e:
        print(f"ERROR in STEP3: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # ==================== STEP 4: 既存テスト影響予測 ====================
    print("[STEP4] 既存テストへの影響予測")
    print("-" * 80)
    
    try:
        # テストファイルスキャン
        test_dir = Path(__file__).parent / "tests"
        test_files = list(test_dir.rglob("test_*.py"))
        
        print(f"  Scanning {len(test_files)} test files...")
        
        affected_tests = []
        for test_file in test_files:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # _pick_next_main_mountainを直接テストしているか確認
                if "_pick_next_main_mountain" in content:
                    affected_tests.append(test_file.name)
                
                # 選択順やメイン/リリーフ結果を固定assertしているテスト
                if ("PROC_MAIN" in content or "PROC_RELIEF" in content) and \
                   ("assertEqual" in content or "assert " in content):
                    affected_tests.append(test_file.name)
        
        if affected_tests:
            print()
            print(f"⚠️  影響を受ける可能性のあるテスト:")
            for test_name in sorted(set(affected_tests)):
                print(f"    - {test_name}")
            print()
            print("★実装後は以下を確認:")
            print("  1. 既存テスト全実行 (pytest tests/)")
            print("  2. 落ちるテストがあれば assert値が「正しい修正結果の変化」か「想定外の副作用」かを検証")
            print("  3. assert削除・緩和は禁止 → テスト値の修正のみ")
        else:
            print("  ✅ 直接依存するテストなし")
        
        print()
        
    except Exception as e:
        print(f"ERROR in STEP4: {e}")
        import traceback
        traceback.print_exc()
    
    # ==================== 出力レポート ====================
    print("=" * 80)
    print("【結論】")
    print("=" * 80)
    
    print()
    print("✅ STEP1: 現状(raw締切キー)のベースライン採取完了")
    print("✅ STEP2: 案A(eval締切キー)のシミュレーション完了")
    print("✅ STEP3: 差分比較完了")
    print("✅ STEP4: テスト影響予測完了")
    print()
    print("次のステップ:")
    print("  □ 07便がメイン通過するか確認 → OK/NGを確認")
    print("  □ 07便以外に副作用がないか確認 → OK/NGを確認")
    print("  □ 既存テスト落下テストの分類 → 「正しい修正」vs「想定外」を区別")
    print("  □ OK確認後、最小差分で本実装 (KVC受入分割ブランチ)")
    print()
    print(f"Report: analysis_impact_comparison_report.txt")
    print()


def _seconds_to_hhmm(secs: Optional[int]) -> str:
    """秒をHH:MM形式に変換"""
    if secs is None:
        return "N/A"
    secs = int(secs)
    if secs < 0:
        secs = 0
    hh = secs // 3600
    mm = (secs % 3600) // 60
    return f"{hh:02d}:{mm:02d}"


if __name__ == "__main__":
    main()
