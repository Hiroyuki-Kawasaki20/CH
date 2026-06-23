# -*- coding: utf-8 -*-
"""CHかんばんセット — CSV読み書きユーティリティ"""

from pathlib import Path
import pandas as pd
from pandas.errors import EmptyDataError


def read_csv_ja(path: Path) -> pd.DataFrame:
    """日本語対応CSVファイル読込（UTF-8/CP932自動判定）"""
    last_decode_error = None
    for encoding in ("utf-8", "cp932"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        except EmptyDataError as exc:
            raise ValueError(f"CSVが空です: {path}") from exc
    if last_decode_error is not None:
        raise last_decode_error
    raise ValueError(f"CSVを読み込めませんでした: {path}")


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
