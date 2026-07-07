# -*- coding: utf-8 -*-
"""CHかんばんセット — 仕分けロジックのユニットテスト"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import pandas as pd
import numpy as np

from src.services.sorter import (
    assign_groups_sequential,
    build_all_mountain_details,
    _build_size1_mixed,
    _match_units_with_layer_rules,
    run_pipeline,
)
from src.services.data_loader import load_data, DataManager, load_pickup_time_master_xlsx, get_master_path
from src.services.scheduler import cluster_by_store
from src.services.process_assigner import (
    _time_to_seconds, _seconds_to_hhmm, _adjust_start_for_breaks,
    _calc_work_end_with_breaks, _to_operational_timeline_secs,
    DAY_SECS, ARRIVAL_BUFFER_SECS,
    compute_proc_details, assign_processes_by_arrival_time,
    compute_proc_summary,
)
from src.services.exporter import build_spo_export_df, build_groupeddata_json_for_mountain
from src.models.constants import (
    PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW, BASE_ONE_TIME, BASE_PER_PAL,
    DEFAULT_HEIGHT_CAP, SPECIAL_HINBAN, SPECIAL_HEIGHT_CAP,
)
from src.utils.normalizer import _normalize_hhmm, _normalize_dest_name


class TestNormalizer:
    def test_normalize_hhmm_basic(self):
        assert _normalize_hhmm("8:30") == "08:30"
        assert _normalize_hhmm("12:05") == "12:05"
        assert _normalize_hhmm("") == ""
        assert _normalize_hhmm(None) == ""

    def test_normalize_hhmm_fullwidth(self):
        assert _normalize_hhmm("０８：３０") == "08:30"

    def test_normalize_dest_name_alias(self):
        assert _normalize_dest_name("九州") == "KVC"
        assert _normalize_dest_name("TMK") == "KVC"
        assert _normalize_dest_name("日野E/H") == "日野EH"
        assert _normalize_dest_name("武部") == "武部"


class TestGrouping:
    def test_sequential_basic(self):
        heights = pd.Series([100, 200, 300, 2400, 50])
        result = assign_groups_sequential(heights, cap=2450)
        assert result == [1, 1, 1, 2, 2]

    def test_sequential_exact_fit(self):
        heights = pd.Series([2450])
        result = assign_groups_sequential(heights, cap=2450)
        assert result == [1]

    def test_sequential_overflow(self):
        heights = pd.Series([2000, 500, 2000])
        result = assign_groups_sequential(heights, cap=2450)
        assert result == [1, 2, 3]

    def test_sequential_special_hinban_uses_lower_cap_and_logs(self, caplog):
        heights = pd.Series([1300, 900])
        hinbans = pd.Series([SPECIAL_HINBAN, "999999999999"])
        with caplog.at_level("DEBUG"):
            result = assign_groups_sequential(heights, cap=DEFAULT_HEIGHT_CAP, hinbans=hinbans)
        assert result == [1, 2]
        assert any(
            SPECIAL_HINBAN in record.message and str(SPECIAL_HEIGHT_CAP) in record.message
            for record in caplog.records
        )

    def test_size1_same_bin_only_is_single_mountain(self):
        """同じNONYUHIBINのみの場合は通常積みで1山になる。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1300, "移動工数": 10, "UKEIRE": "A", "納入先": "日野"},
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1100, "移動工数": 9, "UKEIRE": "B", "納入先": "KVC"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")
        assert details["山通番"].nunique() == 1

    def test_size1_forbid_same_dest_diff_bin(self):
        """納入先が同じで NONYUHIBINが異なる場合は混載禁止。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1000, "移動工数": 10, "UKEIRE": "A", "納入先": "日野"},
            {"サイズ種類": "1", "NONYUHIBIN": "02", "高さ": 1000, "移動工数": 9, "UKEIRE": "B", "納入先": "日野"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")
        # 同じ納入先でNONYUHIBINが異なるので2つの山に分かれる
        assert details["山通番"].nunique() == 2

    def test_size1_allow_diff_bin_when_dest_differs(self):
        """納入先が異なれば NONYUHIBIN が異なっても混載を許容する。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1000, "移動工数": 10, "UKEIRE": "A", "納入先": "高岡"},
            {"サイズ種類": "1", "NONYUHIBIN": "02", "高さ": 1000, "移動工数": 9, "UKEIRE": "B", "納入先": "KVC"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")
        assert details["山通番"].nunique() == 1

    def test_size1_rescue_split_urgent_vendor_when_deadline_floor_conflict(self):
        """混載山で締切/開始下限が衝突する場合、締切が厳しい納入先を単独山へ分離する。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1000, "移動工数": 10, "UKEIRE": "A", "納入先": "高岡", "入車時間": "07:31"},
            {"サイズ種類": "1", "NONYUHIBIN": "02", "高さ": 1000, "移動工数": 9, "UKEIRE": "B", "納入先": "KVC", "入車時間": "10:56"},
            # KVC02 の開始下限を作る前便
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 200, "移動工数": 3, "UKEIRE": "C", "納入先": "KVC", "入車時間": "08:26"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")
        urgent = details[details["納入先"].astype(str) == "高岡"]
        kvc02 = details[(details["納入先"].astype(str) == "KVC") & (details["NONYUHIBIN"].astype(str).str.endswith("02"))]
        assert not urgent.empty and not kvc02.empty
        assert int(urgent["山通番"].iloc[0]) != int(kvc02["山通番"].iloc[0])

    def test_size1_rescue_split_applies_to_non_takaoka_vendor(self):
        """高岡以外でも、締切が厳しい納入先は同様に単独山へ分離する。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 1000, "移動工数": 10, "UKEIRE": "A", "納入先": "KVC", "入車時間": "07:31"},
            {"サイズ種類": "1", "NONYUHIBIN": "02", "高さ": 1000, "移動工数": 9, "UKEIRE": "B", "納入先": "日野EH", "入車時間": "10:56"},
            # 日野EH02 の開始下限を作る前便
            {"サイズ種類": "1", "NONYUHIBIN": "01", "高さ": 200, "移動工数": 3, "UKEIRE": "C", "納入先": "日野EH", "入車時間": "08:26"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")
        kvc = details[details["納入先"].astype(str) == "KVC"]
        hino02 = details[(details["納入先"].astype(str) == "日野EH") & (details["NONYUHIBIN"].astype(str).str.endswith("02"))]
        assert not kvc.empty and not hino02.empty
        assert int(kvc["山通番"].iloc[0]) != int(hino02["山通番"].iloc[0])

    def test_takaoka_size17_adjacent_mountains_are_merged(self):
        """高岡(K5)サイズ17で同一便・同一入車時間の隣接山は統合される。"""
        det17 = pd.DataFrame([
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-5", "SEBANGO": "716", "サイズ種類": "17", "移動工数": 16.6501, "高さ": 830},
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
            {"グループ番号": 2, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
        ])

        out = build_all_mountain_details({"17": det17}, pd.DataFrame())
        assert out["山通番"].nunique() == 1
        assert len(out) == 3
        summary = out.groupby("山通番").agg(
            パレット数=("山通番", "size"),
            Max移動工数=("移動工数", "max"),
        ).reset_index()
        assert int(summary.loc[0, "パレット数"]) == 3
        assert float(summary.loc[0, "Max移動工数"]) == pytest.approx(16.6501, abs=1e-4)

    def test_non_takaoka_size17_adjacent_mountains_are_merged(self):
        """サイズ17統合は全出荷先対象のため、高岡以外でも同条件なら統合される。"""
        det17 = pd.DataFrame([
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-5", "SEBANGO": "716", "サイズ種類": "17", "移動工数": 16.6501, "高さ": 830},
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
            {"グループ番号": 2, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
        ])

        out = build_all_mountain_details({"17": det17}, pd.DataFrame())
        assert out["山通番"].nunique() == 1
        assert len(out) == 3

    def test_non_size17_mountains_remain_split_regression(self):
        """サイズ17以外は統合後処理の対象外で、従来どおり分割を維持する。"""
        det18 = pd.DataFrame([
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-5", "SEBANGO": "716", "サイズ種類": "18", "移動工数": 16.6501, "高さ": 830},
            {"グループ番号": 1, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "18", "移動工数": 16.6500, "高さ": 830},
            {"グループ番号": 2, "入車時間": "13:01", "NONYUHIBIN": "2026062503", "納入先": "KVC", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "18", "移動工数": 16.6500, "高さ": 830},
        ])

        out = build_all_mountain_details({"18": det18}, pd.DataFrame())
        assert out["山通番"].nunique() == 2

    def test_size17_mountains_with_different_arrival_are_not_merged(self):
        """サイズ17でも入車時間が異なる山は統合しない。"""
        det17 = pd.DataFrame([
            {"グループ番号": 1, "入車時間": "07:55", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-5", "SEBANGO": "716", "サイズ種類": "17", "移動工数": 16.6501, "高さ": 830},
            {"グループ番号": 1, "入車時間": "07:55", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
            {"グループ番号": 2, "入車時間": "08:03", "NONYUHIBIN": "2026062503", "納入先": "高岡", "UKEIRE": "K5", "ストア": "Q9-A-1", "SEBANGO": "715", "サイズ種類": "17", "移動工数": 16.6500, "高さ": 830},
        ])

        out = build_all_mountain_details({"17": det17}, pd.DataFrame())
        assert out["山通番"].nunique() == 2

    def test_regression_order_yama_continuity_real_20260706_091011(self):
        """回帰: 09/10/11 実データで各オーダー内の山通番が連続範囲であること。"""
        df_ship, df_places = load_data()
        master = load_pickup_time_master_xlsx(get_master_path())
        dm = DataManager(df_ship, df_places)

        orders = ["2026070609", "2026070610", "2026070611"]
        selections = []
        for route in dm.get_routes():
            for receipt in dm.get_receipts_for_route(route):
                cand = set(dm.get_orders_for_route_receipt(route, receipt))
                for order in orders:
                    if order in cand:
                        selections.append({"便名": route, "受入": receipt, "オーダー": order})

        _filtered, _expanded, group_results, group_details, _s1_summary, s1_details, _lane_end = run_pipeline(
            dm,
            selections,
            2450,
            "UKEIRE",
            master_df=master,
            return_lane_end_times=True,
        )

        all_det = build_all_mountain_details(group_details, s1_details)
        assert not all_det.empty

        nony = all_det["NONYUHIBIN"].astype(str).str.strip()
        for tail in ["09", "10", "11"]:
            sub = all_det[nony.str[-2:] == tail]
            yamas = sorted(pd.to_numeric(sub["山通番"], errors="coerce").dropna().astype(int).unique().tolist())
            assert yamas, f"tail={tail}: 山通番が存在しません"
            contiguous = (max(yamas) - min(yamas) + 1) == len(yamas)
            assert contiguous, f"tail={tail}: 山通番が不連続 yamas={yamas}"


class TestProcessAssigner:
    def test_time_conversion(self):
        assert _time_to_seconds("08:30") == 8 * 3600 + 30 * 60
        assert _time_to_seconds("") is None
        assert _seconds_to_hhmm(8 * 3600 + 30 * 60) == "08:30"

    def test_adjust_start_for_breaks(self):
        # 8:35は休憩中(8:30-8:40)なので8:41に調整
        start = 8 * 3600 + 35 * 60
        adjusted = _adjust_start_for_breaks(start)
        assert adjusted == 8 * 3600 + 41 * 60  # 8:41

    def test_lunch_break_limits_last_mountain_end_to_10min_before(self):
        """10:40/20:55の長休憩は、休憩10分前を超える作業を休憩後へ送る。"""
        # 10:20開始 + 15分作業 = 10:35（10:30制限を超過）→ 11:40開始へ繰り下げ
        start_1 = 10 * 3600 + 20 * 60
        adjusted_1 = _adjust_start_for_breaks(start_1, 15 * 60)
        assert adjusted_1 == 11 * 3600 + 40 * 60

        # 20:40開始 + 10分作業 = 20:50（20:45制限を超過）→ 21:55開始へ繰り下げ
        start_2 = 20 * 3600 + 40 * 60
        adjusted_2 = _adjust_start_for_breaks(start_2, 10 * 60)
        assert adjusted_2 == 21 * 3600 + 55 * 60

    def test_lunch_break_first_mountain_starts_15min_after_break(self):
        """長休憩中に入る開始時刻は、休憩終了15分後へ調整する。"""
        # 11:30は10:40-11:25休憩の直後帯 → 11:40
        adjusted_1 = _adjust_start_for_breaks(11 * 3600 + 30 * 60)
        assert adjusted_1 == 11 * 3600 + 40 * 60

        # 21:45は20:55-21:40休憩の直後帯 → 21:55
        adjusted_2 = _adjust_start_for_breaks(21 * 3600 + 45 * 60)
        assert adjusted_2 == 21 * 3600 + 55 * 60

    def test_assign_all_main_no_master(self):
        """マスタなしの場合は全てメイン工程"""
        df = pd.DataFrame({
            "山通番": [1, 1, 2, 2],
            "移動工数": [100, 200, 150, 180],
            "納入先": ["A", "B", "C", "D"],
        })
        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, pd.DataFrame())
        assert len(result) == 2
        assert all(result["山工程"] == PROC_MAIN)

    def test_assign_with_tight_deadline(self):
        """締め切りに間に合わない山はリリーフに回る"""
        df = pd.DataFrame({
            "山通番": [1, 1, 2, 2],
            "移動工数": [100, 100, 100, 100],
            "納入先": ["武部", "武部", "武部", "武部"],
            "NONYUHIBIN": ["01", "01", "02", "02"],
            "高さ": [500, 500, 500, 500],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["武部", "武部"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["08:35", "08:36"],  # 非常にタイトな締め切り
        })
        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)
        # 非常にタイトな締め切り → リリーフまたはあふれに回るはず
        non_main = result[result["山工程"] != PROC_MAIN]
        assert not non_main.empty, "少なくとも1つはメイン以外（リリーフ/あふれ）に回るはず"

    def test_takebe_first_group_has_no_start_floor_constraint(self):
        """武部で前グループが無い初便は開始制約なし（0秒）として扱う。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["武部"],
            "NONYUHIBIN": ["01"],
            "高さ": [400],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["武部"],
            "NONYUHIBIN": ["01"],
            "入車時間": ["08:30"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        row = result.iloc[0]
        assert row["山工程"] == PROC_MAIN
        start_secs = _time_to_seconds(str(row["実開始時間"]))
        assert start_secs is not None
        # 不具合時は開始下限が08:40に固定され、締切08:20に間に合わずメイン不可となっていた。
        assert start_secs < _time_to_seconds("08:20")

    def test_relief_start_respects_prev_bin_floor(self):
        """リリーフ1山目の開始時刻が「前便入車+10分」の下限を下回らない（仕分けロジック遵守）。

        シナリオ:
                    山1 (A-01, 締切12:00) → MAIN で余裕あり
                    山2 (A-02, 前便01が12:00着 → 開始下限12:10, 締切12:04) → MAINでは間に合わないためRELIEF
          RELIEFの最遅開始 = 12:04 - work_secs ≈ 12:00 < 開始下限12:10
          修正前: relief開始 = 12:00 (下限違反)
          修正後: relief開始 >= 12:10 (下限尊重)
        """
        # 各山1パレット、移動工数0 → pick_cost = round(187.64 + 52, 0) = 240 secs
        df = pd.DataFrame({
            "山通番": [1, 2],
            "移動工数": [0.0, 0.0],
            "納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            "高さ": [300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            # 01が12:00着 → 山2の開始下限12:10
            # 山2の締切12:04は 開始下限12:10 より早い → 最遅開始(=12:00)が下限(12:10)を下回る
            "入車時間": ["12:00", "12:04"],
        })
        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        # 山2は締切(11:54) < 開始下限(12:10) → どの工程でも間に合わない → あふれ
        overflow_rows = result[result["山工程"] == PROC_OVERFLOW]
        assert not overflow_rows.empty, "山2はあふれに割り当てられるはず"

        overflow_row = overflow_rows[overflow_rows["山通番"] == 2].iloc[0]
        overflow_start_secs = _time_to_seconds(str(overflow_row["実開始時間"]))
        prev_bin_arrival_secs = _time_to_seconds("12:00")
        start_floor_secs = prev_bin_arrival_secs + 10 * 60  # 12:10

        assert overflow_start_secs >= start_floor_secs, (
            f"あふれ開始時刻 {overflow_row['実開始時間']} が"
            f" 開始下限 12:10 を下回っている（前便入車+10分ルール違反）"
        )

    def test_proc_summary(self):
        df = pd.DataFrame({"山通番": [1, 2], "移動工数": [100, 200], "納入先": ["A", "B"]})
        proc_det = compute_proc_details(df)
        proc_map = {1: PROC_MAIN, 2: PROC_RELIEF}
        summary = compute_proc_summary(proc_det, proc_map)
        assert len(summary) == 2
        assert summary.loc[summary["山通番"] == 1, "メイン工程"].values[0] == 1
        assert summary.loc[summary["山通番"] == 2, "リリーフ工程"].values[0] == 1

    def test_dynamic_prefetch_keeps_primary_deadline(self):
        """主対象の締切を守れる場合のみ、別第の山を前倒しできる。

        シナリオ:
          山通番1 (A-01, 締分1 09:20) ... 最早締切 = primary
          山通番2 (B-01, 締分2 10:00) ... start_floor=0（初便）→前倒し可能
          山通番3 (A-02, 締分3 14:00) ... start_floor=09:30→mountain1時刻超過のため前倒し不可
        期待: mountain2が前倒し(True)、全山MAIN。
        """
        df = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "A"],
            "NONYUHIBIN": ["01", "01", "02"],
            "高さ": [300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A", "B"],
            "NONYUHIBIN": ["01", "02", "01"],
            "入車時間": ["09:20", "14:00", "10:00"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        assert set(result["山工程"].tolist()) == {PROC_MAIN}
        assert "前倒し" in result.columns

        row1 = result.loc[result["山通番"] == 1].iloc[0]  # A-01: primary
        row2 = result.loc[result["山通番"] == 2].iloc[0]  # B-01: 前倒し
        assert bool(row1["前倒し"]) is False  # primaryは前倒しされない
        assert bool(row2["前倒し"]) is True   # B-01は前倒しされる

    def test_assign_marks_every_third_start_with_180sec_delay(self):
        df = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "高さ": [300, 300, 300],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, pd.DataFrame())

        assert "照合追加180秒" in result.columns
        flagged = result.loc[result["照合追加180秒"], "山通番"].tolist()
        assert flagged == [3]

    def test_assign_cascades_180sec_delay_without_overlap(self):
        df = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "高さ": [300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "入車時間": ["12:00", "12:10", "12:20"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        ordered = result.copy()
        ordered["_start_sec"] = ordered["実開始時間"].astype(str).map(_time_to_seconds)
        ordered = ordered.sort_values(["山工程", "_start_sec", "山通番"]).reset_index(drop=True)
        assert ordered["_start_sec"].notna().all()

        work_sec = int(np.round(120 + 0 + 60, 0))
        for _, proc_rows in ordered.groupby("山工程"):
            proc_rows = proc_rows.sort_values(["_start_sec", "山通番"]).reset_index(drop=True)
            for i in range(len(proc_rows) - 1):
                cur_start = int(proc_rows.loc[i, "_start_sec"])
                next_start = int(proc_rows.loc[i + 1, "_start_sec"])
                end_cur = _calc_work_end_with_breaks(cur_start, work_sec)
                # 次山が3番目/5番目/...（index=2,4,...）なら照合180秒が入る
                delay_before_next = 180 if ((i + 1) >= 2 and (i + 1) % 2 == 0) else 0
                assert next_start >= end_cur + delay_before_next

    def test_assign_prevents_late_main_mountains_after_finalization(self):
        """最終時刻確定後、メイン工程に締切超過を残さない。"""
        df = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "高さ": [300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "入車時間": ["11:12", "11:12", "11:12"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        deadline_secs = _time_to_seconds("11:12")
        work_sec = int(np.round(0 + BASE_ONE_TIME + BASE_PER_PAL, 0))
        main_rows = result[result["山工程"] == PROC_MAIN]
        for _, row in main_rows.iterrows():
            start_secs = _time_to_seconds(str(row["実開始時間"]))
            assert start_secs is not None
            end_secs = _calc_work_end_with_breaks(int(start_secs), work_sec)
            assert end_secs <= int(deadline_secs)

    def test_assign_main_deadline_rule_is_enforced_in_mixed_lanes(self):
        """MAINと非MAINが混在する出力でも、MAINは入車10分前締切を必ず守る。"""
        df = pd.DataFrame({
            "山通番": [1, 2, 3, 4],
            "移動工数": [120, 60, 30, 30],
            "納入先": ["D", "D", "A", "C"],
            "NONYUHIBIN": ["03", "02", "02", "02"],
            "高さ": [400, 400, 400, 400],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["D", "D", "A", "C"],
            "NONYUHIBIN": ["03", "02", "02", "02"],
            "入車時間": ["09:00", "11:40", "09:20", "08:50"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        main_rows = result[result["山工程"] == PROC_MAIN]
        non_main_rows = result[result["山工程"] != PROC_MAIN]
        assert not main_rows.empty
        assert not non_main_rows.empty

        arrival_map = {
            1: _time_to_seconds("09:00"),
            2: _time_to_seconds("11:40"),
            3: _time_to_seconds("09:20"),
            4: _time_to_seconds("08:50"),
        }
        work_map = {
            1: int(np.round(120 + BASE_ONE_TIME + BASE_PER_PAL, 0)),
            2: int(np.round(60 + BASE_ONE_TIME + BASE_PER_PAL, 0)),
            3: int(np.round(30 + BASE_ONE_TIME + BASE_PER_PAL, 0)),
            4: int(np.round(30 + BASE_ONE_TIME + BASE_PER_PAL, 0)),
        }
        for _, row in main_rows.iterrows():
            yama = int(row["山通番"])
            start_secs = _time_to_seconds(str(row["実開始時間"]))
            assert start_secs is not None
            end_secs = _calc_work_end_with_breaks(int(start_secs), int(work_map[yama]))
            deadline_secs = int(arrival_map[yama]) - 10 * 60
            assert end_secs <= deadline_secs

    def test_assign_keeps_all_main_when_deadline_reorder_is_feasible(self):
        """締切優先の再並び替えで間に合う場合はリリーフへ落とさない。"""
        # work=move+240 になるように移動工数を設定
        df = pd.DataFrame({
            "山通番": [1, 2, 3, 4],
            "移動工数": [223, 313, 16, 183],
            "納入先": ["A", "B", "B", "C"],
            "NONYUHIBIN": ["2026052701", "2026052801", "2026052801", "2026052701"],
            "高さ": [300, 300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "C", "B"],
            "NONYUHIBIN": ["01", "01", "01"],
            "入車時間": ["07:10", "07:31", "08:16"],
        })

        proc_det = compute_proc_details(df)
        result = assign_processes_by_arrival_time(proc_det, master_df)

        assert set(result["山工程"].tolist()) == {PROC_MAIN}

        deadline_map = {
            1: _time_to_seconds("07:00"),
            2: _time_to_seconds("08:06"),
            3: _time_to_seconds("08:06"),
            4: _time_to_seconds("07:21"),
        }
        work_map = {
            1: 463,
            2: 553,
            3: 256,
            4: 423,
        }
        for _, row in result.iterrows():
            yama = int(row["山通番"])
            start_secs = _time_to_seconds(str(row["実開始時間"]))
            assert start_secs is not None
            end_secs = _calc_work_end_with_breaks(int(start_secs), int(work_map[yama]))
            assert end_secs <= int(deadline_map[yama])

    def test_start_floor_shift_first_trip_without_set_flag_uses_shift_start_plus_15(self):
        """セットなしの各直1便目は「各直開始+15分」を開始下限にする。"""
        df = pd.DataFrame({
            "山通番": [1, 2],
            "移動工数": [0, 0],
            "納入先": ["A", "A"],
            "NONYUHIBIN": ["2026052801", "2026052802"],
            "高さ": [300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["08:40", "09:00"],
            "セットありフラグ": ["0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)

        start_1 = result.loc[result["山通番"] == 1, "実開始時間"].iloc[0]
        start_2 = result.loc[result["山通番"] == 2, "実開始時間"].iloc[0]
        assert start_1 == "06:40"
        assert start_2 >= "08:50"

    def test_start_floor_shift_first_trip_with_set_flag_keeps_legacy_rule(self):
        """セットあり便は各直1便目でも従来ルール（前便+10分）を優先する。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["A"],
            "NONYUHIBIN": ["2026052801"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A"],
            "NONYUHIBIN": ["01"],
            "入車時間": ["08:40"],
            "セットありフラグ": ["1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        start_1 = result.loc[result["山通番"] == 1, "実開始時間"].iloc[0]
        # 従来ルールでは初便の開始制約なし（0）なので、06:40固定にはならない
        assert start_1 != "06:40"

    def test_hino_01_without_set_flag_uses_shift_start_plus_15(self):
        """日野でもセットなし各直1便目は「各直開始+15分」を開始下限にする。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["日野"],
            "NONYUHIBIN": ["2026052701"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["日野", "日野"],
            "NONYUHIBIN": ["01", "11"],
            "入車時間": ["06:50", "06:00"],
            "セットありフラグ": ["0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        start_1 = result.loc[result["山通番"] == 1, "実開始時間"].iloc[0]
        # 1直始業06:25 + 15分 = 06:40
        assert start_1 == "06:40"

    def test_overnight_hino_01_is_not_misclassified_as_shift_first_trip(self):
        """日付またぎ(23:xx→00:xx)で日野01を誤って各直1便目扱いしない。"""
        df = pd.DataFrame({
            "山通番": [1, 2],
            "移動工数": [0, 0],
            "納入先": ["日野", "日野"],
            "NONYUHIBIN": ["2026052711", "2026052801"],
            "高さ": [300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["日野", "日野"],
            "NONYUHIBIN": ["11", "01"],
            "入車時間": ["23:40", "00:20"],
            "セットありフラグ": ["0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        row_01 = result.loc[result["山通番"] == 2].iloc[0]

        # 修正前は 00:20 を1直扱いしてしまい、日野01が06:40固定でリリーフ化していた。
        assert row_01["山工程"] == PROC_MAIN
        assert str(row_01["実開始時間"]) != "06:40"

    def test_set_flag_shift1_uses_main_limit_1520_to_reduce_relief(self):
        """セットあり便(1直)は15:20までメイン工程を許容する。"""
        df = pd.DataFrame({
            "山通番": [1],
            # 作業時間を適度に長くし、厳密締切(07:00-10分)では不可だが
            # セットあり上限15:20ならメインで成立するケース
            "移動工数": [7000],
            "納入先": ["A"],
            "NONYUHIBIN": ["2026052802"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["06:40", "07:00"],
            "セットありフラグ": ["0", "1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        assert result.loc[result["山通番"] == 1, "山工程"].iloc[0] == PROC_MAIN

    def test_set_flag_shift2_uses_main_limit_0135_to_reduce_relief(self):
        """セットあり便(2直)は01:35までメイン工程を許容する。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [7000],
            "納入先": ["A"],
            "NONYUHIBIN": ["2026052811"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["10", "11"],
            "入車時間": ["17:10", "17:30"],
            "セットありフラグ": ["0", "1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        assert result.loc[result["山通番"] == 1, "山工程"].iloc[0] == PROC_MAIN

    def test_set_flag_overnight_hino01_uses_24h_continuous_floor(self):
        """日付またぎ日野01(セットあり)は24h連続表記の開始下限を使い、メインで成立する。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["日野"],
            "NONYUHIBIN": ["2026052801"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["日野", "日野"],
            "NONYUHIBIN": ["11", "01"],
            "入車時間": ["24:20", "06:50"],
            "セットありフラグ": ["0", "1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN

    def test_deadline_normalization_is_noop_for_same_day_start(self):
        """開始が当日基準の通常便では締切正規化が据え置きになる。"""
        pickup_secs = _to_operational_timeline_secs(_time_to_seconds("07:00"))
        raw_deadline = int(pickup_secs) - ARRIVAL_BUFFER_SECS
        start_secs = _time_to_seconds("06:50")
        eval_deadline = raw_deadline + DAY_SECS if (int(start_secs) >= DAY_SECS and raw_deadline < DAY_SECS) else raw_deadline

        assert eval_deadline == raw_deadline
        assert _seconds_to_hhmm(raw_deadline) == "06:50"

        # 代表通常便（非巻き戻り）でも工程・開始は従来どおり
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["日野"],
            "NONYUHIBIN": ["2026060101"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["日野", "日野", "日野", "日野", "日野", "日野", "日野", "日野"],
            "NONYUHIBIN": ["01", "03", "05", "07", "09", "11", "13", "15"],
            "入車時間": ["06:50", "07:20", "07:50", "13:52", "17:30", "18:00", "22:00", "00:24"],
            "セットありフラグ": ["0", "0", "0", "0", "0", "0", "0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_OVERFLOW
        assert str(row["実開始時間"]) == "06:40"

    def test_deadline_normalization_does_not_double_add_when_both_next_day_axis(self):
        """開始・締切とも翌日基準のとき締切を二重加算しない。"""
        deadline = _to_operational_timeline_secs(_time_to_seconds("24:20")) - ARRIVAL_BUFFER_SECS  # 24:10
        start = _to_operational_timeline_secs(_time_to_seconds("24:24")) + ARRIVAL_BUFFER_SECS      # 24:34
        eval_deadline = deadline + DAY_SECS if (int(start) >= DAY_SECS and int(deadline) < DAY_SECS) else int(deadline)

        assert int(start) >= DAY_SECS
        assert int(deadline) >= DAY_SECS
        assert eval_deadline == int(deadline)
        assert _seconds_to_hhmm(eval_deadline) == "24:10"

        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [0],
            "納入先": ["日野"],
            "NONYUHIBIN": ["2026052801"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["日野", "日野"],
            "NONYUHIBIN": ["11", "01"],
            "入車時間": ["24:20", "06:50"],
            "セットありフラグ": ["0", "1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        row = result.loc[result["山通番"] == 1].iloc[0]
        assert row["山工程"] == PROC_MAIN
        assert str(row["実開始時間"]) == "24:30"

    def test_set_flag_shift2_first_trip_uses_shift2_limit_not_shift1(self):
        """2直1便目(セットあり)は前便が1直でも2直上限(01:35)を使う。"""
        df = pd.DataFrame({
            "山通番": [1],
            "移動工数": [8000],
            "納入先": ["A"],
            "NONYUHIBIN": ["2026052810"],
            "高さ": [300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["09", "10"],
            "入車時間": ["15:00", "17:30"],
            "セットありフラグ": ["0", "1"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        # 2直セットあり上限01:35で間に合うためメインに残るべき
        assert result.loc[result["山通番"] == 1, "山工程"].iloc[0] == PROC_MAIN

    def test_relief_rows_can_be_promoted_back_to_main_when_feasible(self):
        """初期判定でリリーフになっても、再評価でメインに戻せる山は昇格する。"""
        df = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["KVC", "A", "A"],
            "NONYUHIBIN": ["2026052701", "2026052701", "2026052702"],
            "高さ": [300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["KVC", "A", "A"],
            "NONYUHIBIN": ["01", "01", "02"],
            "入車時間": ["08:20", "08:40", "09:30"],
            "セットありフラグ": ["0", "0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        # KVCを含む山は優先締切でメインに残ること
        kvc_row = result.loc[result["山通番"] == 1].iloc[0]
        assert kvc_row["山工程"] == PROC_MAIN

    def test_relief_first_row_starts_earliest_when_multiple_relief_rows_exist(self):
        """リリーフ複数山時は1山目を遅らせ過ぎず最早開始にする。"""
        df = pd.DataFrame({
            "山通番": [1, 2, 3, 4],
            "移動工数": [0, 0, 0, 0],
            "納入先": ["A", "A", "A", "A"],
            "NONYUHIBIN": ["2026052702", "2026052702", "2026052702", "2026052702"],
            "高さ": [300, 300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["09:26", "09:52"],
            "セットありフラグ": ["0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        # リリーフ＋あふれの合計が2以上
        non_main = result[result["山工程"].isin([PROC_RELIEF, PROC_OVERFLOW])].sort_values("山通番")
        assert len(non_main) >= 2
        # リリーフがあれば前便(01=09:26)由来の開始下限 09:36 以上で開始する
        relief = result[result["山工程"] == PROC_RELIEF].sort_values("山通番")
        if not relief.empty:
            start_secs = _time_to_seconds(str(relief.iloc[0]["実開始時間"]))
            floor_secs = _time_to_seconds("09:36")
            assert start_secs >= floor_secs, (
                f"リリーフ開始 {relief.iloc[0]['実開始時間']} が開始下限 09:36 を下回っている"
            )

    def test_same_bin_cluster_is_scheduled_contiguously_for_hino_02(self):
        """山10/山11(日野・order2=02)の間に山7(KVC)が割り込まないこと。"""
        df = pd.DataFrame({
            "山通番": [7, 10, 11],
            "移動工数": [0, 0, 0],
            "納入先": ["KVC", "日野", "日野"],
            "NONYUHIBIN": ["2026060501", "2026060502", "2026060502"],
            "高さ": [300, 300, 300],
        })
        master_df = pd.DataFrame({
            "OData_納入先": ["KVC", "日野", "日野"],
            "NONYUHIBIN": ["01", "01", "02"],
            "入車時間": ["07:40", "06:55", "08:00"],
            "セットありフラグ": ["0", "0", "0"],
        })

        result = assign_processes_by_arrival_time(compute_proc_details(df), master_df)
        main_rows = result[result["山工程"] == PROC_MAIN].copy()
        main_rows["_start"] = main_rows["実開始時間"].astype(str).map(_time_to_seconds)
        main_rows = main_rows.sort_values(["_start", "山通番"]).reset_index(drop=True)

        ordered = main_rows["山通番"].astype(int).tolist()
        assert 10 in ordered and 11 in ordered
        idx10 = ordered.index(10)
        idx11 = ordered.index(11)
        lo, hi = min(idx10, idx11), max(idx10, idx11)
        between = ordered[lo + 1:hi]
        assert 7 not in between, f"山10/11の間に山7が割り込んでいます: order={ordered}"


class TestExporter:
    def test_spo_pick_cost_links_to_next_start_with_inspection_delay(self):
        proc_details = pd.DataFrame({
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "UKEIRE": ["100", "200", "300"],
            "ストア": ["S1", "S2", "S3"],
        })
        mountain_proc_map = {1: PROC_MAIN, 2: PROC_MAIN, 3: PROC_MAIN}
        start_times = {1: "08:00", 2: "08:05", 3: "08:10"}
        # 2山集荷後の照合180秒は3山目開始前
        inspection_delay_map = {1: False, 2: False, 3: True}

        spo_df = build_spo_export_df(
            proc_details,
            mountain_proc_map,
            start_times,
            inspection_delay_map=inspection_delay_map,
        )

        row1 = spo_df.loc[spo_df["グループ番号"] == 1].iloc[0]
        row2 = spo_df.loc[spo_df["グループ番号"] == 2].iloc[0]
        row3 = spo_df.loc[spo_df["グループ番号"] == 3].iloc[0]
        base_pick = int(np.round(BASE_ONE_TIME + BASE_PER_PAL, 0))
        assert int(row1["引取工数"]) == base_pick
        assert int(row2["引取工数"]) == base_pick + 180
        assert int(row3["引取工数"]) == base_pick


class TestClusterByStore:
    """cluster_by_store: 同梱パレットのストア単位クラスター化テスト"""

    # ------------------------------------------------------------------ #
    # テスト1: 異なる2HINBANが同一STOREに存在 → 1行に束ねる（I12-B-3ケース）
    # ------------------------------------------------------------------ #
    def test_different_hinbans_same_store_are_merged_into_one_row(self):
        """I12-B-3 の異種2HINBANが1山に束ねられること。"""
        rows = [
            {"ストア": "I12-B-3", "HINBAN": "616425003000", "移動工数": 50},
            {"ストア": "I12-B-3", "HINBAN": "616465005000", "移動工数": 60},
        ]
        result = cluster_by_store(rows)
        store_rows = [r for r in result if r.get("ストア") == "I12-B-3"]
        assert len(store_rows) == 1, (
            f"I12-B-3の異種2HINBANは1行に束ねられるべきです。実際: {len(store_rows)}行"
        )

    # ------------------------------------------------------------------ #
    # テスト2: 同一HINBANが複数行 → 束ねない（N12-A-19ケース）
    # ------------------------------------------------------------------ #
    def test_same_hinban_multiple_rows_stay_separate(self):
        """N12-A-19 の同一HINBAN×2行が2山のまま維持されること。"""
        rows = [
            {"ストア": "N12-A-19", "HINBAN": "616425003000", "移動工数": 50},
            {"ストア": "N12-A-19", "HINBAN": "616425003000", "移動工数": 50},
        ]
        result = cluster_by_store(rows)
        store_rows = [r for r in result if r.get("ストア") == "N12-A-19"]
        assert len(store_rows) == 2, (
            f"N12-A-19の同一HINBAN×2行は2行のまま維持されるべきです。実際: {len(store_rows)}行"
        )

    # ------------------------------------------------------------------ #
    # テスト3: 束ねた山の移動工数が1回分のみであること
    # ------------------------------------------------------------------ #
    def test_merged_row_keeps_first_row_move_cost(self):
        """束ねた山の移動工数が先頭行の値（1回分）のみであること。"""
        move_first = 50
        rows = [
            {"ストア": "I12-B-3", "HINBAN": "616425003000", "移動工数": move_first},
            {"ストア": "I12-B-3", "HINBAN": "616465005000", "移動工数": 80},
        ]
        result = cluster_by_store(rows)
        store_rows = [r for r in result if r.get("ストア") == "I12-B-3"]
        assert len(store_rows) == 1
        assert store_rows[0]["移動工数"] == move_first, (
            f"束ね後の移動工数は先頭行の {move_first} であるべきです。"
            f"実際: {store_rows[0]['移動工数']}"
        )

    # ------------------------------------------------------------------ #
    # テスト4: _merged_hinban に同梱HINBANが正しく保持されること
    # ------------------------------------------------------------------ #
    def test_merged_hinban_list_is_populated_correctly(self):
        """_merged_hinban に同梱した全HINBANが正しく保持されること。"""
        hinban_a = "616425003000"
        hinban_b = "616465005000"
        rows = [
            {"ストア": "I12-B-3", "HINBAN": hinban_a, "移動工数": 50},
            {"ストア": "I12-B-3", "HINBAN": hinban_b, "移動工数": 60},
        ]
        result = cluster_by_store(rows)
        store_rows = [r for r in result if r.get("ストア") == "I12-B-3"]
        assert len(store_rows) == 1
        merged = store_rows[0]
        assert "_merged_hinban" in merged, "_merged_hinban キーが存在しません"
        assert isinstance(merged["_merged_hinban"], list), "_merged_hinban はlistであるべきです"
        assert set(merged["_merged_hinban"]) == {hinban_a, hinban_b}, (
            f"_merged_hinban の内容が不正です: {merged['_merged_hinban']}"
        )

    def test_merged_rows_keep_full_detail_records(self):
        """_merged_rows に同梱した元行明細（SEBANGO含む）が保持されること。"""
        rows = [
            {"ストア": "I12-B-3", "HINBAN": "616425003000", "SEBANGO": "740", "移動工数": 50},
            {"ストア": "I12-B-3", "HINBAN": "616465005000", "SEBANGO": "742", "移動工数": 60},
        ]
        result = cluster_by_store(rows)
        assert len(result) == 1
        merged = result[0]
        assert "_merged_rows" in merged
        assert isinstance(merged["_merged_rows"], list)
        assert len(merged["_merged_rows"]) == 2
        assert {str(r.get("SEBANGO")) for r in merged["_merged_rows"]} == {"740", "742"}

    def test_groupeddata_keeps_representative_row_without_expanding_merged_rows(self):
        """xlsx用groupdata生成では_merged_rowsを展開せず代表行のみ採用すること。"""
        sub_rows = pd.DataFrame([
            {
                "山通番": 1,
                "ストア": "I12-B-3",
                "NONYUHIBIN": "03",
                "UKEIRE": "A",
                "納入先": "日野",
                "SEBANGO": "740",
                "_merged_rows": [
                    {"ストア": "I12-B-3", "NONYUHIBIN": "03", "UKEIRE": "A", "納入先": "日野", "SEBANGO": "740"},
                    {"ストア": "I12-B-3", "NONYUHIBIN": "03", "UKEIRE": "A", "納入先": "日野", "SEBANGO": "742"},
                ],
            }
        ])

        gd_json = build_groupeddata_json_for_mountain(sub_rows)
        parsed = json.loads(gd_json)

        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert str(parsed[0].get("SEBANGO")) == "740"

    def test_spo_groupdata_outputs_two_pallets_for_two_clustered_stores(self):
        """I12-B-3/I12-B-5 の束ね代表行2件は groupdata でも2要素になること。"""
        proc_details = pd.DataFrame([
            {
                "山通番": 308,
                "ストア": "I12-B-3",
                "NONYUHIBIN": "03",
                "UKEIRE": "A",
                "納入先": "日野",
                "SEBANGO": "740",
                "移動工数": 50,
                "_merged_rows": [
                    {"ストア": "I12-B-3", "SEBANGO": "740"},
                    {"ストア": "I12-B-3", "SEBANGO": "742"},
                ],
            },
            {
                "山通番": 308,
                "ストア": "I12-B-5",
                "NONYUHIBIN": "05",
                "UKEIRE": "A",
                "納入先": "日野",
                "SEBANGO": "739",
                "移動工数": 45,
                "_merged_rows": [
                    {"ストア": "I12-B-5", "SEBANGO": "739"},
                    {"ストア": "I12-B-5", "SEBANGO": "741"},
                ],
            },
        ])

        out = build_spo_export_df(
            proc_details,
            mountain_proc_map={308: PROC_MAIN},
            mountain_start_times={308: "08:00"},
        )

        assert len(out) == 1
        row = out.iloc[0]
        assert int(row["パレット数"]) == 2
        recs = json.loads(str(row["GroupedData"]))
        assert len(recs) == 2
        assert {str(r.get("OData__x30b9__x30c8__x30a2_")) for r in recs} == {"I12-B-3", "I12-B-5"}
        assert {str(r.get("SEBANGO")) for r in recs} == {"739", "740"}

    def test_dataframe_list_roundtrip_keeps_core_columns_and_types(self):
        """DataFrame->list[dict]->DataFrame 変換で主要列の順序と型が維持されること。"""
        src = pd.DataFrame([
            {"山通番": 1, "ストア": "I12-B-3", "HINBAN": "616425003000", "移動工数": 50.0, "高さ": 1200},
            {"山通番": 1, "ストア": "I12-B-3", "HINBAN": "616465005000", "移動工数": 60.0, "高さ": 1100},
        ])

        base_cols = list(src.columns)
        rows = src.to_dict(orient="records")
        clustered = cluster_by_store(rows)
        clustered_df = pd.DataFrame(clustered)
        ordered_cols = [c for c in base_cols if c in clustered_df.columns]
        extra_cols = [c for c in clustered_df.columns if c not in ordered_cols]
        out = clustered_df.loc[:, ordered_cols + extra_cols].copy()

        assert list(out.columns[:len(base_cols)]) == base_cols
        assert out["山通番"].dtype.kind in {"i", "u"}
        assert out["移動工数"].dtype.kind == "f"
        assert out["高さ"].dtype.kind in {"i", "u"}

    # ------------------------------------------------------------------ #
    # 追加: 混在ケース（2つのSTOREが共存する場合の独立性確認）
    # ------------------------------------------------------------------ #
    def test_mixed_case_both_stores_handled_independently(self):
        """異種STORE（束ね対象+非束ね対象）が共存しても正しく処理されること。"""
        rows = [
            {"ストア": "I12-B-3", "HINBAN": "616425003000", "移動工数": 50},
            {"ストア": "I12-B-3", "HINBAN": "616465005000", "移動工数": 60},
            {"ストア": "N12-A-19", "HINBAN": "616425003000", "移動工数": 50},
            {"ストア": "N12-A-19", "HINBAN": "616425003000", "移動工数": 50},
        ]
        result = cluster_by_store(rows)
        i12_rows = [r for r in result if r.get("ストア") == "I12-B-3"]
        n12_rows = [r for r in result if r.get("ストア") == "N12-A-19"]
        assert len(i12_rows) == 1, f"I12-B-3は1行に束ねられるべきです。実際: {len(i12_rows)}行"
        assert len(n12_rows) == 2, f"N12-A-19は2行のまま維持されるべきです。実際: {len(n12_rows)}行"

    # ------------------------------------------------------------------ #
    # 追加: 空リストは空リストを返す
    # ------------------------------------------------------------------ #
    def test_empty_input_returns_empty(self):
        """空リストを渡した場合は空リストが返ること。"""
        assert cluster_by_store([]) == []

    # ------------------------------------------------------------------ #
    # 追加: STOREが1行だけの場合は変化しない
    # ------------------------------------------------------------------ #
    def test_single_row_store_is_unchanged(self):
        """1行しかないSTOREはそのまま返ること。"""
        rows = [{"ストア": "X-01", "HINBAN": "AAA", "移動工数": 30}]
        result = cluster_by_store(rows)
        assert len(result) == 1
        assert result[0] == rows[0]

    # ------------------------------------------------------------------ #
    # 追加: 3種HINBANも1行に束ねられること
    # ------------------------------------------------------------------ #
    def test_three_different_hinbans_merged_into_one_row(self):
        """3種のHINBANが同一STOREに存在する場合も1行に束ねられること。"""
        rows = [
            {"ストア": "Z-01", "HINBAN": "AAAA", "移動工数": 10},
            {"ストア": "Z-01", "HINBAN": "BBBB", "移動工数": 20},
            {"ストア": "Z-01", "HINBAN": "CCCC", "移動工数": 30},
        ]
        result = cluster_by_store(rows)
        z_rows = [r for r in result if r.get("ストア") == "Z-01"]
        assert len(z_rows) == 1
        assert set(z_rows[0]["_merged_hinban"]) == {"AAAA", "BBBB", "CCCC"}


class TestSize1And21Stacking:
    def test_size21_only_forms_valid_mountain(self):
        """サイズ21のみでも有効な1山を形成し、一時列は出力に残さない。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "21", "高さ": 1200, "移動工数": 10, "NONYUHIBIN": "01", "納入先": "高岡", "UKEIRE": "A", "SYUKKASAKI": "高岡"},
            {"サイズ種類": "21", "高さ": 1100, "移動工数": 9, "NONYUHIBIN": "01", "納入先": "高岡", "UKEIRE": "A", "SYUKKASAKI": "高岡"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")

        assert details["山通番"].nunique() == 1
        assert details["サイズ種類"].astype(str).eq("21").all()
        assert "_is_size1" not in details.columns
        assert "_is_size21" not in details.columns
        assert "_role_class" not in details.columns

    def test_height_cap_keeps_units_separate(self):
        """高さ上限を超える1+21は統合されず別山のまま維持される。"""
        expanded = pd.DataFrame([
            {"サイズ種類": "1", "高さ": 1500, "移動工数": 10, "NONYUHIBIN": "01", "納入先": "高岡", "UKEIRE": "A", "SYUKKASAKI": "高岡"},
            {"サイズ種類": "21", "高さ": 1200, "移動工数": 9, "NONYUHIBIN": "01", "納入先": "高岡", "UKEIRE": "A", "SYUKKASAKI": "高岡"},
        ])

        _, details = _build_size1_mixed(expanded, height_cap=2450, mixing_key="UKEIRE")

        assert details["山通番"].nunique() == 2
        assert len(details["山通番"].astype(int).unique()) == 2

    def test_match_units_no_size1_on_size21_unit(self):
        """_has_size21=True の山には _has_size1=True の山を積まない。"""
        units = pd.DataFrame([
            {
                "山ID": 1,
                "高さ合計": 1200,
                "NONYUHIBIN": "01",
                "納入先": "高岡",
                "_has_size1": False,
                "_has_size21": True,
            },
            {
                "山ID": 2,
                "高さ合計": 1000,
                "NONYUHIBIN": "01",
                "納入先": "高岡",
                "_has_size1": True,
                "_has_size21": False,
            },
        ])

        id_map = _match_units_with_layer_rules(units, height_cap=2450)

        assert id_map.get(2) != 1
        assert (2, 1) not in id_map.items()



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
