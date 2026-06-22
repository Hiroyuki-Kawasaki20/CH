#!/usr/bin/env python
"""E2E出力確認 - データフレームカラム確認"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.services.data_loader import load_data

df_shipments, df_places = load_data()
print("出荷情報カラム:")
print(df_shipments.columns.tolist())
print("\n出荷場一覧カラム:")
print(df_places.columns.tolist())
print("\n最初の5行:")
print(df_shipments.head(5))
