# -*- coding: utf-8 -*-
"""Issue #101: Issue #97 のあふれ山を最早空き窓へ前詰めする回帰テスト。"""
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
PREV_LANE_END_TIMES = None


def _load_snapshot():
    spo_df = pd.read_excel(FIXTURE_DIR / "spo_upload_snapshot.xlsx", engine="openpyxl")
    master_df = load_pickup_time_master_xlsx(FIXTURE_DIR / "nyusha_master_snapshot.xlsx")
    return spo_df, master_df


def _hino_yamas(details_df: pd.DataFrame, order: str) -> set[int]:
    normalized = details_df.copy()
    normalized["納入先"] = normalized["納入先"].astype(str).map(pa._normalize_dest_name)
    return set(
        int(yama)
        for yama in normalized.loc[
            (normalized["納入先"] == "日野")
            & (normalized["NONYUHIBIN"].astype(str).str.strip().str[-2:] == order),
            "山通番",
        ].unique()
    )


def _floor_for_hino04(master_df: pd.DataFrame) -> int:
    master = master_df.copy()
    master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip().map(pa._normalize_dest_name)
    master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip()
    row = master[(master["OData_納入先"] == "日野") & (master["NONYUHIBIN"] == "02")].iloc[0]
    return int(pa._to_operational_timeline_secs(pa._time_to_seconds(row["入車時間"]))) + pa.ARRIVAL_BUFFER_SECS


def test_issue97_followup_hino04_is_front_packed_without_hino_interleave():
    spo_df, master_df = _load_snapshot()
    details_df = _build_detail_rows_from_spo_vendor_aware(spo_df, master_df)
    output = pa.assign_processes_by_arrival_time(
        pa.compute_proc_details(details_df),
        master_df,
        previous_lane_end_times=PREV_LANE_END_TIMES,
    )
    unique = output[["山通番", "山工程", "実開始時間", "実終了時間"]].drop_duplicates("山通番")
    by_yama = {int(row["山通番"]): row for _, row in unique.iterrows()}
    hino04 = _hino_yamas(details_df, "04")
    hino03 = _hino_yamas(details_df, "03")
    assert len(hino04) == 3, "fixture の日野04便は3山であること"

    # (a) #97 継承: 日野04便3山をあふれへ残さない。
    assert not [yama for yama in hino04 if "あふれ" in str(by_yama[yama]["山工程"])]

    # (b) 全山締切内を維持する。
    work_map = _compute_work_secs_by_yama(details_df)
    deadline_map = _compute_deadline_map(details_df, master_df)
    late = []
    for yama, row in by_yama.items():
        start = pa._to_operational_timeline_secs(pa._time_to_seconds(str(row["実開始時間"])))
        if start is None or yama not in deadline_map:
            continue
        end = pa._calc_work_end_with_breaks(start, int(work_map.get(yama, 0)))
        if end > int(deadline_map[yama]):
            late.append(yama)
    assert not late, f"締切超過が発生: {late}"

    # (c) ユーザー裁定の床: 日野2レーンの同一レーン前便02 + 10分 = 18:40。
    floor = _floor_for_hino04(master_df)
    starts = {
        yama: pa._to_operational_timeline_secs(pa._time_to_seconds(str(by_yama[yama]["実開始時間"])))
        for yama in hino04
    }
    assert all(start is not None and start >= floor for start in starts.values())

    # (d) 2026-08-25 河崎裁定: 短休憩は純休憩10分＋仕分け猶予20分＝引取不可30分。
    # 当初期待値 18:46/18:53/19:01 は休憩帯 18:45-19:15 内で達成不能のため撤回し、
    # 実測ベース（19:16/19:26/19:34・全体 19:43）に余裕を持たせた上限へ改訂。
    assert min(starts.values()) <= pa._time_to_seconds("19:20")
    assert max(starts.values()) <= pa._time_to_seconds("19:40")
    assert max(pa._time_to_seconds(str(row["実終了時間"])) for _, row in by_yama.items()) <= pa._time_to_seconds("19:45")
    assert not [yama for yama in hino04 if "あふれ" in str(by_yama[yama]["山工程"])]
    work_map = _compute_work_secs_by_yama(details_df)
    deadline_map = _compute_deadline_map(details_df, master_df)
    new_late = []
    for yama, row in by_yama.items():
        start = pa._to_operational_timeline_secs(pa._time_to_seconds(str(row["実開始時間"])))
        if start is None or yama not in deadline_map:
            continue
        end = pa._calc_work_end_with_breaks(start, int(work_map.get(yama, 0)))
        if end > int(deadline_map[yama]):
            new_late.append(yama)
    assert not new_late, f"新規締切超過が発生: {new_late}"

    # (e) 日野03便の全レーン完了後、日野便番号が各レーンで非減少になること。
    hino03_ends = []
    for yama in hino03:
        row = by_yama.get(yama)
        if row is None:
            continue
        end = pa._to_operational_timeline_secs(pa._time_to_seconds(str(row["実終了時間"])))
        if end is not None:
            hino03_ends.append(end)
    assert hino03_ends, "fixture の日野03便の終了時刻が取得できない"
    for yama, start in starts.items():
        assert start is not None and start >= max(hino03_ends)

    for lane, lane_rows in output.groupby("山工程"):
        ordered = lane_rows.drop_duplicates("山通番").sort_values("実開始時間")
        bins = []
        for _, row in ordered.iterrows():
            yama = int(row["山通番"])
            values = details_df.loc[details_df["山通番"] == yama, "NONYUHIBIN"]
            if pa._normalize_dest_name(str(details_df.loc[details_df["山通番"] == yama, "納入先"].iloc[0])) == "日野":
                bins.append(int(str(values.iloc[0]).strip()[-2:]))
        assert bins == sorted(bins), f"{lane} の日野便順序が逆転: {bins}"
