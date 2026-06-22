# -*- coding: utf-8 -*-
"""CHかんばんセット — テキスト正規化ユーティリティ"""

import re
import pandas as pd

# 全角→半角変換テーブル
_ZEN2HAN_DIGIT_COLON = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "：": ":",
})

# 納入先エイリアス
_NAME_ALIASES = {
    "九州": "KVC",
    "TMK": "KVC",
    "日野E/H": "日野EH",
    "日野ｅ/ｈ": "日野EH",
    "日野e/h": "日野EH",
}


def _normalize_name(text: str) -> str:
    if pd.isna(text):
        return ""
    s = str(text).strip()
    return _NAME_ALIASES.get(s, s)


def _normalize_dest_name(text: str) -> str:
    return _normalize_name(text)


def _normalize_route_name(text: str) -> str:
    return _normalize_name(text)


def _normalize_hhmm(text: str) -> str:
    """'HH:MM' 形式に正規化。秒は切り捨て、全角数字/コロンも半角に寄せる。"""
    if pd.isna(text):
        return ""
    s = str(text).strip().translate(_ZEN2HAN_DIGIT_COLON)
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{1,2})", s)
    if not m:
        return ""
    hh, mm = m.group(1), m.group(2)
    return f"{int(hh):02d}:{int(mm):02d}"


def _normalize_ukeire(val) -> str:
    """受入の正規化（数字のみなら先頭ゼロを除去して比較用に統一）"""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if s.isdigit():
        return str(int(s))
    return s
