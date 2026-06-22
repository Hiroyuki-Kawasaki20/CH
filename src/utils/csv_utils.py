# -*- coding: utf-8 -*-
"""CHかんばんセット — CSV読み書きユーティリティ"""

from pathlib import Path
import pandas as pd


def read_csv_ja(path: Path) -> pd.DataFrame:
    """日本語対応CSVファイル読込（UTF-8/CP932自動判定）"""
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp932")


def write_csv_ja(df: pd.DataFrame, path: Path):
    """日本語対応CSVファイル書込（エンコーディング自動選択）"""
    encodings = ["utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            df.to_csv(path, index=False, encoding=enc)
            return
        except Exception:
            continue
    df.to_csv(path, index=False)
