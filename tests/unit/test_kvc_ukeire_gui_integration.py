# -*- coding: utf-8 -*-
"""
CHかんばんセット — KVC UKEIREフィルタ統合テスト

GUI選択 → run_pipeline → 出力結果まで通した検証
"""

import pytest
import pandas as pd
import numpy as np
from src.services.data_loader import DataManager, load_pickup_time_master_xlsx, load_data
from src.services.sorter import run_pipeline
from src.models.constants import DEFAULT_HEIGHT_CAP, DEFAULT_MIXING_KEY


class TestKvcUkeireGuiIntegration:
    """GUI選択時のUKEIREフィルタが最終出力に反映されることを検証"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """テスト前準備"""
        self.df_shipments, self.df_places = load_data()
        self.data_mgr = DataManager(self.df_shipments, self.df_places)
        
        # 入車時間マスタを読み込む
        try:
            self.master_data = load_pickup_time_master_xlsx()
        except Exception:
            self.master_data = pd.DataFrame(
                columns=["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]
            )

    def test_kvc_b7_selection_outputs_only_b7_mountains(self):
        """
        KVC-B7を選択して run_pipeline を実行した結果、
        出力された山（filtered, expanded等）に UKEIRE=='B3' が含まれないことを検証。
        """
        # KVC-B7 のオーダーを数件取得
        kvc_orders_b7 = self.data_mgr.get_orders_for_route("KVC", ukeire="B7")
        if not kvc_orders_b7:
            pytest.skip("KVC-B7 のオーダーがありません")
        
        # 最初の1-3件を選択
        selected_orders = kvc_orders_b7[:min(3, len(kvc_orders_b7))]
        
        # KVC-B7 の受入を取得
        kvc_receipts_b7 = self.data_mgr.get_receipts_for_route("KVC", ukeire="B7")
        if not kvc_receipts_b7:
            pytest.skip("KVC-B7 の受入がありません")
        
        # selections を構築（ukeire="B7" を付与）
        selections = []
        for order in selected_orders:
            for receipt in kvc_receipts_b7[:1]:  # 最初の受入のみ
                selections.append({
                    "便名": "KVC",
                    "受入": receipt,
                    "オーダー": order,
                    "ukeire": "B7",  # ← KVC-B7の場合
                })
        
        # run_pipeline を実行
        filtered, expanded, group_results, group_details, _, _, _ = run_pipeline(
            self.data_mgr,
            selections,
            DEFAULT_HEIGHT_CAP,
            DEFAULT_MIXING_KEY,
            master_df=self.master_data,
            previous_lane_end_times={},
            return_lane_end_times=True,
        )
        
        # filtered と expanded に UKEIRE=='B3' が含まれないか確認
        if not filtered.empty and "UKEIRE" in filtered.columns:
            b3_count_filtered = (filtered["UKEIRE"].astype(str).str.strip() == "B3").sum()
            assert b3_count_filtered == 0, f"filtered に B3 データが {b3_count_filtered} 件 含まれている"
        
        if not expanded.empty and "UKEIRE" in expanded.columns:
            b3_count_expanded = (expanded["UKEIRE"].astype(str).str.strip() == "B3").sum()
            assert b3_count_expanded == 0, f"expanded に B3 データが {b3_count_expanded} 件 含まれている"
        
        # group_details 内のすべてのサイズ種類について検証
        for size_type, detail_df in group_details.items():
            if not detail_df.empty and "UKEIRE" in detail_df.columns:
                b3_count = (detail_df["UKEIRE"].astype(str).str.strip() == "B3").sum()
                assert b3_count == 0, f"group_details[{size_type}] に B3 データが {b3_count} 件 含まれている"

    def test_kvc_b3_selection_outputs_only_b3_mountains(self):
        """
        KVC-B3を選択して run_pipeline を実行した結果、
        出力された山に UKEIRE=='B7' が含まれないことを検証。
        """
        # KVC-B3 のオーダーを数件取得
        kvc_orders_b3 = self.data_mgr.get_orders_for_route("KVC", ukeire="B3")
        if not kvc_orders_b3:
            pytest.skip("KVC-B3 のオーダーがありません")
        
        # 最初の1-3件を選択
        selected_orders = kvc_orders_b3[:min(3, len(kvc_orders_b3))]
        
        # KVC-B3 の受入を取得
        kvc_receipts_b3 = self.data_mgr.get_receipts_for_route("KVC", ukeire="B3")
        if not kvc_receipts_b3:
            pytest.skip("KVC-B3 の受入がありません")
        
        # selections を構築（ukeire="B3" を付与）
        selections = []
        for order in selected_orders:
            for receipt in kvc_receipts_b3[:1]:  # 最初の受入のみ
                selections.append({
                    "便名": "KVC",
                    "受入": receipt,
                    "オーダー": order,
                    "ukeire": "B3",  # ← KVC-B3の場合
                })
        
        # run_pipeline を実行
        filtered, expanded, group_results, group_details, _, _, _ = run_pipeline(
            self.data_mgr,
            selections,
            DEFAULT_HEIGHT_CAP,
            DEFAULT_MIXING_KEY,
            master_df=self.master_data,
            previous_lane_end_times={},
            return_lane_end_times=True,
        )
        
        # filtered と expanded に UKEIRE=='B7' が含まれないか確認
        if not filtered.empty and "UKEIRE" in filtered.columns:
            b7_count_filtered = (filtered["UKEIRE"].astype(str).str.strip() == "B7").sum()
            assert b7_count_filtered == 0, f"filtered に B7 データが {b7_count_filtered} 件 含まれている"
        
        if not expanded.empty and "UKEIRE" in expanded.columns:
            b7_count_expanded = (expanded["UKEIRE"].astype(str).str.strip() == "B7").sum()
            assert b7_count_expanded == 0, f"expanded に B7 データが {b7_count_expanded} 件 含まれている"
        
        # group_details 内のすべてのサイズ種類について検証
        for size_type, detail_df in group_details.items():
            if not detail_df.empty and "UKEIRE" in detail_df.columns:
                b7_count = (detail_df["UKEIRE"].astype(str).str.strip() == "B7").sum()
                assert b7_count == 0, f"group_details[{size_type}] に B7 データが {b7_count} 件 含まれている"

    def test_non_kvc_no_ukeire_filter_regression(self):
        """
        KVC以外の便名（例:日野）は ukeire未設定で従来と同一件数を返すことを検証。
        後方互換性を確認する。
        """
        routes = self.data_mgr.get_routes()
        non_kvc_routes = [r for r in routes if r != "KVC"]
        
        if not non_kvc_routes:
            pytest.skip("KVC以外の便名がありません")
        
        test_route = non_kvc_routes[0]
        
        # ukeire=None（従来）でオーダーを取得
        orders_traditional = self.data_mgr.get_orders_for_route(test_route, ukeire=None)
        
        # ukeire未指定でもオーダーを取得
        orders_without_ukeire = self.data_mgr.get_orders_for_route(test_route)
        
        # 件数が同じか確認
        assert len(orders_traditional) == len(orders_without_ukeire), \
            f"{test_route}: ukeire=None ({len(orders_traditional)} 件) と " \
            f"ukeire未指定 ({len(orders_without_ukeire)} 件) で件数が異なる"
        
        # 同じオーダーが返されているか確認
        assert set(orders_traditional) == set(orders_without_ukeire), \
            f"{test_route}: 返されるオーダーが異なる"
