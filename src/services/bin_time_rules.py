# -*- coding: utf-8 -*-
"""Issue #96: (納入先, 便) → (開始床, 締切) の共通計算ヘルパー。

定義:
- 締切 = 自便の入車時刻 − 20分（山はこの時刻までに完了していること）
- 床   = 前便の入車時刻 + 10分（前便が落ち着くまで着手しない）

日跨ぎ軸は process_assigner と同じ 03:00 基準（03:00未満は +24h）に統一する。
sorter 従来実装（_timeline_secs）の 06:25 基準との軸ズレ（Issue #27 の親戚 = #96 穴3）を
ここで解消する。

前便解決（#96 穴2）: 01便の前便は「その納入先の最終便」（河崎様確認済み）。
process_assigner._get_prev_bin_for_vendor（wrap対応）と
process_assigner._cycle_aware_prev_floor_secs（前便が前日側に見える場合の-24h補正）を
そのまま再利用し、ロジックの二重実装を避ける。
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..models.constants import PICKUP_DEADLINE_BUFFER_SECS
from ..utils.normalizer import (
    _normalize_dest_name, _normalize_hhmm, _ZEN2HAN_DIGIT_COLON,
)
from .process_assigner import _get_prev_bin_for_vendor, _cycle_aware_prev_floor_secs

logger = logging.getLogger(__name__)

FLOOR_BUFFER_SECS = 10 * 60
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


def _vendor_bin_numbers(bin_time_map: BinTimeMap, vendor: str) -> List[int]:
    """bin_time_map から対象納入先の便番号一覧（int・昇順）を導出する（#96 穴2）。"""
    bins = set()
    for (v, order2) in bin_time_map.keys():
        if v != vendor:
            continue
        try:
            bins.add(int(order2))
        except (TypeError, ValueError):
            continue
    return sorted(bins)


def unit_floor_deadline(
    vendor, nonyuhibin, arrival_hhmm, bin_time_map: BinTimeMap
) -> Tuple[int, Optional[int]]:
    """1ユニット（納入先×便）の (床秒, 締切秒 or None) を返す。

    締切: ユニットに付与済みの「入車時間」を優先（SPLIT_UKEIRE_ROUTES 解決済みのため）。
          無ければマスタ辞書から引く。
    床  : 前便（01便は最終便へ巻き戻り = process_assigner._get_prev_bin_for_vendor）の
          入車 + 10分。前便が前日側に見える場合は -24h 補正（_cycle_aware_prev_floor_secs）。
    """
    vendor = _normalize_dest_name(str(vendor).strip())
    nony = str(nonyuhibin).strip().translate(_ZEN2HAN_DIGIT_COLON)
    order2 = nony[-2:] if len(nony) >= 2 else nony

    arrival = timeline_secs(arrival_hhmm)
    if arrival is None:
        arrival = bin_time_map.get((vendor, order2))
    deadline = max(0, int(arrival) - PICKUP_DEADLINE_BUFFER_SECS) if arrival is not None else None

    floor = 0
    try:
        b = int(order2)
    except (TypeError, ValueError):
        b = None
    if b is not None:
        vendor_bins = _vendor_bin_numbers(bin_time_map, vendor)
        prev_bin = _get_prev_bin_for_vendor(
            vendor, b, {vendor: vendor_bins}, allow_wrap=True, offset=1,
        )
        if prev_bin is not None:
            prev_secs = bin_time_map.get((vendor, prev_bin))
            if prev_secs is not None:
                if arrival is not None:
                    floor = _cycle_aware_prev_floor_secs(int(prev_secs), int(arrival))
                else:
                    floor = int(prev_secs) + FLOOR_BUFFER_SECS
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
