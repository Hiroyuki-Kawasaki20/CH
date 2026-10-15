# -*- coding: utf-8 -*-
"""セットあり便の前便は、同じ入車時刻の便（同じトラック）を飛ばして探す。

実例(2026-10-15 10:09): KVC-B7 10便(10/15分)と01便(10/16分)は、どちらも朝一06:45の
同じトラックに載せる（現場確認）。01便の巡回上の前便は10便(06:45、同じ時刻)のため、
床06:55・締切(1直上限)15:20になり、10便(床22:51・締切25:35)と混ぜた山は
床22:51 > 締切15:20 で成り立たず「あふれ」になった。
"""
import pandas as pd

from src.models.constants import PROC_MAIN
from src.services.process_assigner import (
    _time_to_seconds,
    _to_operational_timeline_secs,
    assign_processes_by_arrival_time,
)

FLOOR_2CHOKU_2251 = 22 * 3600 + 51 * 60  # 09便 22:41 + 10分


def _master():
    times = {
        "01": "06:45", "02": "10:51", "03": "10:51", "04": "14:40", "05": "14:40",
        "06": "18:46", "07": "18:46", "08": "22:41", "09": "22:41", "10": "06:45",
    }
    rows = [
        {"OData_納入先": "KVC-B7", "NONYUHIBIN": b, "入車時間": t,
         "セットありフラグ": "1" if b in ("01", "10") else ""}
        for b, t in times.items()
    ]
    return pd.DataFrame(rows)


def _yama(*nonyuhibins):
    n = len(nonyuhibins)
    return pd.DataFrame({
        "山通番": [1] * n,
        "納入先": ["KVC"] * n,
        "NONYUHIBIN": list(nonyuhibins),
        "UKEIRE": ["B7"] * n,
        "移動工数": [300.0] * n,
    })


def _op_start(out):
    return _to_operational_timeline_secs(_time_to_seconds(out.iloc[0]["実開始時間"]))


def test_same_truck_set_flag_bins_mixed_yama_stays_main():
    """B7 10便と01便（同じ06:45のトラック）の混載山は、前夜2直のメイン工程で間に合う。"""
    out = assign_processes_by_arrival_time(_yama("2026101510", "2026101601"), _master())
    row = out.iloc[0]
    assert row["山工程"] == PROC_MAIN, row.to_dict()
    assert bool(row["締切超過"]) is False, row.to_dict()
    assert _op_start(out) >= FLOOR_2CHOKU_2251, row["実開始時間"]


def test_set_flag_bin_after_same_time_bin_uses_previous_truck_floor():
    """B7 01便だけの山も、前便は10便(同じ06:45)ではなく09便(22:41)。床は22:51。"""
    out = assign_processes_by_arrival_time(_yama("2026101601"), _master())
    assert _op_start(out) >= FLOOR_2CHOKU_2251, out.iloc[0]["実開始時間"]
    assert bool(out.iloc[0]["締切超過"]) is False


def test_set_flag_bin_with_different_time_prev_is_unchanged():
    """回帰防止: B7 10便は前便09便(22:41)のまま。床22:51、締切超過なし。"""
    out = assign_processes_by_arrival_time(_yama("2026101510"), _master())
    assert _op_start(out) >= FLOOR_2CHOKU_2251, out.iloc[0]["実開始時間"]
    assert bool(out.iloc[0]["締切超過"]) is False