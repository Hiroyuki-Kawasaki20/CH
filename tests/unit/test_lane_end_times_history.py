# -*- coding: utf-8 -*-
"""CHかんばんセット — 前回仕分け終了時刻の履歴機能テスト

機能概要:
- レーン毎の仕分け終了時刻を最大2件まで履歴保持
- ドロップダウン選択で過去の時刻に巻き戻し可能
- 新規実装時の fail 先行テスト（TDD）
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from src.services.lane_end_times_history import (
    push_lane_end_times,
    select_lane_end_times,
    MAX_HISTORY,
)


class TestPushLaneEndTimes:
    """push_lane_end_times() 関数のテスト"""

    def test_push_to_empty_history(self):
        """ケース1: 空履歴に push → 1件・それが先頭"""
        history = []
        new_times = {"山1": "08:30", "山2": "09:15"}
        
        result = push_lane_end_times(history, new_times)
        
        assert len(result) == 1
        assert result[0] == {"山1": "08:30", "山2": "09:15"}

    def test_push_adds_to_front(self):
        """ケース2: push は新しいものを先頭に積む（元の最新は2番目へ）"""
        old_times = {"山1": "08:00", "山2": "09:00"}
        history = [old_times]
        new_times = {"山1": "08:30", "山2": "09:15"}
        
        result = push_lane_end_times(history, new_times)
        
        assert len(result) == 2
        assert result[0] == {"山1": "08:30", "山2": "09:15"}  # 新 → 先頭
        assert result[1] == {"山1": "08:00", "山2": "09:00"}  # 旧 → 2番目

    def test_push_maintains_max_history_of_2(self):
        """ケース3: 3件目 push で最古破棄・常に len==MAX_HISTORY==2"""
        assert MAX_HISTORY == 2, "MAX_HISTORY は 2 であること"
        
        times_1 = {"山1": "08:00", "山2": "09:00"}
        times_2 = {"山1": "08:30", "山2": "09:15"}
        times_3 = {"山1": "09:00", "山2": "10:00"}
        
        history = [times_2, times_1]  # 2件
        result = push_lane_end_times(history, times_3)
        
        # 3件目 push で最古（times_1）が破棄される
        assert len(result) == 2
        assert result[0] == {"山1": "09:00", "山2": "10:00"}  # 最新
        assert result[1] == {"山1": "08:30", "山2": "09:15"}  # 1つ前

    def test_push_does_not_mutate_input_history(self):
        """ケース4: push は入力 history を破壊しない"""
        original_history = [{"山1": "08:00", "山2": "09:00"}]
        history_copy = [entry.copy() for entry in original_history]
        new_times = {"山1": "08:30", "山2": "09:15"}
        
        push_lane_end_times(original_history, new_times)
        
        # 入力の history は変わっていないこと
        assert original_history == history_copy

    def test_push_creates_defensive_copy(self):
        """ケース5: push した dict は防御的コピー（元 dict を後で書き換えても履歴不変）"""
        history = []
        new_times = {"山1": "08:30", "山2": "09:15"}
        
        result = push_lane_end_times(history, new_times)
        
        # 元の new_times を書き換える
        new_times["山1"] = "MODIFIED"
        new_times["山2"] = "MODIFIED"
        
        # 履歴には元の値が保持されている
        assert result[0] == {"山1": "08:30", "山2": "09:15"}
        assert result[0] != new_times


class TestSelectLaneEndTimes:
    """select_lane_end_times() 関数のテスト"""

    def test_select_latest_when_available(self):
        """ケース6: select "最新" → 先頭"""
        history = [
            {"山1": "08:30", "山2": "09:15"},
            {"山1": "08:00", "山2": "09:00"},
        ]
        
        result = select_lane_end_times(history, "最新")
        
        assert result == {"山1": "08:30", "山2": "09:15"}

    def test_select_previous_when_available(self):
        """ケース7: select "1つ前" → 2番目"""
        history = [
            {"山1": "08:30", "山2": "09:15"},
            {"山1": "08:00", "山2": "09:00"},
        ]
        
        result = select_lane_end_times(history, "1つ前")
        
        assert result == {"山1": "08:00", "山2": "09:00"}

    def test_select_latest_from_empty_history_returns_empty_dict(self):
        """ケース8: 0件で "最新" → {}"""
        history = []
        
        result = select_lane_end_times(history, "最新")
        
        assert result == {}

    def test_select_previous_from_single_entry_returns_empty_dict(self):
        """ケース9: 1件で "1つ前" → {}"""
        history = [{"山1": "08:30", "山2": "09:15"}]
        
        result = select_lane_end_times(history, "1つ前")
        
        assert result == {}

    def test_select_unknown_choice_defaults_to_latest(self):
        """ケース10: 未知 choice → "最新"扱い"""
        history = [
            {"山1": "08:30", "山2": "09:15"},
            {"山1": "08:00", "山2": "09:00"},
        ]
        
        result_unknown = select_lane_end_times(history, "未知の選択肢")
        result_latest = select_lane_end_times(history, "最新")
        
        assert result_unknown == result_latest
        assert result_unknown == {"山1": "08:30", "山2": "09:15"}

    def test_select_latest_from_single_entry_returns_that_entry(self):
        """補足: 1件で "最新" を選ぶと、その1件が返る"""
        history = [{"山1": "08:30", "山2": "09:15"}]
        
        result = select_lane_end_times(history, "最新")
        
        assert result == {"山1": "08:30", "山2": "09:15"}


class TestLaneEndTimesHistoryScenario:
    """統合シナリオテスト"""

    def test_scenario_redo_with_previous_baseline(self):
        """ケース11: A案の中核シナリオ
        
        [山3=300, 山2=200] で "1つ前"(=200)を選び再実行結果250をpush
        → [250, 300] になり、再度 "1つ前" で 300 に戻れる
        （＝やり直しで基準がずれ続けない）
        """
        # 初期状態: 山3=300, 山2=200 を持つ履歴
        history = [
            {"山3": 300, "山2": 200},
        ]
        
        # "1つ前" を選ぶ（この場合 1件しかないので {} が返る？）
        # 「中核シナリオ」の解釈: 2件あると仮定
        history = [
            {"山3": 300, "山2": 200},  # 最新
            {"山3": 250, "山2": 180},  # 1つ前（前回のやり直し基準）
        ]
        
        # "1つ前" を選ぶ
        selected = select_lane_end_times(history, "1つ前")
        assert selected == {"山3": 250, "山2": 180}, "1つ前が選ばれる"
        
        # 選んだ基準で再実行 → 結果 250
        new_result = {"山3": 250, "山2": 190}  # 今回の再実行結果
        
        # 新しい結果を push
        history = push_lane_end_times(history, new_result)
        
        # push 後の状態を確認
        assert len(history) == 2
        assert history[0] == {"山3": 250, "山2": 190}, "新しい結果が先頭に"
        assert history[1] == {"山3": 300, "山2": 200}, "前回の最新が2番目に"
        
        # 再度 "1つ前" を選ぶと前回の最新に戻れる
        re_selected = select_lane_end_times(history, "1つ前")
        assert re_selected == {"山3": 300, "山2": 200}, "前回の基準に戻れる"


class TestIntegrationWithMultiplePushes:
    """複数回の push 操作の統合テスト"""

    def test_push_sequence_maintains_order(self):
        """複数回 push してもFIFO順序が保持される"""
        history = []
        
        # 1回目: 08:00
        history = push_lane_end_times(history, {"山1": "08:00"})
        assert len(history) == 1
        assert history[0] == {"山1": "08:00"}
        
        # 2回目: 08:30
        history = push_lane_end_times(history, {"山1": "08:30"})
        assert len(history) == 2
        assert history[0] == {"山1": "08:30"}
        assert history[1] == {"山1": "08:00"}
        
        # 3回目: 09:00（最古破棄）
        history = push_lane_end_times(history, {"山1": "09:00"})
        assert len(history) == 2
        assert history[0] == {"山1": "09:00"}
        assert history[1] == {"山1": "08:30"}
        assert not any("08:00" in str(v) for v in history), "08:00 は破棄される"

    def test_select_always_returns_copy(self):
        """select が返す dict は独立したコピー（返り値の編集が元に影響しない）"""
        original_times = {"山1": "08:30", "山2": "09:15"}
        history = [original_times.copy()]
        
        selected = select_lane_end_times(history, "最新")
        
        # 返された dict を編集
        selected["山1"] = "MODIFIED"
        
        # 元の履歴には影響がない
        re_selected = select_lane_end_times(history, "最新")
        assert re_selected == {"山1": "08:30", "山2": "09:15"}


class TestGenerateLaneEndTimesLabel:
    """generate_lane_end_times_label() 関数のテスト
    
    履歴から Combobox 用ラベルを生成
    例: "最新 (メイン 12:24 / リリーフ 12:10)"
    """

    def test_generate_label_empty_history_latest(self):
        """空履歴で最新 → '最新 (未計算)'"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = []
        result = generate_lane_end_times_label(history, "最新")
        
        assert result == "最新 (未計算)"

    def test_generate_label_empty_history_previous(self):
        """空履歴で 1つ前 → '1つ前 (未計算)'"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = []
        result = generate_lane_end_times_label(history, "1つ前")
        
        assert result == "1つ前 (未計算)"

    def test_generate_label_single_entry_latest(self):
        """1件で最新 → 時刻表示"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        # 秒単位のデータ: メイン 12:00 (43200秒), リリーフ 11:45 (42300秒)
        history = [{"メイン": 43200, "リリーフ": 42300}]
        result = generate_lane_end_times_label(history, "最新")
        
        assert result == "最新 (メイン 12:00 / リリーフ 11:45)"

    def test_generate_label_single_entry_previous(self):
        """1件で 1つ前 → '1つ前 (未計算)'"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = [{"メイン": 43200, "リリーフ": 42300}]
        result = generate_lane_end_times_label(history, "1つ前")
        
        assert result == "1つ前 (未計算)"

    def test_generate_label_two_entries_latest(self):
        """2件で最新 → 最新の時刻"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = [
            {"メイン": 44640, "リリーフ": 43560},  # 12:24, 12:06
            {"メイン": 43200, "リリーフ": 42300},  # 12:00, 11:45
        ]
        result = generate_lane_end_times_label(history, "最新")
        
        assert result == "最新 (メイン 12:24 / リリーフ 12:06)"

    def test_generate_label_two_entries_previous(self):
        """2件で 1つ前 → 1つ前の時刻"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = [
            {"メイン": 44640, "リリーフ": 43560},  # 12:24, 12:06
            {"メイン": 43200, "リリーフ": 42300},  # 12:00, 11:45
        ]
        result = generate_lane_end_times_label(history, "1つ前")
        
        assert result == "1つ前 (メイン 12:00 / リリーフ 11:45)"

    def test_generate_label_missing_key_uses_zero(self):
        """キーが存在しない場合 → 0 (00:00) を使用"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = [{"メイン": 43200}]  # リリーフキーがない
        result = generate_lane_end_times_label(history, "最新")
        
        # リリーフは 0 → "00:00"
        assert result == "最新 (メイン 12:00 / リリーフ 00:00)"

    def test_generate_label_negative_value_becomes_na(self):
        """負の値 → N/A"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        history = [{"メイン": -100, "リリーフ": 42300}]
        result = generate_lane_end_times_label(history, "最新")
        
        assert result == "最新 (メイン N/A / リリーフ 11:45)"

    def test_generate_label_24h_overflow(self):
        """翌日超過 >= 86400 → 25:00 形式"""
        from src.services.lane_end_times_history import generate_lane_end_times_label
        
        # 翌日01:00 = 90000秒
        history = [{"メイン": 90000, "リリーフ": 86400}]
        result = generate_lane_end_times_label(history, "最新")
        
        assert result == "最新 (メイン 25:00 / リリーフ 24:00)"


class TestNormalizeChoiceLabel:
    """normalize_choice_label() 関数のテスト
    
    ドロップダウンラベルから 最新/1つ前 を抽出
    例: 最新 (メイン 12:00 / ...) → 最新
    """

    def test_normalize_latest_with_parentheses(self):
        """ラベルから 最新 を抽出"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "最新 (メイン 12:00 / リリーフ 11:45)"
        result = normalize_choice_label(label)
        
        assert result == "最新"

    def test_normalize_previous_with_parentheses(self):
        """ラベルから 1つ前 を抽出"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "1つ前 (メイン 12:00 / リリーフ 11:45)"
        result = normalize_choice_label(label)
        
        assert result == "1つ前"

    def test_normalize_latest_not_yet_calculated(self):
        """最新 (未計算) から 最新 を抽出"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "最新 (未計算)"
        result = normalize_choice_label(label)
        
        assert result == "最新"

    def test_normalize_previous_not_yet_calculated(self):
        """1つ前 (未計算) から 1つ前 を抽出"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "1つ前 (未計算)"
        result = normalize_choice_label(label)
        
        assert result == "1つ前"

    def test_normalize_already_normalized(self):
        """既に 最新 のみ → そのまま返す"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "最新"
        result = normalize_choice_label(label)
        
        assert result == "最新"

    def test_normalize_1tsumaae_already_normalized(self):
        """既に 1つ前 のみ → そのまま返す"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        label = "1つ前"
        result = normalize_choice_label(label)
        
        assert result == "1つ前"

    def test_normalize_with_various_parentheses_content(self):
        """括弧内の内容が異なっても動作"""
        from src.services.lane_end_times_history import normalize_choice_label
        
        labels = [
            ("最新 (メイン 25:00 / リリーフ 24:00)", "最新"),
            ("1つ前 (メイン 12:00 / リリーフ 11:45)", "1つ前"),
            ("最新 (未計算)", "最新"),
            ("1つ前 (未計算)", "1つ前"),
        ]
        
        for label, expected in labels:
            result = normalize_choice_label(label)
            assert result == expected, f"Failed for label: {label}"
