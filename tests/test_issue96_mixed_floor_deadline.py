"""Issue #96: 混載山で片方の集荷可能時間(床)が他方の入車締切を殺す問題の再現。

納入先A 07便(前便06便=13:00がマスタに存在 → 床13:10)と
納入先B 01便(入車12:20 → 締切12:10)が高さ的に混載可能なとき、
現状の混載判定は時間の整合を見ず、救済(_rescue_split_conflict_vendor)も
前便を入車時間マスタから引かないため、床(13:10) > 締切(12:10) の詰み山ができる。
"""

import pandas as pd
import pytest

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import run_pipeline

_TEN_MIN = 10 * 60


class _StubDataManager:
    def __init__(self, df):
        self._df = df

    def filter_shipments(self, selections):
        return self._df.copy()


def _hhmm_to_secs(value):
    hh, mm = str(value).strip().split(":")
    return int(hh) * 3600 + int(mm) * 60


def _pallet_row(vendor, nonyuhibin, height, move_cost):
    return {
        "HINBAN": f"H{vendor}{nonyuhibin}",
        "サイズ種類": "1",
        "NONYUHIBIN": nonyuhibin,
        "納入先": vendor,
        "SYUKKASAKI": vendor,
        "高さ": height,
        "移動工数": move_cost,
        "PLANKANBANSU": 1,
    }


def _master(rows):
    return pd.DataFrame(
        [{"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}
         for v, b, t in rows]
    )


def _floor_deadline_from_master(master_df, vendor, order2):
    """(床, 締切) をマスタから計算（前便=便番号-1 / 床=前便入車+10分 / 締切=入車-10分）。"""
    m = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in master_df.iterrows()}
    arrival = m.get((vendor, order2))
    deadline = _hhmm_to_secs(arrival) - _TEN_MIN if arrival else None
    floor = 0
    if int(order2) > 1:
        prev = m.get((vendor, f"{int(order2) - 1:02d}"))
        if prev:
            floor = _hhmm_to_secs(prev) + _TEN_MIN
    return floor, deadline


def _run(shipments, master_df):
    _, _, _, _, _, mixed_details = run_pipeline(
        _StubDataManager(shipments),
        selections=None,
        height_cap=DEFAULT_HEIGHT_CAP,
        mixing_key=None,
        master_df=master_df,
    )
    return mixed_details


def _assert_all_mountains_feasible(mixed_details, master_df):
    for yama, sub in mixed_details.groupby("山通番"):
        floors, deadlines = [], []
        for _, row in sub.iterrows():
            f, d = _floor_deadline_from_master(
                master_df, str(row["納入先"]).strip(), str(row["NONYUHIBIN"]).strip()
            )
            floors.append(f)
            if d is not None:
                deadlines.append(d)
        assert not deadlines or max(floors) <= min(deadlines), (
            f"山{yama}: 床max={max(floors)}秒 > 締切min={min(deadlines)}秒 "
            f"(メンバー: {sorted(set(sub['納入先'].astype(str)))}) の詰み山が生成された"
        )


def test_mixed_mountain_does_not_pair_incompatible_floor_and_deadline():
    master_df = _master([
        ("拠点A", "06", "13:00"),  # 前便（当日データには居ない）→ 07便の床は13:10
        ("拠点A", "07", "13:30"),  # 締切 13:20
        ("拠点B", "01", "12:20"),  # 床0・締切 12:10
    ])
    shipments = pd.DataFrame([
        _pallet_row("拠点A", "07", 1000, 10),
        _pallet_row("拠点B", "01", 1200, 9),
    ])

    _assert_all_mountains_feasible(_run(shipments, master_df), master_df)


def test_mixed_mountain_with_compatible_times_stays_merged():
    """時間整合の取れた別納入先の混載は分割されないこと（過剰分割ガード）。"""
    master_df = _master([
        ("拠点A", "06", "13:00"),
        ("拠点A", "07", "13:30"),  # 床13:10・締切13:20
        ("拠点C", "01", "14:00"),  # 床0・締切13:50 → max床13:10 ≤ min締切13:20 で両立
    ])
    shipments = pd.DataFrame([
        _pallet_row("拠点A", "07", 1000, 10),
        _pallet_row("拠点C", "01", 1200, 9),
    ])

    mixed_details = _run(shipments, master_df)

    assert mixed_details["山通番"].nunique() == 1
    _assert_all_mountains_feasible(mixed_details, master_df)