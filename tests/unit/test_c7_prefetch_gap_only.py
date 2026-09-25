import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import pytest
import src.services.process_assigner as pa
from src.services.process_assigner import (
    assign_processes_by_arrival_time, compute_proc_details, _time_to_seconds,
)

def _row(v, b, t):
    return {"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}

def _first_yama(details, master, prev=None):
    r = assign_processes_by_arrival_time(
        compute_proc_details(pd.DataFrame(details)), pd.DataFrame(master),
        previous_lane_end_times=prev)
    s = {int(x["山通番"]): _time_to_seconds(str(x["実開始時間"])) for _, x in r.iterrows()}
    return min(s, key=s.get), s

# テスト1: 昼明け、両方11:50スタートのとき、締切の早い山が先か
MASTER_1 = [
    _row("高岡", "01", "10:30"), _row("高岡", "02", "12:30"),   # 締切12:20・着手10:40〜
    _row("日野", "11", "11:06"), _row("日野", "12", "12:05"),
    _row("日野", "13", "13:21"),                                 # 締切13:11・着手11:16〜
]
DETAILS_1 = [
    {"山通番": 1, "移動工数": 0, "納入先": "高岡", "NONYUHIBIN": "2026092502", "高さ": 300},
    {"山通番": 2, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026092513", "高さ": 300},
]

@pytest.mark.parametrize("gap_only, expected", [(False, 2), (True, 1)])
def test_c7_lunch_resume_order(monkeypatch, gap_only, expected):
    monkeypatch.setattr(pa, "MAIN_PREFETCH_GAP_ONLY", gap_only)
    first, s = _first_yama(DETAILS_1, MASTER_1)
    assert first == expected, f"開始時刻: {s}"

# テスト2: メインが10:00から空く日に、07:38から着手できる山を「穴埋め」扱いで先頭にしないか
MASTER_2 = [
    _row("高岡", "01", "07:28"), _row("高岡", "02", "12:21"),   # 元町-1W 便03相当（締切12:11・着手07:38〜）
    _row("日野", "10", "09:25"), _row("日野", "11", "11:06"),
    _row("日野", "12", "12:05"),                                 # 締切11:55・着手09:35〜
]
DETAILS_2 = [
    {"山通番": 1, "移動工数": 0, "納入先": "高岡", "NONYUHIBIN": "2026092502", "高さ": 300},
    {"山通番": 2, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026092512", "高さ": 300},
]

@pytest.mark.parametrize("gap_only, expected", [(False, 1), (True, 2)])
def test_c7_no_phantom_gap(monkeypatch, gap_only, expected):
    monkeypatch.setattr(pa, "MAIN_PREFETCH_GAP_ONLY", gap_only)
    first, s = _first_yama(DETAILS_2, MASTER_2, prev={pa.PROC_MAIN: 10 * 3600})
    assert first == expected, f"開始時刻: {s}"