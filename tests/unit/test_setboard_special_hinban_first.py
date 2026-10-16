# -*- coding: utf-8 -*-
"""セットボードの山詳細: 特例品番(Q10-A-24)の行を └1（2枚なら └1・└2）に表示する。表示専用。

作業者が特例品番を山の最上段に置く運用に、GUI の表示を合わせる。
GroupedData の「番号」（exporter.sort_pallets_for_numbering）は変えない。
"""
import types

import pandas as pd
import pytest

from src.models.constants import PROC_MAIN, SPECIAL_HINBAN

gui = pytest.importorskip("src.app.gui")

NORMAL_HINBAN = "616425003000"


def _row(store, sebango, cost, hinban=NORMAL_HINBAN):
    return {"ストア": store, "SEBANGO": sebango, "移動工数": cost, "HINBAN": hinban}


def _pallets(*rows):
    base = {"NONYUHIBIN": "2026101612", "UKEIRE": "06", "納入先": "日野", "サイズ種類": "1"}
    return pd.DataFrame([{**base, **r} for r in rows])


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


def _detail_view(df):
    """update_setboard_views を1山分だけ動かして、詳細行の (└N のリスト, ストアのリスト) を返す。"""
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
    return [r["values"][0] for r in detail], [r["values"][2] for r in detail]


def test_special_hinban_first_moves_special_to_top():
    df = _pallets(
        _row("Q10-A-11", 190, 60.0), _row("Q10-A-13", 196, 70.0),
        _row("Q10-A-24", 443, 72.9, SPECIAL_HINBAN),
    )
    out = gui._special_hinban_first(df)
    assert out["ストア"].tolist() == ["Q10-A-24", "Q10-A-11", "Q10-A-13"]


def test_special_hinban_first_keeps_relative_order_of_two_special():
    df = _pallets(
        _row("Q10-A-11", 190, 60.0), _row("Q10-A-24", 443, 72.9, SPECIAL_HINBAN),
        _row("Q10-A-13", 196, 70.0), _row("Q10-A-24", 444, 72.9, SPECIAL_HINBAN),
    )
    out = gui._special_hinban_first(df)
    assert out["SEBANGO"].tolist() == [443, 444, 190, 196]


def test_special_hinban_first_is_noop_without_special_or_hinban_column():
    df = _pallets(_row("Q10-A-11", 190, 60.0), _row("Q10-A-13", 196, 70.0))
    pd.testing.assert_frame_equal(gui._special_hinban_first(df), df)
    no_col = df.drop(columns=["HINBAN"])
    pd.testing.assert_frame_equal(gui._special_hinban_first(no_col), no_col)


def test_special_hinban_first_accepts_numeric_and_padded_hinban():
    for value in (int(SPECIAL_HINBAN), float(SPECIAL_HINBAN), f" {SPECIAL_HINBAN} "):
        df = _pallets(_row("Q10-A-11", 190, 60.0), _row("Q10-A-24", 443, 72.9, value))
        out = gui._special_hinban_first(df)
        assert out["ストア"].tolist() == ["Q10-A-24", "Q10-A-11"], value


def test_setboard_puts_special_hinban_at_first_row():
    """2026-10-16 山8型: GroupedData は A-24 が番号3。GUI は └1 に出す。"""
    df = _pallets(
        _row("Q10-A-11", 190, 60.0), _row("Q10-A-13", 196, 70.0),
        _row("Q10-A-24", 443, 72.9, SPECIAL_HINBAN),
    )
    labels, stores = _detail_view(df)
    assert labels == ["└1", "└2", "└3"]
    assert stores == ["Q10-A-24", "Q10-A-11", "Q10-A-13"]


def test_setboard_puts_two_special_hinban_at_first_and_second():
    df = _pallets(
        _row("Q10-A-11", 190, 60.0), _row("Q10-A-13", 196, 70.0),
        _row("Q10-A-24", 443, 72.9, SPECIAL_HINBAN), _row("Q10-A-24", 444, 72.9, SPECIAL_HINBAN),
    )
    labels, stores = _detail_view(df)
    assert labels == ["└1", "└2", "└3", "└4"]
    assert stores == ["Q10-A-24", "Q10-A-24", "Q10-A-11", "Q10-A-13"]


def test_setboard_without_special_keeps_groupeddata_order():
    df = _pallets(_row("Q10-A-13", 196, 70.0), _row("Q10-A-11", 190, 60.0))
    _, stores = _detail_view(df)
    assert stores == ["Q10-A-11", "Q10-A-13"]
