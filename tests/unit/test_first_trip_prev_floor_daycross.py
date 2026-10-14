# -*- coding: utf-8 -*-
"""各直1便目の「前便入車+10分」が、前サイクル(前夜〜未明)の便を床にしないこと。

実例(2026-10-14 15:02:58): 豊鉄広久手02便(入車11:40)の前便01便は00:40入車。
00:40は業務日タイムラインで24:40扱いのため、床が24:50になった。あふれ/リリーフの開始が
24:50になり、締切の+24h補正(_deadline_for_eval)で「間に合う」扱いになって締切超過が隠れた。
"""
import pandas as pd
import pytest

from src.services.process_assigner import DAY_SECS, assign_processes_by_arrival_time

SHIFT1_FIRST_TRIP_START = 6 * 3600 + 50 * 60  # 1直開始 06:25 + 25分


def _master(vendor, prev_time):
    rows = [
        {"OData_納入先": vendor, "NONYUHIBIN": "01", "入車時間": prev_time, "セットありフラグ": ""},
        {"OData_納入先": vendor, "NONYUHIBIN": "02", "入車時間": "11:40", "セットありフラグ": ""},
    ]
    return pd.DataFrame(rows)


def _heavy_single_yama(vendor):
    """移動工数を極端に大きくして、どの時刻に始めても締切(11:30)に間に合わない山にする。"""
    return pd.DataFrame({
        "山通番": [1],
        "納入先": [vendor],
        "NONYUHIBIN": ["2026101402"],
        "UKEIRE": [""],
        "移動工数": [20000.0],
    })


def _start_secs(hhmm: str) -> int:
    hh, mm = str(hhmm).split(":")
    return int(hh) * 3600 + int(mm) * 60


@pytest.mark.parametrize("prev_time", ["00:40", "01:00"])
def test_first_trip_start_ignores_previous_cycle_bin(prev_time):
    out = assign_processes_by_arrival_time(
        _heavy_single_yama("テスト便"), _master("テスト便", prev_time)
    )
    start = _start_secs(out.iloc[0]["実開始時間"])
    assert SHIFT1_FIRST_TRIP_START <= start < DAY_SECS, out.iloc[0]["実開始時間"]


def test_first_trip_unmeetable_deadline_is_flagged_late():
    out = assign_processes_by_arrival_time(
        _heavy_single_yama("テスト便"), _master("テスト便", "00:40")
    )
    assert bool(out.iloc[0]["締切超過"]) is True