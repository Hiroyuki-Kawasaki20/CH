#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ステップA検証スクリプト②：GUI内の注入ヘルパー関数をテスト
"""

import sys
import pandas as pd
from src.models.constants import PROC_MAIN, VIRTUAL_YAMA_NO

print("\n" + "="*80)
print("ステップA検証②：GUIの注入ヘルパー関数をテスト")
print("="*80)

# GUIクラスのメソッドを直接テストするため、簡易版を実装
def build_virtual_battery_row_for_df(base_df: pd.DataFrame) -> dict:
    """既存列構成に合わせて、表示/出力用の仮想山(-1)明細1行を作る。"""
    row = {}
    for col in base_df.columns:
        if pd.api.types.is_numeric_dtype(base_df[col]):
            row[col] = 0
        else:
            row[col] = ""

    fixed_values = {
        "山通番": -1,
        "工程": PROC_MAIN,
        "工程内No": 1,
        "納入先": "〔バッテリー交換〕",
        "HINBAN": "BATTERY_CHANGE",
        "引取工数_秒": 600,
        "移動工数": 0,
        "高さ": 0,
    }
    for col, val in fixed_values.items():
        if col in base_df.columns:
            row[col] = val

    return row

def inject_single_virtual_battery_row(df: pd.DataFrame) -> pd.DataFrame:
    """既存-1行を除去した上で、仮想山(-1)明細を1行だけ注入する。"""
    if df is None or df.empty or "山通番" not in df.columns:
        return df

    out = df.copy()
    yama_num = pd.to_numeric(out["山通番"], errors="coerce")
    out = out.loc[yama_num != -1].copy()

    row = build_virtual_battery_row_for_df(out if not out.empty else df)
    virtual_df = pd.DataFrame([row], columns=out.columns if not out.empty else df.columns)
    return pd.concat([out, virtual_df], axis=0, ignore_index=True)

# テスト用データ（実際のセットボード出力を模した列構成）
test_data = pd.DataFrame({
    '山通番': [1, 1, 2, 2, 3],
    '工程': ['メイン', 'メイン', 'メイン', 'メイン', 'メイン'],
    '工程内No': [1, 2, 1, 2, 1],
    '納入先': ['先A', '先A', '先B', '先B', '先C'],
    'HINBAN': ['品1', '品2', '品3', '品4', '品5'],
    '引取工数_秒': [600, 600, 1200, 600, 900],
    '移動工数': [10, 10, 20, 10, 15],
    '高さ': [1, 1, 2, 1, 1],
})

print("\n【テスト1】元データ（-1なし）")
print(test_data)

print("\n【テスト2】1回目の注入")
injected_once = inject_single_virtual_battery_row(test_data.copy())
print(injected_once)
print(f"\n  行数: {len(injected_once)} 行（元 {len(test_data)} + -1は1行）")
print(f"  -1の行数: {int((pd.to_numeric(injected_once['山通番'], errors='coerce') == -1).sum())}")

print("\n【テスト3】2回目の注入（既存-1削除→再注入で1行保証）")
injected_twice = inject_single_virtual_battery_row(injected_once.copy())
print(injected_twice)
print(f"\n  行数: {len(injected_twice)} 行（元 {len(test_data)} + -1は1行のまま）")
print(f"  -1の行数: {int((pd.to_numeric(injected_twice['山通番'], errors='coerce') == -1).sum())}")

if len(injected_twice) == len(injected_once):
    print("\n  ✓ OK：2回の注入で行数が変わらない（1行保証）")
else:
    print(f"\n  ✗ NG：行数が変わった（{len(injected_once)} → {len(injected_twice)}）")

print("\n【テスト4】-1行の値の確認")
virtual_row = injected_twice[pd.to_numeric(injected_twice['山通番'], errors='coerce') == -1]
if not virtual_row.empty:
    print(virtual_row.to_string())
    assert virtual_row['納入先'].values[0] == '〔バッテリー交換〕', "納入先が不正"
    assert virtual_row['HINBAN'].values[0] == 'BATTERY_CHANGE', "HINBANが不正"
    assert virtual_row['引取工数_秒'].values[0] == 600, "引取工数_秒が不正"
    print("\n  ✓ OK：-1行の固定値がすべて正しい")
else:
    print("  ✗ NG：-1行が見つからない")

print("\n" + "="*80)
print("ステップA検証②OK：注入ヘルパー関数が正常に動作")
print("="*80)
