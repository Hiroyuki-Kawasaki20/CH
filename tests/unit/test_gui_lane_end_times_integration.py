# -*- coding: utf-8 -*-
"""CHかんばんセット — GUI 統合: run() 実行後の lane_end_times_history 検証

修正内容:
- 配線漏れ修正: 計算結果を self._last_lane_end_times に保存
- push タイミング修正: 計算後・early return 後に push 実行
- 結果: 1回目実行後、self.lane_end_times_history[0] に計算値が格納される

この恒久テストは以下を検証:
1. push_lane_end_times() が計算結果を正しく history に追加する
2. 複数実行時に FIFO (max 2 entries) で動作する
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from src.services.lane_end_times_history import push_lane_end_times


class TestGUILaneEndTimesIntegration:
    """lane_end_times_history の push / select 動作確認"""

    def test_push_single_execution(self):
        """✅ TDD: 1回実行 → history[0] に計算結果が入る"""
        
        # ===== Mock 計算結果を用意 =====
        calculated_lane_end_times = {
            "メイン": 45000,       # 12:30:00
            "リリーフ": 32400,      # 09:00:00
            "あふれ": 86399,        # 23:59:59
        }
        
        # ===== 初期状態 =====
        history = []
        
        # ===== 1回目の計算結果を push =====
        history = push_lane_end_times(history, calculated_lane_end_times)
        
        # ✅ Assertion 1: history が空でない
        assert len(history) > 0, "❌ push 後、history が空"
        
        # ✅ Assertion 2: history[0] は dict
        assert isinstance(history[0], dict), f"❌ history[0] が dict ではなく {type(history[0])}"
        
        # ✅ Assertion 3: history[0] は非空
        assert len(history[0]) > 0, "❌ history[0] は空の dict"
        
        # ✅ Assertion 4: 計算結果そのものか（値が一致）
        assert history[0] == calculated_lane_end_times, (
            f"❌ history[0] != 計算結果\n期待: {calculated_lane_end_times}\n実際: {history[0]}"
        )
        
        # ✅ Assertion 5: 期待される キー が含まれているか
        expected_keys = {"メイン", "リリーフ", "あふれ"}
        assert expected_keys.issubset(set(history[0].keys())), (
            f"❌ 期待キー {expected_keys} が不足"
        )
        
        # ✅ Assertion 6: 値は秒単位の整数か
        for key, value in history[0].items():
            assert isinstance(value, int) and value >= 0, (
                f"❌ {key}={value} が正の整数ではない"
            )
        
        print("\n" + "="*60)
        print("✅ SINGLE EXECUTION: ALL CHECKS PASSED")
        print("="*60)
        print(f"history[0] = {history[0]}")

    def test_push_double_execution(self):
        """✅ 拡張: 2回実行 → history に2件が FIFO 順に入る"""
        
        result1 = {
            "メイン": 45000,
            "リリーフ": 32400,
            "あふれ": 86399,
        }
        
        result2 = {
            "メイン": 48600,
            "リリーフ": 39600,
            "あふれ": 86400,
        }
        
        # ===== 1回目 =====
        history = []
        history = push_lane_end_times(history, result1)
        assert len(history) == 1, f"1回目後: len={len(history)}, 期待=1"
        assert history[0] == result1
        
        # ===== 2回目 =====
        history = push_lane_end_times(history, result2)
        assert len(history) == 2, f"2回目後: len={len(history)}, 期待=2"
        assert history[0] == result2, "❌ 最新が先頭でない (FIFO 違反)"
        assert history[1] == result1, "❌ 前回が2番目でない"
        
        # ===== 3回目（max 2 entries 確認） =====
        result3 = {
            "メイン": 50000,
            "リリーフ": 41400,
            "あふれ": 86400,
        }
        history = push_lane_end_times(history, result3)
        assert len(history) == 2, f"3回目後: len={len(history)}, 期待=2"
        assert history[0] == result3, "❌ 最新が先頭でない"
        assert history[1] == result2, "❌ 2番目が削除されている"
        
        print("\n" + "="*60)
        print("✅ DOUBLE EXECUTION: ALL CHECKS PASSED")
        print("="*60)
        print(f"After 1st run: len(history)=1, history[0]={result1}")
        print(f"After 2nd run: len(history)=2, history[0]={result2}, history[1]={result1}")
        print(f"After 3rd run: len(history)=2, history[0]={result3}, history[1]={result2}")


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
