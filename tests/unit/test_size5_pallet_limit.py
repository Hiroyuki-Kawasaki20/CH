# -*- coding: utf-8 -*-
"""サイズ5パレット2枚制限テスト"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import pandas as pd
import numpy as np
from src.services.sorter import assign_groups_sequential
from src.models.constants import SIZE5_TYPE, SIZE5_MAX_PALLETS_PER_YAMA, DEFAULT_HEIGHT_CAP


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
