# -*- coding: utf-8 -*-
"""使い捨て: _build_size1_mixed の出力列を確認するスクリプト"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from src.services.sorter import _build_size1_mixed

# === 最小入力: サイズ1×1行 + サイズ21×1行（同一便・同一納入先・高さ合計2450以内） ===
expanded = pd.DataFrame([
    {
        "サイズ種類": "1",
        "高さ": 1200,
        "移動工数": 10,
        "NONYUHIBIN": "01",
        "納入先": "高岡",
        "UKEIRE": "A",
        "SYUKKASAKI": "高岡",
    },
    {
        "サイズ種類": "21",
        "高さ": 800,
        "移動工数": 8,
        "NONYUHIBIN": "01",
        "納入先": "高岡",
        "UKEIRE": "A",
        "SYUKKASAKI": "高岡",
    },
])

summary, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")

print("=" * 60)
print("■ details (size1_mixed_details) の列情報")
print("=" * 60)

print("\n--- columns.tolist() ---")
print(details.columns.tolist())

print("\n--- dtypes ---")
print(details.dtypes)

print("\n--- df.to_string() ---")
print(details.to_string())

print("\n--- 山通番 ---")
if "山通番" in details.columns:
    print("山通番 values:", details["山通番"].tolist())
    print("山通番 dtype:", details["山通番"].dtype)
else:
    print("山通番 列は存在しません")

# 積み順関連列の探索
print("\n--- 積み順関連列の探索 ---")
order_candidates = ["積み順", "レイヤー", "段", "順序", "layer", "stack_order",
                    "role", "role_class", "_role_class", "サイズ種類"]
for col in order_candidates:
    if col in details.columns:
        print(f"  {col}: {details[col].tolist()}")

print("\n" + "=" * 60)
print("■ summary (size1_mixed_summary) の列情報")
print("=" * 60)

print("\n--- columns.tolist() ---")
print(summary.columns.tolist())

print("\n--- df.to_string() ---")
print(summary.to_string())
