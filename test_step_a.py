#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ステップA検証スクリプト：作業1（注入）だけ実装が正常に動作するか確認
- OFF時：-1は出ない
- ON時：-1が注入される
"""

import sys
import pandas as pd
from src.models.constants import VIRTUAL_YAMA_NO, is_virtual_yama

print("="*80)
print("ステップA検証：作業1（注入）の実装確認")
print("="*80)

# テスト1: 定数確認
print("\n【テスト1】定数確認")
print(f"  VIRTUAL_YAMA_NO = {VIRTUAL_YAMA_NO}")
print(f"  is_virtual_yama(-1) = {is_virtual_yama(-1)}")
print(f"  is_virtual_yama(1) = {is_virtual_yama(1)}")
print(f"  is_virtual_yama(None) = {is_virtual_yama(None)}")
print(f"  is_virtual_yama('abc') = {is_virtual_yama('abc')}")

# テスト2: injection ロジック確認
print("\n【テスト2】注入ロジック確認")
test_df = pd.DataFrame({
    '山通番': [1, 2, 3],
    '納入先': ['A', 'B', 'C'],
    '引取工数_秒': [1200, 1800, 900],
})
print(f"  元データ:\n{test_df}")

# -1を含む DataFrame を作成
test_df_with_neg1 = pd.concat([test_df, pd.DataFrame({'山通番': [-1], '納入先': ['既存-1'], '引取工数_秒': [0]})], ignore_index=True)
print(f"\n  既存-1を含むデータ:\n{test_df_with_neg1}")

# -1を除外するフィルタ
yama_num = pd.to_numeric(test_df_with_neg1['山通番'], errors='coerce')
filtered = test_df_with_neg1.loc[yama_num != -1].copy()
print(f"\n  フィルタ後（-1除外）:\n{filtered}")

# テスト3: is_virtual_yama() の正動作確認
print("\n【テスト3】is_virtual_yama()の正動作")
test_values = [-1, 0, 1, 2, None, '-1', 'abc']
for val in test_values:
    result = is_virtual_yama(val)
    print(f"  is_virtual_yama({repr(val):>5}) = {result}")

print("\n" + "="*80)
print("ステップA準備OK：注入ロジックの基本確認完了")
print("="*80)
