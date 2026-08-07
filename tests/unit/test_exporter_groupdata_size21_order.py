# -*- coding: utf-8 -*-
"""
build_groupeddata_json_for_mountain のサイズ21優先採番ルールをテストする。

背景:
  apps側（作業中仕分け結果画面）は実物かんばんの積み順の関係で
  「番号」の降順（遅い順）に表示する。移動工数昇順採番のままだと
  サイズ21が番号最大（=画面先頭）になり、「21を先に取る」誤ったフローに見える。

新ルール:
  0) サイズ種類 == "21" の行は常に先頭（番号1側）
  1) それ以外は従来どおり移動工数昇順
  2) 同値は SEBANGO 昇順（なければ 工程内No 昇順）
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.exporter import build_groupeddata_json_for_mountain


def _make_row(store, ido_kosuu, size, sebango="", proc_no=1,
              nonyuhibin="2026070110", ukeire="CH"):
    return {
        "ストア": store,
        "移動工数": ido_kosuu,
        "サイズ種類": size,
        "SEBANGO": sebango,
        "工程内No": proc_no,
        "NONYUHIBIN": nonyuhibin,
        "UKEIRE": ukeire,
        "納入先": "Q10",
        "引取済": "",
    }


class TestSize21IsNumber1:
    """山3相当: サイズ1×2枚 + サイズ21×1枚（UKEIRE W5 / SEBANGO 478）"""

    def setup_method(self):
        rows = [
            _make_row("Q10-B-7",  72.908, "1",  sebango="120", proc_no=1),
            _make_row("Q10-A-11", 72.911, "1",  sebango="250", proc_no=2),
            _make_row("Q10-A-20", 72.914, "21", sebango="478", proc_no=3, ukeire="W5"),
        ]
        self.df = pd.DataFrame(rows)

    def test_サイズ21が番号1(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        num1 = next(r for r in result if r["番号"] == 1)
        assert num1["SEBANGO"] == "478", "サイズ21（SEBANGO 478 / W5）が番号1であること"
        assert num1["UKEIRE"] == "W5"

    def test_サイズ1同士は従来どおり移動工数昇順(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        ordered = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in ordered]
        assert stores == ["Q10-A-20", "Q10-B-7", "Q10-A-11"], (
            "番号1=21サイズ、以降はサイズ1が移動工数昇順であること"
        )

    def test_補助列が出力JSONに漏れない(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        for rec in result:
            assert "_not21" not in rec.keys()
            assert "サイズ種類" not in rec.keys()


class TestSize1OnlyUnchanged:
    """サイズ1のみの山は従来採番（移動工数昇順）のまま"""

    def test_移動工数昇順で採番(self):
        rows = [
            _make_row("Q10-A-12", 72.912, "1", sebango="A-12"),
            _make_row("Q10-B-7",  72.908, "1", sebango="B-7"),
            _make_row("Q10-A-11", 72.911, "1", sebango="A-11"),
        ]
        df = pd.DataFrame(rows)
        result = json.loads(build_groupeddata_json_for_mountain(df))
        ordered = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in ordered]
        assert stores == ["Q10-B-7", "Q10-A-11", "Q10-A-12"]


class TestFallbackNoSizeColumn:
    """サイズ種類列が無い場合は従来動作にフォールバック"""

    def test_列なしでも従来採番(self):
        rows = [
            {"ストア": "S-2", "移動工数": 60.0, "SEBANGO": "2",
             "NONYUHIBIN": "T1", "UKEIRE": "U1", "納入先": "N1", "引取済": ""},
            {"ストア": "S-1", "移動工数": 50.0, "SEBANGO": "1",
             "NONYUHIBIN": "T1", "UKEIRE": "U1", "納入先": "N1", "引取済": ""},
        ]
        df = pd.DataFrame(rows)
        assert "サイズ種類" not in df.columns
        result = json.loads(build_groupeddata_json_for_mountain(df))
        num1 = next(r for r in result if r["番号"] == 1)
        assert num1["OData__x30b9__x30c8__x30a2_"] == "S-1"


class TestAllSize21Unchanged:
    """全て21サイズの山（例: 山6）は順序不変（移動工数昇順のまま）"""

    def test_全21は移動工数昇順(self):
        rows = [
            _make_row("Q20-B-2", 80.5, "21", sebango="502"),
            _make_row("Q20-B-1", 80.2, "21", sebango="501"),
        ]
        df = pd.DataFrame(rows)
        result = json.loads(build_groupeddata_json_for_mountain(df))
        ordered = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in ordered]
        assert stores == ["Q20-B-1", "Q20-B-2"]
