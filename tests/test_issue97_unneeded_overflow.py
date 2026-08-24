# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""Issue #97: 不要な「あふれ」レーン投入の再現テスト（strict xfail・実データスナップショット）

2026-08-24 19:54 実行の実データ（20山）で、日野04便（NONYUHIBIN 下2桁=04）の3山が
あふれ工程へ振られた。実際は床(19:16)開始で全山締切超過なし・リリーフは17:59以降空き。
期待値の根拠: 出力スナップショットは別途保管。
"""
from pathlib import Path

import pandas as pd
import pytest

from src.services import process_assigner as pa
from src.services.data_loader import load_pickup_time_master_xlsx
from tests.unit.test_relief_earliest_start import (
    _build_detail_rows_from_spo_vendor_aware,
    _compute_work_secs_by_yama,
    _compute_deadline_map,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "issue97"
# 19:54実行は履歴選択なし（初回動作）ではないため、再現条件の候補としてNoneを明示。
PREV_LANE_END_TIMES = None


def _load_snapshot():
    spo_df = pd.read_excel(FIXTURE_DIR / "spo_upload_snapshot.xlsx", engine="openpyxl")
    master_df = load_pickup_time_master_xlsx(FIXTURE_DIR / "nyusha_master_snapshot.xlsx")
    return spo_df, master_df


def _hino04_yamas(details_df: pd.DataFrame) -> set:
    d = details_df.copy()
    d["納入先"] = d["納入先"].astype(str).map(pa._normalize_dest_name)
    hit = d[(d["納入先"] == "日野")
            & (d["NONYUHIBIN"].astype(str).str.strip().str[-2:] == "04")]
    return set(int(y) for y in hit["山通番"].unique())


def _floor_map_for(details_df, master_df, yamas):
    """対象山ごとの床（前便入車 + ARRIVAL_BUFFER_SECS の最大）を計算。日野04便は≈19:16。"""
    m = master_df.copy()
    m["OData_納入先"] = m["OData_納入先"].astype(str).str.strip().map(pa._normalize_dest_name)
    m["NONYUHIBIN"] = m["NONYUHIBIN"].astype(str).str.strip()
    m["入車時間"] = m["入車時間"].astype(str).str.strip()
    master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in m.iterrows()}

    floors = {}
    for yama in yamas:
        vals = []
        for _, row in details_df[details_df["山通番"] == yama].iterrows():
            vendor = pa._normalize_dest_name(str(row.get("納入先", "")).strip())
            nony = str(row.get("NONYUHIBIN", "")).strip().translate(pa._ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue
            if vendor == "KVC":
                uk = str(row.get("UKEIRE", "")).strip()
                vendor = f"KVC-{uk}" if uk else vendor
            try:
                prev_bin = f"{int(order2) - 1:02d}" if int(order2) > 1 else None
            except ValueError:
                continue
            if prev_bin is None:
                continue
            prev_pickup = master_map.get((vendor, prev_bin), "")
            if not prev_pickup:
                continue
            secs = pa._to_operational_timeline_secs(pa._time_to_seconds(prev_pickup))
            if secs is not None:
                vals.append(int(secs) + pa.ARRIVAL_BUFFER_SECS)
        if vals:
            floors[yama] = max(vals)
    return floors


@pytest.mark.xfail(
    strict=True,
    reason="Issue #97: 一時的なリリーフ混雑での誤判定＋単一便山の救済欠如＋あふれ片道切符により、"
           "床開始で締切内完了できる日野04便3山が不要にあふれへ送られる",
)
def test_issue97_hino04_trio_not_sent_to_unneeded_overflow():
    spo_df, master_df = _load_snapshot()
    details_df = _build_detail_rows_from_spo_vendor_aware(spo_df, master_df)
    proc_details = pa.compute_proc_details(details_df)
    out = pa.assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times=PREV_LANE_END_TIMES,
    )

    trio = _hino04_yamas(details_df)
    assert trio, "fixtureに日野04便の山が見つからない（fixture取り違えの疑い）"

    uniq = out[["山通番", "山工程", "実開始時間"]].drop_duplicates(subset=["山通番"])
    proc_map = {int(r["山通番"]): str(r["山工程"]) for _, r in uniq.iterrows()}
    start_map = {
        int(r["山通番"]): pa._to_operational_timeline_secs(
            pa._time_to_seconds(str(r["実開始時間"]))
        )
        for _, r in uniq.iterrows()
    }

    failures = []
    on_overflow = sorted(y for y in trio if "あふれ" in proc_map.get(y, ""))
    if on_overflow:
        failures.append(f"(a) 日野04便の山があふれ工程に振られている: {on_overflow}")

    work_map = _compute_work_secs_by_yama(details_df)
    deadline_map = _compute_deadline_map(details_df, master_df)
    late = []
    for yama_no, deadline in deadline_map.items():
        st = start_map.get(yama_no)
        if st is None:
            continue
        end_secs = pa._calc_work_end_with_breaks(int(st), int(work_map.get(yama_no, 0)))
        if end_secs > int(deadline):
            late.append((yama_no, int(st), int(end_secs), int(deadline)))
    if late:
        failures.append(f"(b) 締切超過が発生: {late}")

    floor_map = _floor_map_for(details_df, master_df, trio)
    early = {
        y: (start_map.get(y), floor_map[y])
        for y in floor_map
        if start_map.get(y) is not None and int(start_map[y]) < int(floor_map[y])
    }
    if early:
        failures.append(f"(c) 床より前に開始している日野04山がある(start, floor): {early}")

    assert not failures, "\n".join(failures)