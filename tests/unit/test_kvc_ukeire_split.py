# -*- coding: utf-8 -*-
"""
KVC受入分割（UKEIRE別の山分け）ユニットテスト

テストケース:
1. test_kvc_b7_b3_different_arrival_creates_separate_groups
   - KVC-B7 と KVC-B3 に異なる入車時間を設定 → 別の山になることを確認
2. test_kvc_same_arrival_merges_into_one_group
   - KVC-B7 と KVC-B3 に同じ入車時間を設定 → 同一の山に混載されることを確認
3. test_non_kvc_vendor_unchanged_regression
   - KVC以外の納入先（日野）の入車時間引き当てが改修前と同一であることを確認
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import pandas as pd

from src.services.sorter import _add_arrival_time_column


# ===========================================================================
# 共通ヘルパー
# ===========================================================================

def _make_master(rows):
    """(OData_納入先, NONYUHIBIN, 入車時間) のリストから master_df を生成する。"""
    return pd.DataFrame(rows, columns=["OData_納入先", "NONYUHIBIN", "入車時間"])


def _make_shipment(rows):
    """テスト用の最小限の明細 DataFrame を生成する。"""
    return pd.DataFrame(rows)


# ===========================================================================
# 1. B7/B3 で入車時間が異なる場合 → 別グループ（別山）
# ===========================================================================

class TestKvcB7B3DifferentArrivalCreatesSeparateGroups:
    """
    マスタ: KVC-B7=08:00, KVC-B3=10:00 (異なる入車時間)
    明細: KVC行 UKEIRE=B7 と UKEIRE=B3
    期待: 入車時間が異なるため groupby("入車時間") で 2グループ
    """

    def setup_method(self):
        self.master_df = _make_master([
            {"OData_納入先": "KVC-B7", "NONYUHIBIN": "01", "入車時間": "08:00"},
            {"OData_納入先": "KVC-B3", "NONYUHIBIN": "01", "入車時間": "10:00"},
        ])
        self.shipment_df = _make_shipment([
            {
                "納入先": "KVC", "NONYUHIBIN": "01", "UKEIRE": "B7",
                "高さ": 500.0, "移動工数": 5.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "KVC",
            },
            {
                "納入先": "KVC", "NONYUHIBIN": "01", "UKEIRE": "B3",
                "高さ": 600.0, "移動工数": 5.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "KVC",
            },
        ])

    def test_arrival_times_are_assigned_correctly(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        arrivals = result["入車時間"].tolist()
        assert arrivals[0] == "08:00", f"B7行の入車時間が08:00でない: {arrivals[0]}"
        assert arrivals[1] == "10:00", f"B3行の入車時間が10:00でない: {arrivals[1]}"

    def test_groupby_arrival_time_creates_two_groups(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        groups = list(result.groupby("入車時間"))
        assert len(groups) == 2, f"グループ数が2でない: {len(groups)}"
        group_keys = {k for k, _ in groups}
        assert group_keys == {"08:00", "10:00"}

    def test_b7_rows_in_separate_group_from_b3(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        b7_arrivals = result.loc[result["UKEIRE"] == "B7", "入車時間"].unique().tolist()
        b3_arrivals = result.loc[result["UKEIRE"] == "B3", "入車時間"].unique().tolist()
        # B7とB3の入車時間が異なること → 別グループになる
        assert set(b7_arrivals) != set(b3_arrivals), "B7とB3の入車時間が一致してしまっている"


# ===========================================================================
# 2. B7/B3 で入車時間が同じ場合 → 同一グループに混載
# ===========================================================================

class TestKvcSameArrivalMergesIntoOneGroup:
    """
    マスタ: KVC-B7=09:00, KVC-B3=09:00 (同じ入車時間)
    明細: KVC行 UKEIRE=B7 と UKEIRE=B3
    期待: 入車時間が同一のため groupby("入車時間") で 1グループ
    """

    def setup_method(self):
        self.master_df = _make_master([
            {"OData_納入先": "KVC-B7", "NONYUHIBIN": "02", "入車時間": "09:00"},
            {"OData_納入先": "KVC-B3", "NONYUHIBIN": "02", "入車時間": "09:00"},
        ])
        self.shipment_df = _make_shipment([
            {
                "納入先": "KVC", "NONYUHIBIN": "02", "UKEIRE": "B7",
                "高さ": 400.0, "移動工数": 4.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "KVC",
            },
            {
                "納入先": "KVC", "NONYUHIBIN": "02", "UKEIRE": "B3",
                "高さ": 450.0, "移動工数": 4.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "KVC",
            },
        ])

    def test_arrival_times_both_assigned_same(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        arrivals = result["入車時間"].tolist()
        assert arrivals[0] == "09:00", f"B7行の入車時間が09:00でない: {arrivals[0]}"
        assert arrivals[1] == "09:00", f"B3行の入車時間が09:00でない: {arrivals[1]}"

    def test_groupby_arrival_time_creates_one_group(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        groups = list(result.groupby("入車時間"))
        assert len(groups) == 1, f"グループ数が1でない: {len(groups)}"
        assert groups[0][0] == "09:00"

    def test_both_ukeire_in_same_group(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        group_df = result.groupby("入車時間").get_group("09:00")
        ukeire_in_group = set(group_df["UKEIRE"].tolist())
        assert ukeire_in_group == {"B7", "B3"}, f"B7/B3が同一グループにない: {ukeire_in_group}"


# ===========================================================================
# 3. KVC以外の納入先は改修前と同一（後方互換ガード）
# ===========================================================================

class TestNonKvcVendorUnchangedRegression:
    """
    KVC以外の納入先（日野）の入車時間引き当てが KVC改修の影響を受けないことを確認。
    """

    def setup_method(self):
        self.master_df = _make_master([
            {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "07:30"},
            {"OData_納入先": "KVC-B7", "NONYUHIBIN": "03", "入車時間": "11:00"},
            {"OData_納入先": "KVC-B3", "NONYUHIBIN": "03", "入車時間": "13:00"},
        ])
        self.shipment_df = _make_shipment([
            {
                "納入先": "日野", "NONYUHIBIN": "03", "UKEIRE": "",
                "高さ": 800.0, "移動工数": 6.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "日野",
            },
            {
                "納入先": "KVC", "NONYUHIBIN": "03", "UKEIRE": "B7",
                "高さ": 500.0, "移動工数": 5.0, "PLANKANBANSU": 1,
                "サイズ種類": "1", "SYUKKASAKI": "KVC",
            },
        ])

    def test_hino_arrival_time_is_correct(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        hino_row = result.loc[result["納入先"] == "日野"]
        assert len(hino_row) == 1
        assert hino_row.iloc[0]["入車時間"] == "07:30", (
            f"日野の入車時間が07:30でない: {hino_row.iloc[0]['入車時間']}"
        )

    def test_kvc_b7_arrival_time_is_correct(self):
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        kvc_row = result.loc[result["UKEIRE"] == "B7"]
        assert len(kvc_row) == 1
        assert kvc_row.iloc[0]["入車時間"] == "11:00", (
            f"KVC-B7の入車時間が11:00でない: {kvc_row.iloc[0]['入車時間']}"
        )

    def test_hino_not_affected_by_kvc_ukeire_split(self):
        """日野の入車時間がKVCのUKEIREに引きずられないことを確認"""
        result = _add_arrival_time_column(self.shipment_df, self.master_df)
        # 日野行にUKEIREは空欄 → KVC-B7/KVC-B3 キーで引き当てられてはならない
        hino_arrival = result.loc[result["納入先"] == "日野", "入車時間"].iloc[0]
        assert hino_arrival == "07:30", f"日野の入車時間が不正: {hino_arrival}"
        # KVC-B7 のような入車時間ではないこと
        assert hino_arrival not in ("11:00", "13:00")
