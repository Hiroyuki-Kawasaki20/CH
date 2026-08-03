# -*- coding: utf-8 -*-
"""サイズ5パレット2枚制限テスト"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import pandas as pd
import numpy as np
from src.services.sorter import assign_groups_sequential, run_pipeline
from src.models.constants import SIZE5_TYPE, SIZE5_MAX_PALLETS_PER_YAMA, DEFAULT_HEIGHT_CAP, DEFAULT_MIXING_KEY


class TestSize5PalletLimit:
    """サイズ5パレットの1山最大2枚制限テスト"""
    
    def test_size5_4_pallets_yields_2_groups_of_2(self):
        """サイズ5・4枚（全て高さ上限内）→ 2山×2枚になること"""
        # 高さ: 全て500（合計2000 < 2450の上限）
        heights = pd.Series([500.0, 500.0, 500.0, 500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        # max_pallets=2を指定
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        # 期待: [1, 1, 2, 2] （山1に2枚、山2に2枚）
        assert groups == [1, 1, 2, 2]
        assert max(groups) == 2  # 2山
        
    def test_size5_5_pallets_yields_3_groups(self):
        """サイズ5・5枚 → 3山（2+2+1枚）になること"""
        heights = pd.Series([500.0, 500.0, 500.0, 500.0, 500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        # 期待: [1, 1, 2, 2, 3] （山1に2枚、山2に2枚、山3に1枚）
        assert groups == [1, 1, 2, 2, 3]
        assert max(groups) == 3  # 3山
        
    def test_size5_2_pallets_stays_single_group(self):
        """サイズ5・2枚 → 従来どおり1山のままであること（過剰分割しない）"""
        heights = pd.Series([500.0, 500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        # 期待: [1, 1] （1山に2枚）
        assert groups == [1, 1]
        assert max(groups) == 1  # 1山
        
    def test_size5_height_cap_takes_precedence_over_pallet_count(self):
        """高さ上限との併用: 2枚目で高さ超過する場合は高さ判定が優先して1枚で山が切れること"""
        # 1枚目: 1500mm、2枚目: 1000mm（1500+1000=2500 > 2450の上限）
        heights = pd.Series([1500.0, 1000.0, 500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        # 期待: [1, 2, 2] 
        # 1枚目(1500mm)は山1に。
        # 2枚目(1000mm)は1500+1000=2500 > 2450なので高さ超過 → 山2に。
        # 3枚目(500mm)は山2のパレット数が1なので追加可能 → 山2に。
        # つまり山2は2枚になるが、高さが2450を超えない(1000+500=1500mm)
        assert groups == [1, 2, 2]
        assert max(groups) == 2
        
    def test_assign_groups_with_none_max_pallets_behaves_like_traditional(self):
        """max_pallets=None（他サイズ相当）では従来動作が変わらないこと"""
        heights = pd.Series([500.0, 500.0, 500.0, 500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        # max_pallets=None（未指定）
        groups_none = assign_groups_sequential(heights, cap, max_pallets=None)
        # 従来呼び出し（引数なし）
        groups_traditional = assign_groups_sequential(heights, cap)
        
        # 2つが同じであることを確認
        assert groups_none == groups_traditional
        # 高さのみ制約なので全部1山
        assert groups_none == [1, 1, 1, 1]
        
    def test_size5_3_pallets_within_cap(self):
        """サイズ5・3枚全てが高さ上限内で、かつパレット数制限で2山に分かれること"""
        # 高さ各600mm → 3×600 = 1800mm < 2450
        heights = pd.Series([600.0, 600.0, 600.0])
        cap = DEFAULT_HEIGHT_CAP
        
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        # 期待: [1, 1, 2] （山1に2枚、山2に1枚）
        assert groups == [1, 1, 2]
        assert max(groups) == 2
        
    def test_size5_single_pallet_no_split(self):
        """サイズ5・1枚 → 1山のままであること"""
        heights = pd.Series([500.0])
        cap = DEFAULT_HEIGHT_CAP
        
        groups = assign_groups_sequential(heights, cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
        
        assert groups == [1]
        assert max(groups) == 1


class _StubDataManager:
    """run_pipeline テスト用のスタブ DataManager"""
    
    def __init__(self, df_shipments: pd.DataFrame):
        """df_shipments: フィルタ後のデータフレーム（受け取ったままそのまま返す）"""
        self.df_shipments = df_shipments
    
    def filter_shipments(self, selections: list) -> pd.DataFrame:
        """呼び出し時は df_shipments をそのまま返す（選択条件は既に反映済み想定）"""
        return self.df_shipments.copy()


class TestSize5RunPipelineIntegration:
    """run_pipeline における size5 max_pallets 統合テスト"""
    
    def test_run_pipeline_size5_vs_size3_max_pallets_wiring(self):
        """
        run_pipeline が size5 に対して max_pallets パラメータを正しく通していることを確認。
        size5 は 4 パレット → 2 山、size3 は 4 パレット → 1 山であることで検証。
        """
        # ========== テストデータ構築 ==========
        # サイズ5 × 4 パレット（全て高さ500mm）
        size5_rows = pd.DataFrame({
            "PLANKANBANSU": [1, 1, 1, 1],  # 4 パレット
            "サイズ種類": ["5", "5", "5", "5"],
            "高さ": [500.0, 500.0, 500.0, 500.0],
            "移動工数": [100, 100, 100, 100],
            "SYUKKASAKI": ["仕入先A", "仕入先A", "仕入先A", "仕入先A"],
        })
        
        # サイズ3 × 4 パレット（全て高さ500mm）
        size3_rows = pd.DataFrame({
            "PLANKANBANSU": [1, 1, 1, 1],  # 4 パレット
            "サイズ種類": ["3", "3", "3", "3"],
            "高さ": [500.0, 500.0, 500.0, 500.0],
            "移動工数": [100, 100, 100, 100],
            "SYUKKASAKI": ["仕入先B", "仕入先B", "仕入先B", "仕入先B"],
        })
        
        # 結合してスタブ DataManager に渡す
        all_rows = pd.concat([size5_rows, size3_rows], axis=0, ignore_index=True)
        stub_dm = _StubDataManager(all_rows)
        
        # ========== run_pipeline 実行 ==========
        filtered, expanded, group_results, group_details, _, _ = run_pipeline(
            stub_dm,
            selections=[],  # selections は使用しない（スタブが直接返す）
            height_cap=DEFAULT_HEIGHT_CAP,
            mixing_key=DEFAULT_MIXING_KEY,
            master_df=None,
            previous_lane_end_times=None,
            return_lane_end_times=False,
        )
        
        # ========== 検証 ==========
        # サイズ5 の group_details を確認
        assert "5" in group_details, "size5 が group_details に含まれていない"
        size5_details = group_details["5"]
        size5_groups = size5_details["グループ番号"].unique()
        
        # size5 の 4 パレット → 2 山 であることを確認
        assert len(size5_groups) == 2, (
            f"size5: 期待=2山、実際={len(size5_groups)}山。"
            f"max_pallets=SIZE5_MAX_PALLETS_PER_YAMA が正しく通ってない可能性あり"
        )
        
        # サイズ3 の group_details を確認
        assert "3" in group_details, "size3 が group_details に含まれていない"
        size3_details = group_details["3"]
        size3_groups = size3_details["グループ番号"].unique()
        
        # size3 の 4 パレット → 1 山 であることを確認（max_pallets なし）
        assert len(size3_groups) == 1, (
            f"size3: 期待=1山、実際={len(size3_groups)}山。"
            f"size3 は max_pallets 制限がないはずだが異常"
        )
        
        # 各グループの パレット数 を確認（group_results から）
        assert "5" in group_results, "size5 が group_results に含まれていない"
        size5_result = group_results["5"]
        size5_pallet_counts = size5_result["パレット数"].tolist()
        assert size5_pallet_counts == [2, 2], (
            f"size5 groups のパレット数期待=[2, 2]、実際={size5_pallet_counts}"
        )
        
        assert "3" in group_results, "size3 が group_results に含まれていない"
        size3_result = group_results["3"]
        size3_pallet_counts = size3_result["パレット数"].tolist()
        assert size3_pallet_counts == [4], (
            f"size3 groups のパレット数期待=[4]、実際={size3_pallet_counts}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
