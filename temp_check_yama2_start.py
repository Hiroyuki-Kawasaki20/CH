#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Temporary test to print actual yama2 start time."""
import sys
sys.path.insert(0, '.')

from pathlib import Path
import pandas as pd
from src.services import process_assigner as pa
from src.models.constants import PROC_MAIN
import json

def _load_fixture_input_files():
    root = Path('.').resolve()
    spo_path = root / "tests" / "fixtures" / "issue42" / "spo_upload_snapshot.xlsx"
    master_path = root / "tests" / "fixtures" / "issue42" / "nyusha_master_snapshot.xlsx"

    assert spo_path.exists(), f"SPO fixture not found: {spo_path}"
    assert master_path.exists(), f"Master fixture not found: {master_path}"

    spo_df = pd.read_excel(spo_path, engine="openpyxl")
    master_df = pd.read_excel(master_path, engine="openpyxl")
    return spo_df, master_df

spo_df, master_df = _load_fixture_input_files()

# Minimal processing
details_df = pd.DataFrame([
    {"山通番": 1, "移動工数": 72.9, "納入先": "日野", "NONYUHIBIN": "202607010107"},
    {"山通番": 2, "移動工数": 50.0, "納入先": "日野", "NONYUHIBIN": "202607010207"},
])

proc_details = pa.compute_proc_details(details_df)
assigned = pa.assign_processes_by_arrival_time(proc_details, master_df)

# Extract yama2 start time
assigned_yama2 = assigned[assigned["山通番"] == 2]
if not assigned_yama2.empty:
    start_time_str = str(assigned_yama2.iloc[0].get("実開始時間", ""))
    start_secs = pa._to_operational_timeline_secs(pa._time_to_seconds(start_time_str))
    print(f"Yama2 実開始時間 (str): {start_time_str}")
    print(f"Yama2 実開始時刻 (secs): {start_secs}")
    
    # Convert to HH:MM
    hours = int(start_secs) // 3600
    minutes = (int(start_secs) % 3600) // 60
    print(f"Yama2 実開始時刻 (HH:MM): {hours:02d}:{minutes:02d}")
else:
    print("Yama2 not found in assigned result")
