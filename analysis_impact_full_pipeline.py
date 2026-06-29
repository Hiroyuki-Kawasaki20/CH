# -*- coding: utf-8 -*-
"""
【案A 影響範囲確認スクリプト】 実戦版
選択順キーをeval締切に統一した場合の影響を、実際のGUI本番フロー上で測定

実行:
  python analysis_impact_full_pipeline.py [SPOアップロード用.xlsx]
  
出力:
  - analysis_impact_comparison_detailed.txt : 差分レポート
  - analysis_impact_test_dependency.txt : テスト依存分析
"""

import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import copy

sys.path.insert(0, str(Path(__file__).resolve()))

from src.services.process_assigner import (
    PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW,
)


def analyze_test_dependency():
    """既存テストの依存性を詳細分析"""
    print("[STEP4詳細] 既存テストの依存性分析")
    print("=" * 80)
    
    test_dir = Path(__file__).parent / "tests"
    test_files = list(test_dir.rglob("test_*.py"))
    
    test_analysis = {
        "pick_next_main_mountain_direct": [],
        "proc_main_assert": [],
        "proc_relief_assert": [],
        "selection_order_related": [],
    }
    
    for test_file in sorted(test_files):
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # 各テストメソッドを抽出
            test_methods = []
            for i, line in enumerate(lines):
                if line.strip().startswith("def test_"):
                    test_methods.append((i + 1, line.split('(')[0].replace("def ", "")))
            
            # テストファイル内の各パターンを検索
            for line_no, line in enumerate(lines, 1):
                # パターン1: _pick_next_main_mountain を直接使用
                if "_pick_next_main_mountain" in line and not line.strip().startswith("#"):
                    test_analysis["pick_next_main_mountain_direct"].append({
                        "file": test_file.name,
                        "line": line_no,
                        "content": line.strip()[:80],
                    })
                
                # パターン2: PROC_MAIN のassert
                if "PROC_MAIN" in line and ("assert" in line or "==" in line) and not line.strip().startswith("#"):
                    test_analysis["proc_main_assert"].append({
                        "file": test_file.name,
                        "line": line_no,
                        "content": line.strip()[:80],
                    })
                
                # パターン3: PROC_RELIEF のassert
                if "PROC_RELIEF" in line and ("assert" in line or "==" in line) and not line.strip().startswith("#"):
                    test_analysis["proc_relief_assert"].append({
                        "file": test_file.name,
                        "line": line_no,
                        "content": line.strip()[:80],
                    })
                
                # パターン4: 選択順（インデックス、seq）関連
                if any(kw in line.lower() for kw in ["選択順", "sequence", "_idx", "sort", "order"]) and \
                   not line.strip().startswith("#") and ("assert" in line or "==" in line):
                    test_analysis["selection_order_related"].append({
                        "file": test_file.name,
                        "line": line_no,
                        "content": line.strip()[:80],
                    })
        
        except Exception as e:
            print(f"  WARNING: Failed to analyze {test_file.name}: {e}")
    
    return test_analysis


def generate_test_impact_report(test_analysis: dict) -> str:
    """テスト影響レポート生成"""
    report = []
    report.append("=" * 80)
    report.append("【STEP4詳細】既存テストへの影響分析")
    report.append("=" * 80)
    report.append("")
    
    # パターン1: 直接依存
    if test_analysis["pick_next_main_mountain_direct"]:
        report.append("【高リスク】_pick_next_main_mountain を直接テストするテスト")
        report.append("-" * 80)
        for item in test_analysis["pick_next_main_mountain_direct"]:
            report.append(f"  {item['file']}:{item['line']}")
            report.append(f"    > {item['content']}")
        report.append("")
        report.append("  ⚠️  対策: eval締切ロジックをテストコード内で複製するか、")
        report.append("           パラメータ化してモード切り替え対応が必要")
        report.append("")
    
    # パターン2: メイン工程のassert
    if test_analysis["proc_main_assert"]:
        report.append("【中リスク】PROC_MAIN(メイン工程)の割当結果をassertするテスト")
        report.append("-" * 80)
        for item in test_analysis["proc_main_assert"][:5]:  # 最初の5件を表示
            report.append(f"  {item['file']}:{item['line']}")
            report.append(f"    > {item['content']}")
        if len(test_analysis["proc_main_assert"]) > 5:
            report.append(f"  ... + {len(test_analysis['proc_main_assert']) - 5} more")
        report.append("")
        report.append("  ⚠️  対策: 実装後に pytest を実行して、")
        report.append("           落ちるテストのassert値を「正しい修正」か確認してから修正")
        report.append("")
    
    # パターン3: リリーフ工程のassert
    if test_analysis["proc_relief_assert"]:
        report.append("【中リスク】PROC_RELIEF(リリーフ工程)の割当結果をassertするテスト")
        report.append("-" * 80)
        for item in test_analysis["proc_relief_assert"][:5]:
            report.append(f"  {item['file']}:{item['line']}")
            report.append(f"    > {item['content']}")
        if len(test_analysis["proc_relief_assert"]) > 5:
            report.append(f"  ... + {len(test_analysis['proc_relief_assert']) - 5} more")
        report.append("")
    
    # パターン4: 選択順関連
    if test_analysis["selection_order_related"]:
        report.append("【中リスク】選択順(sequence)に依存するテスト")
        report.append("-" * 80)
        for item in test_analysis["selection_order_related"][:5]:
            report.append(f"  {item['file']}:{item['line']}")
            report.append(f"    > {item['content']}")
        if len(test_analysis["selection_order_related"]) > 5:
            report.append(f"  ... + {len(test_analysis['selection_order_related']) - 5} more")
        report.append("")
    
    report.append("")
    report.append("【実装後の対応フロー】")
    report.append("-" * 80)
    report.append("1. 本実装完了後、以下を実行:")
    report.append("   $ pytest tests/ -v --tb=short")
    report.append("")
    report.append("2. テスト失敗が出た場合:")
    report.append("   a) 失敗内容を確認")
    report.append("   b) eval締切キー適用で「正しく選択順が変わった」ことか確認")
    report.append("   c) 「正しい修正」であればassert値を更新")
    report.append("   d) 「想定外の副作用」であれば実装を再検討")
    report.append("")
    report.append("3. ★重要★ assert削除・緩和は禁止")
    report.append("   - 落ちたテストのassert値は修正のみ")
    report.append("   - 複数の便に副作用が出た場合は実装前に要再検証")
    report.append("")
    
    return "\n".join(report)


def generate_implementation_checklist() -> str:
    """実装前チェックリスト生成"""
    checklist = []
    checklist.append("")
    checklist.append("=" * 80)
    checklist.append("【実装前チェックリスト】")
    checklist.append("=" * 80)
    checklist.append("")
    checklist.append("このスクリプトの結果をもとに、以下を確認してから本実装してください。")
    checklist.append("")
    checklist.append("□ STEP1: 現状(raw締切)のベースラインが正常に採取できたか")
    checklist.append("   → セットボード画面で確認可能な山と選択順が一致しているか")
    checklist.append("")
    checklist.append("□ STEP2: 案A(eval締切)のシミュレーション結果が合理的か")
    checklist.append("   → eval締切によって選択順が正しく変わっているか")
    checklist.append("")
    checklist.append("□ Q2重要観点: 07便がメイン通過しているか")
    checklist.append("   → ✅なら OK")
    checklist.append("   → ⚠️ なら→ 要再検討")
    checklist.append("")
    checklist.append("□ 副作用チェック: 07便以外の工程変化がないか")
    checklist.append("   → ✅なら OK（KVC以外不変の制約を満たす）")
    checklist.append("   → ⚠️ あれば→ 変化の理由を分析（許容か非許容か判断）")
    checklist.append("")
    checklist.append("□ STEP4テスト影響: 高リスクテストが何か確認したか")
    checklist.append("   → 各テストの対応方針を事前に決定")
    checklist.append("   → assert値修正方針を決定")
    checklist.append("")
    checklist.append("✅ すべてOK → 本実装を開始")
    checklist.append("   - KVC受入分割ブランチで実装（mainコミット禁止）")
    checklist.append("   - 変更は _pick_next_main_mountain のソートキーのみ")
    checklist.append("   - 最小差分を厳守")
    checklist.append("")
    checklist.append("⚠️  NG/要検討 → 要件再検討後に改めて調査")
    checklist.append("")
    
    return "\n".join(checklist)


def main():
    print("=" * 80)
    print("【案A 影響範囲確認スクリプト】実戦版")
    print("=" * 80)
    print()
    print("実行予定:")
    print("  STEP1: 現状(raw締切キー)のGUI本番フロー実測採取")
    print("  STEP2: 案A(eval締切キー)のシミュレーション")
    print("  STEP3: STEP1 vs STEP2 差分比較")
    print("  STEP4: 既存テスト影響分析")
    print()
    
    # ==================== STEP 4詳細版 ====================
    print("[STEP4] 既存テスト影響分析（詳細版）")
    print("-" * 80)
    
    test_analysis = analyze_test_dependency()
    
    # サマリ表示
    print()
    print("検出結果:")
    print(f"  - _pick_next_main_mountain 直接使用: {len(test_analysis['pick_next_main_mountain_direct'])} 件")
    print(f"  - PROC_MAIN のassert: {len(test_analysis['proc_main_assert'])} 件")
    print(f"  - PROC_RELIEF のassert: {len(test_analysis['proc_relief_assert'])} 件")
    print(f"  - 選択順関連のassert: {len(test_analysis['selection_order_related'])} 件")
    print()
    
    # レポート生成
    test_report = generate_test_impact_report(test_analysis)
    
    # ファイルに出力
    report_file = Path(__file__).parent / "analysis_impact_test_dependency.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(test_report)
    
    print(f"✅ テスト影響レポート出力: {report_file.name}")
    print()
    
    # ==================== 実装前チェックリスト ====================
    checklist = generate_implementation_checklist()
    
    checklist_file = Path(__file__).parent / "analysis_implementation_checklist.txt"
    with open(checklist_file, 'w', encoding='utf-8') as f:
        f.write(checklist)
    
    print(f"✅ 実装前チェックリスト出力: {checklist_file.name}")
    print()
    
    # ==================== 最終結論 ====================
    print("=" * 80)
    print("【NEXT STEP】")
    print("=" * 80)
    print()
    print("1. ✅ analysis_impact_test_dependency.txt を確認")
    print("     → テスト影響を理解")
    print()
    print("2. ✅ analysis_implementation_checklist.txt に従ってチェック")
    print("     → 各項目OK確認後に本実装開始")
    print()
    print("3. □ GUI本番フロー全体との統合試験")
    print("     → SPOアップロード用.xlsx + GUI実行で STEP1-3 詳細測定")
    print()
    print("4. □ OK確認後、KVC受入分割ブランチで最小差分実装")
    print("     → _pick_next_main_mountain のソートキー変更のみ")
    print()
    
    # ファイル出力完了
    print()
    print("出力ファイル:")
    print(f"  1. {report_file}")
    print(f"  2. {checklist_file}")
    print()


if __name__ == "__main__":
    main()
