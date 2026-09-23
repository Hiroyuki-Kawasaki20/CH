"""Issue #170: 救済分割(_rescue_split_conflict_vendor)が「同一入車時間(=同一トラック)」の
便を前便と誤認し、不要な床を立てて正しく混載できていた山を誤って分割してしまう不具合の
再現・固定化。

旧実装は前便(便番号-1)の入車時刻をそのまま+10分するだけで、前便が「今の便と全く同じ
入車時刻」であっても補正しない。unit_floor_deadline(_cycle_aware_prev_floor_secs)への
統一後は、前便>=今の便の入車時刻であれば-24h補正が働き、床は0に潰れる。
"""

import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import run_pipeline


class _StubDataManager:
    def __init__(self, df):
        self._df = df

    def filter_shipments(self, selections):
        return self._df.copy()


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


def _run(shipments, master_df):
    _, _, _, _, _, mixed_details = run_pipeline(
        _StubDataManager(shipments),
        selections=None,
        height_cap=DEFAULT_HEIGHT_CAP,
        mixing_key=None,
        master_df=master_df,
    )
    return mixed_details


def test_rescue_split_does_not_misfire_on_same_truck_time():
    """拠点D 06便・07便が入車時刻13:30で完全一致（天候不順等の出荷ズレで同じ物理
    トラックが2便として記録される運用）。07便は拠点E 01便(入車13:20)と高さ的に
    混載可能であり、正しい床計算(=0)なら両者は同一山のまま残るべき。
    旧実装では07便の床が「13:30+10分=13:40」に誤って立ち、01便の締切(13:00)を
    超えるため、誤って別山に分割されていた。
    """
    master_df = _master([
        ("拠点D", "06", "13:30"),
        ("拠点D", "07", "13:30"),  # 06と入車時刻が完全一致＝同一トラック
        ("拠点E", "01", "13:20"),
    ])
    shipments = pd.DataFrame([
        _pallet_row("拠点D", "06", 100, 1),
        _pallet_row("拠点D", "07", 700, 8),
        _pallet_row("拠点E", "01", 700, 8),
    ])

    mixed_details = _run(shipments, master_df)

    row_07 = mixed_details[
        (mixed_details["納入先"] == "拠点D") & (mixed_details["NONYUHIBIN"] == "07")
    ]
    row_01 = mixed_details[
        (mixed_details["納入先"] == "拠点E") & (mixed_details["NONYUHIBIN"] == "01")
    ]
    assert not row_07.empty and not row_01.empty

    assert row_07.iloc[0]["山通番"] == row_01.iloc[0]["山通番"], (
        "拠点D-07便（前便06便と入車時刻が完全一致＝同一トラック）が、"
        "誤って06便を『別トラックの前便』と誤認し、救済分割で"
        "拠点E-01便と切り離されてしまった（Issue #170の回帰）"
    )