"""Issue #45: セットボードの山の並び順が時系列（深夜跨ぎ考慮）であること。"""
import pandas as pd
import pytest


def _sort_key_factory(start_times):
    """gui.py の _start_sort_key と同一ロジックを外部から検証するための取り出し。"""
    from src.app import gui as gui_mod

    class _Stub:
        pass

    stub = _Stub()
    stub.mountain_start_times = start_times
    # 実装本体を関数として取得する
    fn = gui_mod.SetBoardApp.update_setboard_views if hasattr(gui_mod, "SetBoardApp") else None
    return stub, fn


class TestSetboardSortKey:
    """深夜跨ぎを含む開始時刻で、山が時系列に並ぶこと。"""

    def test_start_sort_key_orders_midnight_after_late_evening(self):
        from src.app.gui import _start_sort_key_for_test as key

        start_times = {1: "00:18", 2: "00:23", 3: "22:30", 4: "22:37", 5: "24:00"}
        got = sorted(start_times.keys(), key=lambda y: key(start_times, y))
        assert got == [3, 4, 5, 1, 2], f"expected [3,4,5,1,2] but got {got}"

    def test_daytime_order_is_unchanged(self):
        from src.app.gui import _start_sort_key_for_test as key

        start_times = {1: "14:30", 2: "08:00", 3: "10:15"}
        got = sorted(start_times.keys(), key=lambda y: key(start_times, y))
        assert got == [2, 3, 1]

    def test_invalid_value_goes_last(self):
        from src.app.gui import _start_sort_key_for_test as key

        start_times = {1: "", 2: "08:00"}
        got = sorted(start_times.keys(), key=lambda y: key(start_times, y))
        assert got == [2, 1]