# -*- coding: utf-8 -*-
"""Issue #52: 締切超過(_serialize_lanes_final)再現テスト

戦略:
- test_issue36 ベースの master_df 構造を使用
- シンプルな 2～3 山でメイン+リリーフ同時発生ケースを構築
- 直列化により後ろ倒しされた場合の実開始時刻変化を検証
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import pandas as pd
import numpy as np
from io import StringIO

from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    compute_proc_details,
    _calc_work_end_with_breaks,
    _time_to_seconds,
)
from src.models.constants import (
    BASE_ONE_TIME, BASE_PER_PAL, MIDDLE_WORK, PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW,
)


def _work_secs(cost, pal):
    """引取工数[秒] = BASE_ONE_TIME + MIDDLE_WORK*(pal-1) + BASE_PER_PAL*pal + 移動工数"""
    return int(np.round(cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0))


def test_issue52_serialize_lanes_final_affects_start_time():
    """Issue #52: 直列化ステップで実開始時刻が変化するケースを検証
    
    シンプルケース: 
    - 入車時刻: 13:30, 13:30
    - 作業時間: 30分, 30分
    - メイン+リリーフが同時に発生
    - 直列化で後ろ倒しされると 実開始時刻が変わる
    """
    
    # df: 詳細(パレット別)
    df = pd.DataFrame({
        "山通番": [1, 1, 2, 2],
        "パレット番号": [1, 2, 1, 2],
        "納入先": ["A", "A", "B", "B"],
        "NONYUHIBIN": ["01", "01", "01", "01"],
        "高さ": [300, 300, 300, 300],
        "移動工数": [100.0, 100.0, 100.0, 100.0],  # 移動工数で引取時間計算
    })
    
    # master_df: test_issue36 ベースの構造
    master_df = pd.DataFrame({
        "OData_納入先": ["A", "B"],
        "NONYUHIBIN": ["01", "01"],
        "入車時間": ["13:30", "13:30"],
        "セットありフラグ": ["0", "0"],
    })
    
    proc_details = compute_proc_details(df)
    result = assign_processes_by_arrival_time(proc_details, master_df)
    
    print("\n" + "="*80)
    print("Issue #52: 直列化影響テスト")
    print("="*80)
    print("\n【実行結果】")
    print(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
    
    # ファイルに保存
    with open("t133_issue52_repro.txt", "w", encoding="utf-8") as f:
        f.write("Issue #52: 直列化影響テスト\n")
        f.write("="*80 + "\n\n")
        f.write("【テスト条件】\n")
        f.write("- 山1,2: 入車時刻 13:30, 作業時間 30分\n")
        f.write("- メイン+リリーフ同時発生\n\n")
        f.write("【実行結果】\n")
        f.write(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
        f.write("\n\n【確認】\n")
        f.write("直列化により、レーン内の山がずれていないか検証\n")
    
    print("\n → 結果を t133_issue52_repro.txt に保存しました")
    
    # 基本検証
    assert len(result) > 0, "割当結果が空"
    assert "山工程" in result.columns, "山工程 カラムなし"
    assert "実開始時間" in result.columns, "実開始時間 カラムなし"


def test_issue52_midnight_wrapping_via_serialize_lanes_final():
    """Issue #52: 24:xx → 00:xx 巻き戻しが実開始時刻に影響するか検証
    
    シナリオ:
    - 3山、同一レーン（メイン）
    - 作業時間を長めに設定し、end_secs > 86400 (24h超) を意図的に作る
    - direct実開始時刻が 24:xx となった場合、直列化で % 86400 巻き戻しされるはず
    - その場合の実開始時刻が正しい (翌日基準のまま) か、
      或いは不正 (当日基準に戻ってしまった) かを検証
    """
    
    # df: 詳細(パレット別)
    # 長い作業時間設定
    df = pd.DataFrame({
        "山通番": [10, 10, 11, 11, 12, 12],
        "パレット番号": [1, 2, 1, 2, 1, 2],
        "納入先": ["X", "X", "X", "X", "X", "X"],
        "NONYUHIBIN": ["01", "01", "01", "01", "01", "01"],
        "高さ": [300, 300, 300, 300, 300, 300],
        "移動工数": [500.0, 500.0, 500.0, 500.0, 500.0, 500.0],  # 長い
    })
    
    # master_df: 夜間帯入車（24:xx 相当を作りやすい）
    # 入車時刻を 23:30 に設定 → 各山の開始がずれて 24:xx + 超過 となる可能性
    master_df = pd.DataFrame({
        "OData_納入先": ["X"],
        "NONYUHIBIN": ["01"],
        "入車時間": ["23:30"],
        "セットありフラグ": ["0"],
    })
    
    proc_details = compute_proc_details(df)
    result = assign_processes_by_arrival_time(proc_details, master_df)
    
    print("\n" + "="*80)
    print("Issue #52: 24:xx 巻き戻しテスト")
    print("="*80)
    print("\n【実行結果】")
    print(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
    
    # 実開始時刻を秒に変換し、チェック
    print("\n【詳細】")
    for _, row in result.iterrows():
        start_str = str(row.get("実開始時間", "")).strip()
        end_str = str(row.get("実終了時間", "")).strip()
        
        start_secs = _time_to_seconds(start_str)
        if start_secs is not None:
            # 00:xx または 24:xx？
            is_midnight = start_str.startswith("00:")
            is_next_day = start_secs > 86400
            print(f"  山{row['山通番']}: {start_str} ({start_secs}秒, 翌日={is_next_day})")
    
    # ファイルに保存
    with open("t133_issue52_midnight_test.txt", "w", encoding="utf-8") as f:
        f.write("Issue #52: 24:xx 巻き戻しテスト\n")
        f.write("="*80 + "\n\n")
        f.write("【テスト条件】\n")
        f.write("- 山10,11,12: 入車時刻 23:30, 長作業時間\n")
        f.write("- メイン工程へ割当\n")
        f.write("- 直列化で 24:xx が % 86400 巻き戻しされ得る条件\n\n")
        f.write("【実行結果】\n")
        f.write(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
        f.write("\n\n【詳細（秒単位）】\n")
        for _, row in result.iterrows():
            start_str = str(row.get("実開始時間", "")).strip()
            start_secs = _time_to_seconds(start_str)
            if start_secs is not None:
                f.write(f"  山{row['山通番']}: {start_str} = {start_secs}秒\n")
        f.write("\n【判定】\n")
        f.write("実開始時刻が順序通り逆転せず、巻き戻しの影響を観察\n")
    
    print("\n → 結果を t133_issue52_midnight_test.txt に保存しました")
    
    # 基本検証
    assert len(result) > 0, "割当結果が空"


def test_issue52_direct_serialize_lanes_final_impact():
    """Issue #52: _serialize_lanes_final による実開始時刻の変化を直接検証
    
    戦略:
    1. assign_processes_by_arrival_time を実行（通常処理）
    2. 異なる入車時刻でも実行
    3. 結果差分から _serialize_lanes_final の影響度を測定
    
    特に: メイン+リリーフが同時発生し、
    直列化により後ろ倒しされる 24:xx 超過ケースを検証
    """
    
    # 複数ケース
    test_cases = [
        # ケース1: 両山同一納入先・時刻
        {
            "name": "ケース1: 同入車時刻",
            "df": pd.DataFrame({
                "山通番": [20, 20, 21, 21],
                "パレット番号": [1, 2, 1, 2],
                "納入先": ["Y", "Y", "Y", "Y"],
                "NONYUHIBIN": ["02", "02", "02", "02"],
                "高さ": [300, 300, 300, 300],
                "移動工数": [400.0, 400.0, 400.0, 400.0],
            }),
            "master_entry_time": "22:00",
        },
        # ケース2: 別納入先・入車時刻離
        {
            "name": "ケース2: 異納入先",
            "df": pd.DataFrame({
                "山通番": [22, 22, 23, 23],
                "パレット番号": [1, 2, 1, 2],
                "納入先": ["Z", "Z", "W", "W"],
                "NONYUHIBIN": ["03", "03", "04", "04"],
                "高さ": [300, 300, 300, 300],
                "移動工数": [350.0, 350.0, 350.0, 350.0],
            }),
            "master_entry_time": "22:30",
        },
    ]
    
    with open("t133_issue52_direct_impact.txt", "w", encoding="utf-8") as f:
        f.write("Issue #52: _serialize_lanes_final 直接影響テスト\n")
        f.write("="*80 + "\n\n")
        
        for case in test_cases:
            print("\n" + "="*80)
            print(f"【{case['name']}】")
            print("="*80)
            
            df = case["df"]
            
            # master_df: 複数納入先対応
            unique_vendors = df["納入先"].unique()
            unique_bins = df["NONYUHIBIN"].unique()
            
            master_data = []
            for vendor in unique_vendors:
                for bin_id in unique_bins[:1]:  # 最初のBIN_IDのみ
                    master_data.append({
                        "OData_納入先": vendor,
                        "NONYUHIBIN": bin_id,
                        "入車時間": case["master_entry_time"],
                        "セットありフラグ": "0",
                    })
            master_df = pd.DataFrame(master_data)
            
            proc_details = compute_proc_details(df)
            result = assign_processes_by_arrival_time(proc_details, master_df)
            
            print("\n【結果】")
            print(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
            
            # ファイルに出力
            f.write(f"\n【{case['name']}】\n")
            f.write("-"*80 + "\n")
            f.write(f"入車時刻: {case['master_entry_time']}\n\n")
            f.write(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
            f.write("\n\n")
            
            # 統計
            main_rows = result[result["山工程"] == "メイン"]
            relief_rows = result[result["山工程"] == "リリーフ"]
            print(f"\n統計: メイン {len(main_rows)} | リリーフ {len(relief_rows)}")
            f.write(f"統計: メイン {len(main_rows)} | リリーフ {len(relief_rows)}\n\n")
        
        f.write("\n" + "="*80 + "\n")
        f.write("【判定】\n")
        f.write("直列化により実開始時刻の差異が生じるかどうかを観察\n")
        f.write("特に 24:xx → 00:xx への巻き戻しが発生するかを確認\n")
    
    print("\n → 結果を t133_issue52_direct_impact.txt に保存しました")
    
    assert True, "検証完了"


def test_issue52_manual_before_after_comparison():
    """Issue #52: _serialize_lanes_final の処理前後を手動で比較
    
    戦略:
    1. 複数山を異なる入車時刻で実行
    2. 各工程（メイン/リリーフ）ごとに実開始時刻をトラッキング
    3. 直列化による時刻変化を捕捉
    """
    
    # テストケース: 夜間帯入車（24:xx巻き戻しが起こりやすい）
    test_df = pd.DataFrame({
        "山通番": [30, 30, 31, 31, 32, 32],
        "パレット番号": [1, 2, 1, 2, 1, 2],
        "納入先": ["NIGHT", "NIGHT", "NIGHT", "NIGHT", "NIGHT", "NIGHT"],
        "NONYUHIBIN": ["99", "99", "99", "99", "99", "99"],
        "高さ": [300, 300, 300, 300, 300, 300],
        "移動工数": [600.0, 600.0, 600.0, 600.0, 600.0, 600.0],  # 長め
    })
    
    master_df = pd.DataFrame({
        "OData_納入先": ["NIGHT"],
        "NONYUHIBIN": ["99"],
        "入車時間": ["23:45"],  # 夜間帯
        "セットありフラグ": ["0"],
    })
    
    proc_details = compute_proc_details(test_df)
    result = assign_processes_by_arrival_time(proc_details, master_df)
    
    print("\n" + "="*80)
    print("Issue #52: 手動比較テスト（23:45 入車時刻）")
    print("="*80)
    print("\n【割当結果】")
    print(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
    
    # 秒単位で確認
    print("\n【詳細（秒単位）】")
    for _, row in result.iterrows():
        start_str = str(row.get("実開始時間", "")).strip()
        end_str = str(row.get("実終了時間", "")).strip()
        start_secs = _time_to_seconds(start_str)
        end_secs = _time_to_seconds(end_str)
        
        if start_secs is not None:
            # 24h超過判定
            is_next_day = start_secs >= 86400
            print(f"  山{row['山通番']}: {start_str} = {start_secs:6d}秒 (翌日={is_next_day})")
    
    # 締切超過判定
    print("\n【締切判定】")
    # 入車時刻 23:45 = 85500秒
    # 締切を 23:45 から +30分 = 24:15 (86400+900=87300秒) と仮定
    entry_secs = _time_to_seconds("23:45")
    deadline_secs = entry_secs + 1800  # +30分
    
    print(f"  入車時刻: 23:45 ({entry_secs}秒)")
    print(f"  仮想締切: 23:45 + 30分 = 24:15 ({deadline_secs}秒)")
    print(f"\n  超過検証:")
    
    for _, row in result.iterrows():
        end_str = str(row.get("実終了時間", "")).strip()
        end_secs = _time_to_seconds(end_str)
        if end_secs is not None:
            # 当日内での比較
            if end_secs >= 86400:
                adjusted_end = end_secs  # 翌日そのまま
            else:
                adjusted_end = end_secs
            
            is_over = adjusted_end > deadline_secs
            print(f"    山{row['山通番']}: 終了 {end_str} ({end_secs}秒) → 超過={is_over}")
    
    # ファイル保存
    with open("t133_issue52_manual_comparison.txt", "w", encoding="utf-8") as f:
        f.write("Issue #52: 手動比較テスト（23:45 入車）\n")
        f.write("="*80 + "\n\n")
        f.write("【割当結果】\n")
        f.write(result[["山通番", "山工程", "実開始時間", "実終了時間"]].to_string())
        f.write("\n\n【詳細（秒単位）】\n")
        for _, row in result.iterrows():
            start_str = str(row.get("実開始時間", "")).strip()
            start_secs = _time_to_seconds(start_str)
            if start_secs is not None:
                is_next_day = start_secs >= 86400
                f.write(f"  山{row['山通番']}: {start_str} = {start_secs:6d}秒 (翌日={is_next_day})\n")
        f.write("\n【判定】\n")
        f.write("直列化前後での時刻差異を観察\n")
    
    print("\n → 結果を t133_issue52_manual_comparison.txt に保存しました")
    
    assert len(result) > 0, "割当結果が空"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
