# -*- coding: utf-8 -*-
"""分割救済(_can_relief_if_split)で、混載山の開始が山の床より早くならないこと。

実例(2026-10-12): 日野12便(1P)+織機05便(2P)の混載山が、日野12便の床 09:35 で
開始され、織機05便の床 10:40(織機04便の入車10:30+10分)を65分破った。
"""
import pandas as pd

from src.models.constants import PROC_RELIEF
from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    _time_to_seconds,
)

ORIHATA_05_FLOOR = 10 * 3600 + 40 * 60  # 10:40


def _master() -> pd.DataFrame:
    rows = [
        ("日野", "10", "09:25", ""),
        ("日野", "11", "11:06", ""),
        ("日野", "12", "12:05", ""),
        ("織機-28", "03", "08:30", ""),
        ("織機-28", "04", "10:30", ""),
        ("織機-28", "05", "12:30", ""),
    ]
    return pd.DataFrame(
        rows, columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]
    )


def _mixed_yama() -> pd.DataFrame:
    return pd.DataFrame({
        "山通番": [1, 1, 1],
        "納入先": ["日野", "織機", "織機"],
        "NONYUHIBIN": ["2026101212", "2026101205", "2026101205"],
        "UKEIRE": ["07", "28", "28"],
        "移動工数": [72.9, 313.74, 313.74],
    })


def test_split_rescue_start_is_not_before_yama_floor():
    out = assign_processes_by_arrival_time(_mixed_yama(), _master())
    row = out.iloc[0]
    start = _time_to_seconds(row["実開始時間"])
    assert start >= ORIHATA_05_FLOOR, (
        f"山の床 10:40 より早い開始: {row['実開始時間']} ({row['山工程']})"
    )


def test_unsplit_mixed_yama_is_flagged_late_instead_of_hidden():
    out = assign_processes_by_arrival_time(_mixed_yama(), _master())
    assert bool(out.iloc[0]["締切超過"]) is True


def test_yama_stays_in_relief_lane():
    out = assign_processes_by_arrival_time(_mixed_yama(), _master())
    assert out.iloc[0]["山工程"] == PROC_RELIEF