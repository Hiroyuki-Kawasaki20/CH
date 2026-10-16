# -*- coding: utf-8 -*-
"""山内パレットの採番順は、GroupedData の「番号」と GUI セットボードの「└N」で同じ（Issue #81）。

実例: GUI は サイズ21 を先頭にしておらず、移動工数の位置に出していた。
"""
import json
import types

import pandas as pd
import pytest

from src.models.constants import PROC_MAIN
from src.services.exporter import (
    build_groupeddata_json_for_mountain,
    sort_pallets_for_numbering,
)


def _pallets():
    """サイズ21が移動工数の中間に来るデータ。採番順は A-13(21) → A-12 → A-24。"""
    base = {"NONYUHIBIN": "2026101612", "UKEIRE": "06", "納入先": "日野"}
    return pd.DataFrame([
        {**base, "ストア": "Q10-A-12", "SEBANGO": 195, "移動工数": 100.0, "サイズ種類": "1"},
        {**base, "ストア": "Q10-A-13", "SEBANGO": 196, "移動工数": 200.0, "サイズ種類": "21"},
        {**base, "ストア": "Q10-A-24", "SEBANGO": 443, "移動工数": 300.0, "サイズ種類": "1"},
    ])


def _groupeddata_store_order(df):
    gd = json.loads(build_groupeddata_json_for_mountain(df))
    return [r["OData__x30b9__x30c8__x30a2_"] for r in sorted(gd, key=lambda r: r["番号"])]


def test_numbering_puts_size21_first():
    out = sort_pallets_for_numbering(_pallets(), "納入先")
    assert out["ストア"].tolist() == ["Q10-A-13", "Q10-A-12", "Q10-A-24"]


def test_numbering_matches_groupeddata_numbers():
    df = _pallets()
    assert sort_pallets_for_numbering(df, "納入先")["ストア"].tolist() == _groupeddata_store_order(df)


def test_numbering_without_size_column_sorts_by_cost():
    df = _pallets().drop(columns=["サイズ種類"])
    out = sort_pallets_for_numbering(df, "納入先")
    assert out["ストア"].tolist() == ["Q10-A-12", "Q10-A-13", "Q10-A-24"]


def test_numbering_does_not_modify_input():
    df = _pallets()
    before = df.copy()
    sort_pallets_for_numbering(df, "納入先")
    pd.testing.assert_frame_equal(df, before)


# ===== GUI（セットボードの詳細行）=====
gui = pytest.importorskip("src.app.gui")


class _FakeTree:
    def __init__(self):
        self.inserted = []

    def get_children(self):
        return []

    def delete(self, *_a, **_k):
        pass

    def insert(self, parent, index, iid=None, values=(), tags=()):
        self.inserted.append({"iid": iid, "values": tuple(values), "tags": tuple(tags)})

    def tag_configure(self, *_a, **_k):
        pass

    def bind(self, *_a, **_k):
        pass


def test_setboard_detail_order_matches_groupeddata_numbers():
    df = _pallets()
    expected = _groupeddata_store_order(df)

    disp = df.copy()
    disp["山通番"] = 1
    disp["高さ"] = 500
    disp["工程内No"] = range(1, len(disp) + 1)
    stub = types.SimpleNamespace(
        sb_main_tree=_FakeTree(), sb_relief_tree=_FakeTree(), sb_overflow_tree=_FakeTree(),
        proc_details_display=disp, proc_details=disp,
        mountain_start_times={1: "09:59"},
        mountain_proc=pd.DataFrame(),
        mountain_proc_map={1: PROC_MAIN},
        _sb_lane_columns=("開始時間", "納入先", "ストア", "オーダー", "受入"),
        _shorten_order=gui.App._shorten_order,
        _on_setboard_select=lambda *_a, **_k: None,
    )
    gui.App.update_setboard_views(stub)

    detail = [r for r in stub.sb_main_tree.inserted if str(r["iid"]).startswith("sbd:")]
    assert [r["values"][0] for r in detail] == ["└1", "└2", "└3"]
    assert [r["values"][2] for r in detail] == expected