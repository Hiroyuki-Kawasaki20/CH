# -*- coding: utf-8 -*-
"""山組みの床の引き当て: KVC・元町・織機は「納入先-受入」のマスタ行で引く（Issue #195 コミットA）。

実例(2026-10-15 14:53): 日野02 Q10-B-5（締切18:20）と織機08（床18:25）が同じ山にされた。
織機の床が、マスタ行「織機-28」を引けずに 0 になっていたため。
"""
import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.bin_time_rules import (
    attach_unit_time_bounds, build_bin_time_map, unit_floor_deadline,
)
from src.services.sorter import run_pipeline


def _hhmm(h, m):
    return h * 3600 + m * 60


def _master(rows):
    return pd.DataFrame(
        [{"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}
         for v, b, t in rows]
    )


def _btm(rows):
    return build_bin_time_map(_master(rows))


class _StubDataManager:
    def __init__(self, df):
        self._df = df

    def filter_shipments(self, selections):
        return self._df.copy()


def _pallet_row(vendor, nonyuhibin, height, move_cost, ukeire=""):
    return {
        "HINBAN": f"H{vendor}{nonyuhibin}",
        "サイズ種類": "1",
        "NONYUHIBIN": nonyuhibin,
        "納入先": vendor,
        "SYUKKASAKI": vendor,
        "UKEIRE": ukeire,
        "高さ": height,
        "移動工数": move_cost,
        "PLANKANBANSU": 1,
    }


def _run(shipments, master_df):
    _, _, _, _, _, mixed_details = run_pipeline(
        _StubDataManager(shipments),
        selections=None,
        height_cap=DEFAULT_HEIGHT_CAP,
        mixing_key=None,
        master_df=master_df,
    )
    return mixed_details


def _yama_of(details, vendor):
    return set(details.loc[details["納入先"] == vendor, "山通番"])


# ===== 関数単体 =====
def test_split_route_floor_uses_vendor_ukeire_key():
    btm = _btm([("織機-28", "03", "08:30"), ("織機-28", "04", "10:30"), ("織機-28", "05", "12:30")])
    floor, deadline = unit_floor_deadline("織機", "2026101205", "12:30", btm, ukeire="28")
    assert floor == _hhmm(10, 40)       # 織機04便の入車10:30 + 10分
    assert deadline == _hhmm(12, 20)


def test_split_route_same_truck_time_bins_do_not_create_floor():
    """KVC 01・02便が同じ入車時間なら床は立てない（#170と同じ考え方）。"""
    btm = _btm([("KVC-B7", "01", "18:46"), ("KVC-B7", "02", "18:46")])
    floor, _ = unit_floor_deadline("KVC", "2026101202", "18:46", btm, ukeire="B7")
    assert floor <= 0


def test_non_split_vendor_ignores_ukeire():
    btm = _btm([("拠点A", "01", "08:00"), ("拠点A", "02", "10:00")])
    with_uk = unit_floor_deadline("拠点A", "2026101202", "10:00", btm, ukeire="07")
    without = unit_floor_deadline("拠点A", "2026101202", "10:00", btm)
    assert with_uk == without == (_hhmm(8, 10), _hhmm(9, 50))


def test_split_route_without_known_ukeire_keeps_old_behavior():
    """受入が空、またはマスタに無い受入のときは、従来どおり（納入先だけで探す → 前便が無く床0）。"""
    btm = _btm([("織機-28", "07", "18:15"), ("織機-28", "08", "20:35")])
    expected_deadline = _hhmm(20, 25)
    assert unit_floor_deadline("織機", "2026101508", "20:35", btm, ukeire="") == (0, expected_deadline)
    assert unit_floor_deadline("織機", "2026101508", "20:35", btm, ukeire="99") == (0, expected_deadline)
    assert unit_floor_deadline("織機", "2026101508", "20:35", btm) == (0, expected_deadline)


def test_kvc_b7_10_and_01_floors_do_not_block_same_truck_merge():
    """#199 の対象。B7 10便と01便は、どちらも朝一06:45の同じトラック。床は0以下のまま。"""
    btm = _btm([
        ("KVC-B7", "08", "22:41"), ("KVC-B7", "09", "22:41"),
        ("KVC-B7", "10", "06:45"), ("KVC-B7", "01", "06:45"),
    ])
    floor10, dl10 = unit_floor_deadline("KVC", "2026101510", "06:45", btm, ukeire="B7")
    floor01, dl01 = unit_floor_deadline("KVC", "2026101601", "06:45", btm, ukeire="B7")
    assert floor10 <= 0 and floor01 <= 0
    assert dl10 == dl01 == _hhmm(6, 35)


def test_attach_unit_time_bounds_passes_ukeire():
    btm = _btm([("織機-28", "04", "10:30"), ("織機-28", "05", "12:30")])
    units = pd.DataFrame([{
        "納入先": "織機", "NONYUHIBIN": "2026101205", "入車時間": "12:30", "UKEIRE": "28",
    }])
    out = attach_unit_time_bounds(units, btm)
    assert out.iloc[0]["_床秒"] == _hhmm(10, 40)


# ===== パイプライン全体 =====
def test_orihata_floor_prevents_merge_with_earlier_deadline_vendor():
    """2026-10-15 14:53 の再現。織機08の床(18:25) > 日野02の締切(18:20) なので、同じ山にしない。"""
    master = _master([
        ("日野", "01", "17:00"), ("日野", "02", "18:30"),
        ("織機-28", "07", "18:15"), ("織機-28", "08", "20:35"),
    ])
    shipments = pd.DataFrame([
        _pallet_row("日野", "2026101502", 700, 72.9),
        _pallet_row("織機", "2026101508", 700, 313.74, "28"),
        _pallet_row("織機", "2026101508", 700, 313.74, "28"),
    ])
    details = _run(shipments, master)
    assert _yama_of(details, "日野").isdisjoint(_yama_of(details, "織機"))


def test_kvc_b7_same_truck_bins_stay_merged():
    """回帰防止（#199）。B7 10便と01便は同じ06:45のトラックなので、受入対応後も同じ山のまま。"""
    master = _master([
        ("KVC-B7", "01", "06:45"), ("KVC-B7", "02", "10:51"), ("KVC-B7", "03", "10:51"),
        ("KVC-B7", "04", "14:40"), ("KVC-B7", "05", "14:40"), ("KVC-B7", "06", "18:46"),
        ("KVC-B7", "07", "18:46"), ("KVC-B7", "08", "22:41"), ("KVC-B7", "09", "22:41"),
        ("KVC-B7", "10", "06:45"),
    ])
    shipments = pd.DataFrame([
        _pallet_row("KVC", "2026101510", 700, 100.0, "B7"),
        _pallet_row("KVC", "2026101601", 700, 100.0, "B7"),
    ])
    details = _run(shipments, master)
    assert details["山通番"].nunique() == 1
