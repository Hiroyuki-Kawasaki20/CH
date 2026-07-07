"""Investigation test: beam search vs forced exhaustive on latest real SPO data."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from src.models.constants import BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL, PROC_OVERFLOW
from src.services import process_assigner as pa


def _load_input_files() -> Tuple[pd.DataFrame, pd.DataFrame]:
    root = Path(__file__).resolve().parents[2]
    spo_path = root / "SPOアップロード用.xlsx"
    master_path = root / "入車時間マスタ.xlsx"

    assert spo_path.exists(), f"SPO file not found: {spo_path}"
    assert master_path.exists(), f"Master file not found: {master_path}"

    spo_df = pd.read_excel(spo_path, engine="openpyxl")
    master_df = pd.read_excel(master_path, engine="openpyxl")
    return spo_df, master_df


def _parse_groupeddata(cell) -> List[dict]:
    if isinstance(cell, list):
        return [x for x in cell if isinstance(x, dict)]
    if isinstance(cell, dict):
        return [cell]
    if cell is None:
        return []
    s = str(cell).strip()
    if not s or s.lower() == "nan":
        return []
    for cand in (s, s[1:-1] if s.startswith('"') and s.endswith('"') and len(s) >= 2 else s):
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except Exception:
                continue
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        if isinstance(obj, dict):
            return [obj]
    return []


def _build_detail_rows_from_spo(spo_df: pd.DataFrame) -> pd.DataFrame:
    assert "グループ番号" in spo_df.columns, "SPO is missing required unique key column: グループ番号"
    rows: List[dict] = []

    for _, spo_row in spo_df.iterrows():
        # 山識別はグループ番号のみを使う。
        # タイトルは工程ごとに再採番されるため識別子として使わない。
        yama = spo_row.get("グループ番号", None)
        if pd.isna(yama):
            continue
        yama_no = int(yama)

        pick_cost = pd.to_numeric(spo_row.get("引取工数", 0), errors="coerce")
        pick_cost_secs = int(pick_cost) if pd.notna(pick_cost) else 0

        grouped = _parse_groupeddata(spo_row.get("GroupedData", spo_row.get("groupdata", "")))
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
            vendor = str(item.get("OData_納入先") or item.get("OData__x7d0d__x5165__x5148_", "")).strip()
            nony = str(item.get("NONYUHIBIN", "")).strip()
            if not vendor:
                vendor = "UNKNOWN"
            if not nony:
                nony = "00"

            rows.append(
                {
                    "山通番": yama_no,
                    "移動工数": inferred_max_move if i == 0 else 0,
                    "納入先": vendor,
                    "NONYUHIBIN": nony,
                    "高さ": 300,
                    "UKEIRE": str(item.get("UKEIRE", "")).strip(),
                }
            )

    out = pd.DataFrame(rows)
    assert not out.empty, "detail_rows reconstruction resulted in empty dataframe"
    return out


def _build_master_df(master_df: pd.DataFrame) -> pd.DataFrame:
    required = ["OData_納入先", "NONYUHIBIN", "入車時間"]
    for col in required:
        assert col in master_df.columns, f"Master is missing required column: {col}"

    out = master_df.copy()
    if "セットありフラグ" not in out.columns:
        out["セットありフラグ"] = ""
    out = out[["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]].copy()
    out["OData_納入先"] = out["OData_納入先"].astype(str).str.strip()
    out["NONYUHIBIN"] = out["NONYUHIBIN"].astype(str).str.strip()
    out["入車時間"] = out["入車時間"].astype(str).str.strip()
    out["セットありフラグ"] = out["セットありフラグ"].astype(str).str.strip()
    return out


def _run_with_threshold(proc_details: pd.DataFrame, master_df: pd.DataFrame, threshold: int) -> pd.DataFrame:
    original_legacy = pa._legacy_assign_processes_by_arrival_time
    source = inspect.getsource(pa._legacy_assign_processes_by_arrival_time)
    needle = "EXHAUSTIVE_THRESHOLD = 14"
    assert needle in source, "Could not find EXHAUSTIVE_THRESHOLD literal in source"
    patched_source = source.replace(needle, f"EXHAUSTIVE_THRESHOLD = {threshold}")

    local_ns: Dict[str, object] = {}
    exec(patched_source, pa.__dict__, local_ns)
    patched_legacy = local_ns["_legacy_assign_processes_by_arrival_time"]

    try:
        pa._legacy_assign_processes_by_arrival_time = patched_legacy
        return pa.assign_processes_by_arrival_time(proc_details, master_df)
    finally:
        pa._legacy_assign_processes_by_arrival_time = original_legacy


def _overflow_set(result_df: pd.DataFrame) -> set:
    overflow = result_df.loc[result_df["山工程"].astype(str) == PROC_OVERFLOW, "山通番"]
    return set(int(x) for x in overflow.tolist())


def _proc_map(result_df: pd.DataFrame) -> Dict[int, str]:
    return {
        int(r["山通番"]): str(r["山工程"])
        for _, r in result_df[["山通番", "山工程"]].drop_duplicates(subset=["山通番"]).iterrows()
    }


def test_overflow_beam_vs_exhaustive_on_latest_real_data():
    spo_df, raw_master_df = _load_input_files()
    details_df = _build_detail_rows_from_spo(spo_df)
    master_df = _build_master_df(raw_master_df)

    unique_yamas = int(details_df["山通番"].nunique())

    proc_details = pa.compute_proc_details(details_df)

    # 閾値14（現行）: 15山ならビーム探索にフォールバック
    beam_result = _run_with_threshold(proc_details, master_df, threshold=14)
    # 閾値99（検証用）: 全探索を強制
    exhaustive_result = _run_with_threshold(proc_details, master_df, threshold=99)

    beam_overflow = _overflow_set(beam_result)
    exhaustive_overflow = _overflow_set(exhaustive_result)

    beam_map = _proc_map(beam_result)
    exhaustive_map = _proc_map(exhaustive_result)

    changed_yamas = sorted(set(beam_map.keys()) | set(exhaustive_map.keys()))
    changed_yamas = [y for y in changed_yamas if beam_map.get(y) != exhaustive_map.get(y)]

    assert beam_overflow == exhaustive_overflow, (
        "Overflow set differs between beam and exhaustive.\n"
        f"spo_rows={len(spo_df)} unique_yamas={unique_yamas}\n"
        f"beam_overflow={sorted(beam_overflow)}\n"
        f"exhaustive_overflow={sorted(exhaustive_overflow)}\n"
        f"only_beam={sorted(beam_overflow - exhaustive_overflow)}\n"
        f"only_exhaustive={sorted(exhaustive_overflow - beam_overflow)}\n"
        f"changed_proc_yamas={[(y, beam_map.get(y), exhaustive_map.get(y)) for y in changed_yamas]}"
    )