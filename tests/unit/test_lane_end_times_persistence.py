# -*- coding: utf-8 -*-
"""前回終了時刻履歴のファイル永続化 — TDD fail先行テスト

GUIが落ちても履歴を巻き戻せるようにするための save/load をテストする。
"""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.lane_end_times_history import (
    save_lane_end_times_history,
    load_lane_end_times_history,
)


class TestSaveLoadRoundTrip(unittest.TestCase):
    """保存→読込で元に戻ること（往復保証）"""

    def test_roundtrip_two_entries(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            history = [
                {"メイン": 44640, "リリーフ": 43800},
                {"メイン": 43200, "リリーフ": 42300},
            ]
            self.assertTrue(save_lane_end_times_history(history, p))
            self.assertEqual(load_lane_end_times_history(p), history)

    def test_roundtrip_empty_history(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            self.assertTrue(save_lane_end_times_history([], p))
            self.assertEqual(load_lane_end_times_history(p), [])

    def test_saved_file_is_readable_json_with_japanese_keys(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            save_lane_end_times_history([{"メイン": 100}], p)
            raw = p.read_text(encoding="utf-8")
            self.assertIn("メイン", raw)          # ensure_ascii=False
            self.assertIn("history", json.loads(raw))
            self.assertIn("version", json.loads(raw))


class TestLoadResilience(unittest.TestCase):
    """壊れていても GUI を止めないこと"""

    def test_load_missing_file_returns_empty(self):
        with TemporaryDirectory() as d:
            self.assertEqual(load_lane_end_times_history(Path(d) / "none.json"), [])

    def test_load_broken_json_returns_empty(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            p.write_text("{ this is not json", encoding="utf-8")
            self.assertEqual(load_lane_end_times_history(p), [])

    def test_load_unexpected_structure_returns_empty(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
            self.assertEqual(load_lane_end_times_history(p), [])

    def test_load_history_not_a_list_returns_empty(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            p.write_text(json.dumps({"history": "notalist"}), encoding="utf-8")
            self.assertEqual(load_lane_end_times_history(p), [])


class TestAtomicWrite(unittest.TestCase):
    """途中で落ちても前回分が壊れないこと（クラッシュ耐性）"""

    def test_overwrite_keeps_valid_json(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            save_lane_end_times_history([{"メイン": 1}], p)
            save_lane_end_times_history([{"メイン": 2}], p)
            self.assertEqual(load_lane_end_times_history(p), [{"メイン": 2}])

    def test_no_temp_file_left_behind(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "hist.json"
            save_lane_end_times_history([{"メイン": 1}], p)
            leftovers = [f for f in os.listdir(d) if f != "hist.json"]
            self.assertEqual(leftovers, [])

    def test_save_creates_parent_directory(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "sub" / "deep" / "hist.json"
            self.assertTrue(save_lane_end_times_history([{"メイン": 1}], p))
            self.assertTrue(p.exists())


class TestNoRegressionOnExistingApi(unittest.TestCase):
    """既存APIを壊していないこと"""

    def test_existing_functions_still_importable(self):
        from src.services.lane_end_times_history import (
            push_lane_end_times, select_lane_end_times,
            generate_lane_end_times_label, normalize_choice_label,
            MAX_HISTORY,
        )
        self.assertEqual(MAX_HISTORY, 2)


if __name__ == "__main__":
    unittest.main()
