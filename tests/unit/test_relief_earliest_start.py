from __future__ import annotations

import json
from typing import Dict
from pathlib import Path

import pandas as pd

from src.models.constants import BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL, PROC_MAIN
from src.services import process_assigner as pa
from src.services.data_loader import load_pickup_time_master_xlsx

from tests.unit.test_overflow_beam_vs_exhaustive import _load_input_files


def _build_detail_rows_from_spo_vendor_aware(spo_df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    master_vendors = set(
        master_df["OData_納入先"].astype(str).str.strip().map(pa._normalize_dest_name).tolist()
    )

    for _, spo_row in spo_df.iterrows():
        yama = spo_row.get("グループ番号", None)
        if pd.isna(yama):
            continue
        yama_no = int(yama)

        pick_cost = pd.to_numeric(spo_row.get("引取工数", 0), errors="coerce")
        pick_cost_secs = int(pick_cost) if pd.notna(pick_cost) else 0

        grouped_cell = spo_row.get("GroupedData", spo_row.get("groupdata", ""))
        grouped = []
        if isinstance(grouped_cell, str) and grouped_cell.strip():
            try:
                grouped = json.loads(grouped_cell)
            except Exception:
                grouped = []
        elif isinstance(grouped_cell, list):
            grouped = grouped_cell

        if not grouped:
            grouped = [{}]

        pal = len(grouped)
        inferred_max_move = max(
            0,
            int(
                round(
                    pick_cost_secs
                    - BASE_ONE_TIME
                    - ((pal - 1) * MIDDLE_WORK)
                    - (pal * BASE_PER_PAL)
                )
            ),
        )

        for i, item in enumerate(grouped):
            vendor = ""
            for k, v in item.items():
                if not str(k).startswith("OData_"):
                    continue
                vv = str(v).strip()
                if pa._normalize_dest_name(vv) in master_vendors:
                    vendor = vv
                    break

            ukeire = str(item.get("UKEIRE", "")).strip()
            if not vendor and ukeire in {"B7", "B3"}:
                vendor = "KVC"
            if not vendor:
                vendor = str(item.get("OData_納入先") or item.get("OData__x7d0d__x5165__x5148_") or "").strip()
            if not vendor:
                vendor = "UNKNOWN"

            nony = str(item.get("NONYUHIBIN", "")).strip()
            if not nony:
                nony = "00"

            rows.append(
                {
                    "山通番": yama_no,
                    "移動工数": inferred_max_move if i == 0 else 0,
                    "納入先": vendor,
                    "NONYUHIBIN": nony,
                    "高さ": 300,
                    "UKEIRE": ukeire,
                }
            )

    out = pd.DataFrame(rows)
    assert not out.empty, "detail_rows reconstruction resulted in empty dataframe"
    return out


def _compute_work_secs_by_yama(details_df: pd.DataFrame) -> Dict[int, int]:
    out: Dict[int, int] = {}
    work_df = details_df.copy()
    work_df["移動工数"] = pd.to_numeric(work_df.get("移動工数", 0), errors="coerce").fillna(0)
    for yama, sub in work_df.groupby("山通番", sort=True):
        pal = int(sub.shape[0])
        max_cost = float(sub["移動工数"].max()) if pal > 0 else 0.0
        out[int(yama)] = int(round(max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL)))
    return out


def _compute_deadline_map(details_df: pd.DataFrame, master_df: pd.DataFrame) -> Dict[int, int]:
    m = master_df.copy()
    m["OData_納入先"] = m["OData_納入先"].astype(str).str.strip().map(pa._normalize_dest_name)
    m["NONYUHIBIN"] = m["NONYUHIBIN"].astype(str).str.strip()
    m["入車時間"] = m["入車時間"].astype(str).str.strip()
    master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in m.iterrows()}

    ddl_map: Dict[int, int] = {}
    for yama, sub in details_df.groupby("山通番", sort=True):
        yama_no = int(yama)
        y_deadline = None
        for _, row in sub.iterrows():
            vendor = pa._normalize_dest_name(str(row.get("納入先", "")).strip())
            nony = str(row.get("NONYUHIBIN", "")).strip().translate(pa._ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue

            if vendor == "KVC":
                ukeire = str(row.get("UKEIRE", "")).strip()
                lookup_vendor = f"KVC-{ukeire}" if ukeire else vendor
            else:
                lookup_vendor = vendor

            pickup = master_map.get((lookup_vendor, order2), "")
            if not pickup:
                continue

            pickup_secs = pa._to_operational_timeline_secs(pa._time_to_seconds(pickup))
            if pickup_secs is None:
                continue
            strict_deadline = max(0, int(pickup_secs) - pa.ARRIVAL_BUFFER_SECS)
            if y_deadline is None or strict_deadline < y_deadline:
                y_deadline = strict_deadline

        if y_deadline is not None:
            ddl_map[yama_no] = int(y_deadline)
    return ddl_map


def test_relief_yama_uses_earliest_feasible_start():
    spo_df, raw_master_df = _load_input_files()
    _ = raw_master_df
    root = Path(__file__).resolve().parents[2]
    master_df = load_pickup_time_master_xlsx(root / "入車時間マスタ.xlsx")
    details_df = _build_detail_rows_from_spo_vendor_aware(spo_df, master_df)

    proc_details = pa.compute_proc_details(details_df)
    assigned = pa.assign_processes_by_arrival_time(proc_details, master_df)

    proc_map = {
        int(r["山通番"]): str(r["山工程"])
        for _, r in assigned[["山通番", "山工程"]].drop_duplicates(subset=["山通番"]).iterrows()
    }
    start_map = {
        int(r["山通番"]): pa._to_operational_timeline_secs(pa._time_to_seconds(str(r.get("実開始時間", ""))))
        for _, r in assigned[["山通番", "実開始時間"]].drop_duplicates(subset=["山通番"]).iterrows()
    }

    work_map = _compute_work_secs_by_yama(details_df)
    deadline_map = _compute_deadline_map(details_df, master_df)

    failures = []

    # (a) 山2はメイン工程に残るべき
    if proc_map.get(2) != PROC_MAIN:
        failures.append(f"(a) expected yama2 in メイン but got {proc_map.get(2)}")

    # (b) 山2開始は空き窓内（23:20=84000 〜 23:45=85500）であるべき
    y2_start = start_map.get(2)
    if y2_start is None:
        failures.append("(b) yama2 start time is missing")
    elif not (84000 <= int(y2_start) <= 85500):
        failures.append(f"(b) expected yama2 start in [84000,85500] but got {int(y2_start)}")

    # (c) 全山で締切非侵害
    late = []
    for yama_no, deadline in deadline_map.items():
        st = start_map.get(yama_no)
        if st is None:
            continue
        end_secs = pa._calc_work_end_with_breaks(int(st), int(work_map.get(yama_no, 0)))
        if end_secs > int(deadline):
            late.append((yama_no, int(st), int(end_secs), int(deadline)))
    if late:
        failures.append(f"(c) deadline violation(s): {late}")

    assert not failures, "\n".join(failures)
