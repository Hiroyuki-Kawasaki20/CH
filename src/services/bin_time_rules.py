# -*- coding: utf-8 -*-
"""Issue #96: (納入先, 便) → (開始床, 締切) の共通計算ヘルパー。

定義:
- 締切 = 自便の入車時刻 − 10分（山はこの時刻までに完了していること）
- 床   = 前便の入車時刻 + 10分（前便が落ち着くまで着手しない）

日跨ぎ軸は process_assigner と同じ 03:00 基準（03:00未満は +24h）に統一する。
sorter 従来実装（_timeline_secs）の 06:25 基準との軸ズレ（Issue #27 の親戚 = #96 穴3）を
ここで解消する。

既知の制限（次PRで process_assigner._get_prev_bin_for_vendor と統合予定 = #96 穴2）:
- 前便は「便番号 −1 がマスタに存在する場合」のみ解決する。
  01便の巻き戻り・日野N-2・武部時刻グループ・セットありフラグは未対応
  （床が 0 または高め に倒れる。高め側は混載を控えめにする安全側の誤り）。
"""

import logging
from typing import Dict, Optional, Tuple

import pandas as pd

from ..utils.normalizer import (
    _normalize_dest_name, _normalize_hhmm, _ZEN2HAN_DIGIT_COLON,
)

logger = logging.getLogger(__name__)

TEN_MIN_SECS = 10 * 60
DAY_ROLLOVER_SECS = 3 * 3600

BinTimeMap = Dict[Tuple[str, str], int]


def timeline_secs(hhmm_text: str) -> Optional[int]:
    """HH:MM を業務日タイムライン秒へ変換（03:00 未満は +24h）。"""
    t = _normalize_hhmm(str(hhmm_text))
    if not t:
        return None
    try:
        hh, mm = t.split(":", 1)
        secs = int(hh) * 3600 + int(mm) * 60
    except Exception:
        return None
    if secs < DAY_ROLLOVER_SECS:
        secs += 24 * 3600
    return secs


def build_bin_time_map(master_df: Optional[pd.DataFrame]) -> BinTimeMap:
    """入車時間マスタから (正規化納入先, 便2桁) → 入車秒 の辞書を構築する。

    当日の仕分けデータに存在しない前便もここから引ける（#96 穴1の解消）。
    """
    result: BinTimeMap = {}
    if master_df is None or master_df.empty:
        return result
    for _, row in master_df.iterrows():
        vendor = _normalize_dest_name(str(row.get("OData_納入先", "")).strip())
        nony = str(row.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
        order2 = nony[-2:] if len(nony) >= 2 else nony
        secs = timeline_secs(str(row.get("入車時間", "")).strip())
        if vendor and order2 and secs is not None:
            result[(vendor, order2)] = secs
    return result


def unit_floor_deadline(
    vendor, nonyuhibin, arrival_hhmm, bin_time_map: BinTimeMap
) -> Tuple[int, Optional[int]]:
    """1ユニット（納入先×便）の (床秒, 締切秒 or None) を返す。

    締切: ユニットに付与済みの「入車時間」を優先（SPLIT_UKEIRE_ROUTES 解決済みのため）。
          無ければマスタ辞書から引く。
    床  : 前便（便番号 −1）の入車をマスタ辞書から引いて +10分。
    """
    vendor = _normalize_dest_name(str(vendor).strip())
    nony = str(nonyuhibin).strip().translate(_ZEN2HAN_DIGIT_COLON)
    order2 = nony[-2:] if len(nony) >= 2 else nony

    arrival = timeline_secs(arrival_hhmm)
    if arrival is None:
        arrival = bin_time_map.get((vendor, order2))
    deadline = max(0, int(arrival) - TEN_MIN_SECS) if arrival is not None else None

    floor = 0
    try:
        b = int(order2)
    except (TypeError, ValueError):
        b = None
    if b is not None and b > 1:
        prev_secs = bin_time_map.get((vendor, f"{b - 1:02d}"))
        if prev_secs is not None:
            floor = int(prev_secs) + TEN_MIN_SECS
    return floor, deadline


def attach_unit_time_bounds(units: pd.DataFrame, bin_time_map: BinTimeMap) -> pd.DataFrame:
    """混載判定ユニット表に _床秒 / _締切秒 列を付与する（締切不明=+inf、床不明=0）。"""
    if units is None or units.empty:
        return units
    floors, deadlines = [], []
    for _, u in units.iterrows():
        floor, deadline = unit_floor_deadline(
            u.get("納入先", ""), u.get("NONYUHIBIN", ""),
            u.get("入車時間", ""), bin_time_map,
        )
        floors.append(float(floor))
        deadlines.append(float(deadline) if deadline is not None else float("inf"))
    units = units.copy()
    units["_床秒"] = floors
    units["_締切秒"] = deadlines
    return units
