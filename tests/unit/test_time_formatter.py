"""
テスト: src.utils.time_formatter

秒 (int) → "HH:MM" 形式への変換
※ 24時間超は連続表記（"25:00", "48:00" など）
"""
import pytest
from src.utils.time_formatter import seconds_to_hhMM


class TestSecondsToHHMM:
    """基本ケース: 0-86399 秒（当日内）"""

    def test_midnight(self):
        """00:00"""
        assert seconds_to_hhMM(0) == "00:00"

    def test_morning_0930(self):
        """09:30"""
        assert seconds_to_hhMM(34200) == "09:30"

    def test_noon_1200(self):
        """12:00"""
        assert seconds_to_hhMM(43200) == "12:00"

    def test_afternoon_1545(self):
        """15:45"""
        assert seconds_to_hhMM(56700) == "15:45"

    def test_almost_midnight_2359(self):
        """23:59 (当日最後)"""
        assert seconds_to_hhMM(86399) == "23:59"


class TestSecondsToHHMM24hOverflow:
    """翌日超過: >= 86400 秒（Option B: 連続表記）"""

    def test_24h_boundary_2400(self):
        """24:00 (翌日 00:00)"""
        assert seconds_to_hhMM(86400) == "24:00"

    def test_early_next_day_0100(self):
        """25:00 (翌日 01:00)"""
        assert seconds_to_hhMM(90000) == "25:00"

    def test_next_day_afternoon_1345(self):
        """37:45 (翌日 13:45)"""
        assert seconds_to_hhMM(135900) == "37:45"

    def test_almost_2days_2359(self):
        """47:59 (翌々日 前日の23:59)"""
        assert seconds_to_hhMM(172799) == "47:59"

    def test_2days_boundary_0000(self):
        """48:00 (翌々日 00:00)"""
        assert seconds_to_hhMM(172800) == "48:00"

    def test_3days_example_5010(self):
        """50:10 (3日目 02:10)"""
        assert seconds_to_hhMM(180610) == "50:10"


class TestSecondsToHHMMEdgeCases:
    """異常値・境界値"""

    def test_negative_value(self):
        """負の秒数 → N/A"""
        assert seconds_to_hhMM(-100) == "N/A"

    def test_none_value(self):
        """None → N/A"""
        assert seconds_to_hhMM(None) == "N/A"

    def test_zero_padding_single_digit_minutes(self):
        """分の 0 パディング確認"""
        assert seconds_to_hhMM(3600) == "01:00"  # 1:00
        assert seconds_to_hhMM(3660) == "01:01"  # 1:01
        assert seconds_to_hhMM(3605) == "01:00"  # 1:00 (5秒は切り捨て)

    def test_large_value(self):
        """非常に大きい秒数"""
        # 100日分
        assert seconds_to_hhMM(8640000) == "2400:00"


class TestSecondsToHHMMAccuracy:
    """計算精度: 秒単位を分単位に変換することを確認"""

    def test_61_seconds_becomes_1_minute(self):
        """61秒 = 1分1秒 (表示では 1秒は切り捨て → 1分)"""
        # 61秒 ÷ 60 = 1 余り 1
        # 表示: 00:01
        assert seconds_to_hhMM(61) == "00:01"

    def test_3599_seconds_becomes_59_minutes(self):
        """3599秒 = 59分59秒"""
        assert seconds_to_hhMM(3599) == "00:59"

    def test_3661_seconds_becomes_1h1m(self):
        """3661秒 = 1時間1分1秒"""
        assert seconds_to_hhMM(3661) == "01:01"
