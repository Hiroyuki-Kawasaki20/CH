# -*- coding: utf-8 -*-
"""
【PR #58 実データ検証用スクリプト】
日野別便の入れ込みカウント測定（データ分析版）

実行:
  python t119_validate_hino_interleave.py [--input-xlsx PATH]

出力:
  - t119_interleave_validation.txt : 詳細レポート
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Set, Tuple, List

# Windows環境でのUnicode出力対応
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np
from src.services.data_loader import load_pickup_time_master_xlsx


def extract_hino_bin_number(nonyuhibin: str) -> str:
    """NONYUHIBIN を文字列化して便番号として使用"""
    if pd.isna(nonyuhibin):
        return None
    # NONYUHIBIN をそのまま文字列化（末尾2桁ではなく全体が便番号）
    return str(int(nonyuhibin) % 100).zfill(2)


def get_hino_bins_in_df(df: pd.DataFrame) -> Set[str]:
    """
    DataFrameに含まれる日野便番号セットを取得
    """
    hino_col = 'OData_納入先' if 'OData_納入先' in df.columns else '納入先'
    hino_orders = df[df[hino_col] == '日野']
    bin_set = set()
    for nonyuhibin in hino_orders['NONYUHIBIN'].dropna():
        bin_num = extract_hino_bin_number(nonyuhibin)
        if bin_num:
            bin_set.add(bin_num)
    return bin_set


def count_hino_interleave_by_order_time(input_df: pd.DataFrame) -> Tuple[int, List[Dict]]:
    """
    日野別便の入れ込み件数をカウント（受注単位での分析）

    カウント定義:
      日野便A の全オーダー群の時間帯 start_A～end_A 内に、
      日野便B（A≠B）のオーダーが存在するケースを1件と数える

    Args:
        input_df: 元の入力データフレーム

    Returns:
        (interleave_count, [検出した組の明細リスト])
    """
    interleave_count = 0
    interleave_details = []
    
    # 日野オーダーのみを抽出
    hino_col = 'OData_納入先' if 'OData_納入先' in input_df.columns else '納入先'
    hino_df = input_df[input_df[hino_col] == '日野'].copy()
    
    if hino_df.empty:
        return 0, []
    
    # 日野便ごとに時間でグループ化
    hino_df['日野便番'] = hino_df['NONYUHIBIN'].apply(extract_hino_bin_number)
    
    # 日野便番がない行を除外
    hino_df = hino_df.dropna(subset=['日野便番'])
    
    if hino_df.empty:
        return 0, []
    
    # 入車時間を時間に変換（HH:MM形式 → 秒）
    def time_str_to_seconds(time_str):
        if pd.isna(time_str):
            return None
        try:
            s = str(time_str).strip()
            if ':' in s:
                h, m = s.split(':')
                return int(h) * 3600 + int(m) * 60
            else:
                return None
        except:
            return None
    
    hino_df['入車秒'] = hino_df['入車時間'].apply(time_str_to_seconds)
    hino_df = hino_df.dropna(subset=['入車秒'])
    
    # 日野便ごとのグループ化
    hino_groups = hino_df.groupby('日野便番')
    
    bin_list = sorted(hino_groups.groups.keys())
    
    print(f"【日野便の日時範囲分析】")
    print(f"日野便数: {len(bin_list)}")
    print(f"日野便リスト: {bin_list}")
    print()
    
    # 各日野便の時間帯を取得
    bin_time_ranges = {}
    for bin_num, group_df in hino_groups:
        if '入車秒' in group_df.columns:
            min_sec = group_df['入車秒'].min()
            max_sec = group_df['入車秒'].max()
            bin_time_ranges[bin_num] = {
                'min': min_sec,
                'max': max_sec,
                'count': len(group_df),
            }
            
            def sec_to_hm(sec):
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                return f"{h:02d}:{m:02d}"
            
            print(f"  日野便{bin_num}: {sec_to_hm(min_sec)} ～ {sec_to_hm(max_sec)} ({len(group_df)}件)")
        else:
            bin_time_ranges[bin_num] = {
                'min': None,
                'max': None,
                'count': len(group_df),
            }
    
    print()
    
    # 日野便ペアの時間帯の重なりを確認
    print(f"【日野別便の入れ込み検出】")
    
    for i, bin_a in enumerate(bin_list):
        for bin_b in bin_list[i+1:]:
            range_a = bin_time_ranges[bin_a]
            range_b = bin_time_ranges[bin_b]
            
            # 時間情報がない場合はスキップ
            if range_a['min'] is None or range_b['min'] is None:
                continue
            
            # 時間帯の重なりを確認
            overlap_start = max(range_a['min'], range_b['min'])
            overlap_end = min(range_a['max'], range_b['max'])
            
            if overlap_start <= overlap_end:
                # 重なっている
                interleave_count += 1
                detail = {
                    'bin_a': bin_a,
                    'bin_b': bin_b,
                    'a_start': range_a['min'],
                    'a_end': range_a['max'],
                    'b_start': range_b['min'],
                    'b_end': range_b['max'],
                    'overlap_start': overlap_start,
                    'overlap_end': overlap_end,
                }
                interleave_details.append(detail)
                
                def sec_to_hm(sec):
                    h = int(sec // 3600)
                    m = int((sec % 3600) // 60)
                    return f"{h:02d}:{m:02d}"
                
                print(f"  [入れ込み #{interleave_count}]")
                print(f"    日野便{bin_a}: {sec_to_hm(range_a['min'])} ～ {sec_to_hm(range_a['max'])}")
                print(f"    日野便{bin_b}: {sec_to_hm(range_b['min'])} ～ {sec_to_hm(range_b['max'])}")
                print(f"    重なり: {sec_to_hm(overlap_start)} ～ {sec_to_hm(overlap_end)}")
                print()
    
    if interleave_count == 0:
        print("  入れ込みなし")
    
    return interleave_count, interleave_details


def main():
    parser = argparse.ArgumentParser(
        description='PR #58 実データ検証用スクリプト'
    )
    parser.add_argument(
        '--input-xlsx',
        type=str,
        default='入車時間マスタ.xlsx',
        help='入力Excelファイルパス'
    )
    
    args = parser.parse_args()
    
    print(f"【PR #58 実データ検証（データ分析版）】")
    print(f"入力ファイル: {args.input_xlsx}")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    # 入力データ読込
    try:
        input_path = Path(args.input_xlsx)
        df_input = load_pickup_time_master_xlsx(input_path)
        print(f"✓ 入力ファイル読込成功: {len(df_input)} 行")
        print(f"  列: {list(df_input.columns)}")
    except Exception as e:
        print(f"✗ 入力ファイル読込失敗: {e}")
        return 1
    
    print()
    
    # データの基本統計
    print("【入力データ統計】")
    print(f"  総行数: {len(df_input)}")
    
    hino_col = 'OData_納入先' if 'OData_納入先' in df_input.columns else '納入先'
    hino_df = df_input[df_input[hino_col] == '日野']
    print(f"  日野オーダー数: {len(hino_df)}")
    
    if not hino_df.empty:
        hino_bins = get_hino_bins_in_df(df_input)
        print(f"  日野便種: {sorted(hino_bins)}")
    
    print()
    
    # 日野別便入れ込みカウント
    print("【STEP 1】 日野別便入れ込みカウント")
    print("-" * 80)
    try:
        interleave_count, interleave_details = count_hino_interleave_by_order_time(df_input)
        print()
        print(f"✓ カウント完了: {interleave_count} 件")
    except Exception as e:
        print(f"✗ カウント失敗: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print()
    
    # 検証結果レポート
    print("【検証結果】")
    print("=" * 80)
    print()
    print(f"【日野別便入れ込み件数】 {interleave_count} 件")
    print()
    
    if interleave_details:
        print("【入れ込み明細】")
        for idx, detail in enumerate(interleave_details, 1):
            print(f"\n  ◆ 件#{idx}")
            print(f"    日野便{detail['bin_a']}: {detail['a_start']} ～ {detail['a_end']}")
            print(f"    日野便{detail['bin_b']}: {detail['b_start']} ～ {detail['b_end']}")
            print(f"    重なり期間: {detail['overlap_start']} ～ {detail['overlap_end']}")
    else:
        print("【入れ込み明細】 なし")
    
    print()
    
    # レポートファイル出力
    report_path = Path(f"t119_interleave_validation.txt")
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"【PR #58 実データ検証レポート】\n")
            f.write(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"【日野別便入れ込み件数】 {interleave_count} 件\n\n")
            
            if interleave_details:
                f.write("【入れ込み明細】\n")
                for idx, detail in enumerate(interleave_details, 1):
                    f.write(f"\n  ◆ 件#{idx}\n")
                    f.write(f"    日野便{detail['bin_a']}: {detail['a_start']} ～ {detail['a_end']}\n")
                    f.write(f"    日野便{detail['bin_b']}: {detail['b_start']} ～ {detail['b_end']}\n")
                    f.write(f"    重なり期間: {detail['overlap_start']} ～ {detail['overlap_end']}\n")
        
        print(f"✓ レポート出力: {report_path}")
    except Exception as e:
        print(f"✗ レポート出力失敗: {e}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
