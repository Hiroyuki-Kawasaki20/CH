# -*- coding: utf-8 -*-
"""
build_groupeddata_json_for_mountain の「番号」採番ルールをテストする。

仕様: 山の中のパレットは「移動工数の昇順」で番号 1, 2, 3 … を振る。
     同値の場合は SEBANGO 昇順（なければ 工程内No 昇順）で安定化する。

実データ検証:
  06便（NONYUHIBIN=2026070110）
    Q10-B-7  : 移動工数=72.908(最小) → 番号1
    Q10-A-11 : 移動工数=72.911       → 番号2
    Q10-A-12 : 移動工数=72.912       → 番号3

  W5便
    Q10-A-20 : 移動工数=72.914       → 番号1
    Q10-A-22 : 移動工数=72.915       → 番号2
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.exporter import build_groupeddata_json_for_mountain

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_row(store: str, ido_kosuu: float, sebango: str = "", proc_no: int = 1,
              nonyuhibin: str = "2026070110", ukeire: str = "CH",
              noireyuki: str = "Q10") -> dict:
    """テスト用パレット行を生成する。"""
    return {
        "ストア": store,
        "移動工数": ido_kosuu,
        "SEBANGO": sebango,
        "工程内No": proc_no,
        "NONYUHIBIN": nonyuhibin,
        "UKEIRE": ukeire,
        "納入先": noireyuki,
        "引取済": "",
    }


# ---------------------------------------------------------------------------
# テスト: 06便の3パレット（実データ値）
# ---------------------------------------------------------------------------

class TestGroupeddataBin06:
    """06便 Q10 ストア3枚の採番テスト。"""

    def setup_method(self):
        # 意図的に移動工数が昇順でない順序で DataFrame を作成する（ソート前後を検証）
        rows = [
            _make_row("Q10-A-11", 72.911, sebango="A-11", proc_no=1),
            _make_row("Q10-A-12", 72.912, sebango="A-12", proc_no=2),
            _make_row("Q10-B-7",  72.908, sebango="B-7",  proc_no=3),  # 最小だが最後に並べる
        ]
        self.df = pd.DataFrame(rows)

    def test_番号1は移動工数最小のパレット(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        num1_row = next(r for r in result if r["番号"] == 1)
        assert num1_row["OData__x30b9__x30c8__x30a2_"] == "Q10-B-7", (
            "移動工数=72.908(最小)の Q10-B-7 が 番号1 であること"
        )

    def test_番号順序が移動工数昇順(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        numbering = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in numbering]
        assert stores == ["Q10-B-7", "Q10-A-11", "Q10-A-12"], (
            "番号 1→2→3 は Q10-B-7 → Q10-A-11 → Q10-A-12 の順であること"
        )

    def test_番号は1始まりの連番(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        bangoset = sorted(r["番号"] for r in result)
        assert bangoset == [1, 2, 3]

    def test_json_キー構成が変わらない(self):
        """出力 JSON のキー一覧が仕様通りであること。"""
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        expected_keys = {
            "OData__x30b9__x30c8__x30a2_",
            "NONYUHIBIN", "UKEIRE",
            "OData__x7d0d__x5165__x5148_",
            "SEBANGO", "番号", "引取済",
        }
        for rec in result:
            assert set(rec.keys()) == expected_keys


# ---------------------------------------------------------------------------
# テスト: W5便の2パレット（実データ値）
# ---------------------------------------------------------------------------

class TestGroupeddataBinW5:
    """W5便 Q10 ストア2枚の採番テスト。新ルールでも壊れないことを検証する。"""

    def setup_method(self):
        rows = [
            _make_row("Q10-A-20", 72.914, sebango="A-20", proc_no=1, nonyuhibin="W5"),
            _make_row("Q10-A-22", 72.915, sebango="A-22", proc_no=2, nonyuhibin="W5"),
        ]
        self.df = pd.DataFrame(rows)

    def test_番号1はA_20(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        num1_row = next(r for r in result if r["番号"] == 1)
        assert num1_row["OData__x30b9__x30c8__x30a2_"] == "Q10-A-20"

    def test_番号2はA_22(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        num2_row = next(r for r in result if r["番号"] == 2)
        assert num2_row["OData__x30b9__x30c8__x30a2_"] == "Q10-A-22"

    def test_W5便の順序はA20_A22のまま(self):
        result = json.loads(build_groupeddata_json_for_mountain(self.df))
        numbering = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in numbering]
        assert stores == ["Q10-A-20", "Q10-A-22"]


# ---------------------------------------------------------------------------
# テスト: エッジケース
# ---------------------------------------------------------------------------

class TestGroupeddataEdgeCases:
    """空入力・1件・移動工数NaNのエッジケース。"""

    def test_空DataFrameで空リスト(self):
        result = build_groupeddata_json_for_mountain(pd.DataFrame())
        assert result == "[]"

    def test_Noneで空リスト(self):
        result = build_groupeddata_json_for_mountain(None)
        assert result == "[]"

    def test_1件のみは番号1(self):
        df = pd.DataFrame([_make_row("Q10-A-1", 100.0, sebango="A-1")])
        result = json.loads(build_groupeddata_json_for_mountain(df))
        assert len(result) == 1
        assert result[0]["番号"] == 1

    def test_移動工数NaNは末尾に(self):
        """移動工数が NaN のパレットは末尾（番号最大）になること。"""
        rows = [
            _make_row("STORE-B", 50.0, sebango="B"),
            _make_row("STORE-A", float("nan"), sebango="A"),
            _make_row("STORE-C", 30.0, sebango="C"),
        ]
        df = pd.DataFrame(rows)
        result = json.loads(build_groupeddata_json_for_mountain(df))
        # 番号3 が NaN の STORE-A であること
        num3_row = next(r for r in result if r["番号"] == 3)
        assert num3_row["OData__x30b9__x30c8__x30a2_"] == "STORE-A"

    def test_移動工数同値はSEBANGO昇順で安定化(self):
        """移動工数が同じ場合、SEBANGO の昇順が番号採番に使われること。"""
        rows = [
            _make_row("STORE-Z", 80.0, sebango="Z-99"),
            _make_row("STORE-A", 80.0, sebango="A-01"),
            _make_row("STORE-M", 80.0, sebango="M-50"),
        ]
        df = pd.DataFrame(rows)
        result = json.loads(build_groupeddata_json_for_mountain(df))
        numbering = sorted(result, key=lambda r: r["番号"])
        sebangs = [r["SEBANGO"] for r in numbering]
        assert sebangs == ["A-01", "M-50", "Z-99"]

    def test_SEBANGO列なし_工程内No昇順で安定化(self):
        """SEBANGO 列がない場合、工程内No 昇順で同値安定化されること。"""
        rows = [
            {"ストア": "S-3", "移動工数": 60.0, "工程内No": 3, "NONYUHIBIN": "T1",
             "UKEIRE": "U1", "納入先": "N1", "引取済": ""},
            {"ストア": "S-1", "移動工数": 60.0, "工程内No": 1, "NONYUHIBIN": "T1",
             "UKEIRE": "U1", "納入先": "N1", "引取済": ""},
            {"ストア": "S-2", "移動工数": 60.0, "工程内No": 2, "NONYUHIBIN": "T1",
             "UKEIRE": "U1", "納入先": "N1", "引取済": ""},
        ]
        df = pd.DataFrame(rows)
        result = json.loads(build_groupeddata_json_for_mountain(df))
        numbering = sorted(result, key=lambda r: r["番号"])
        stores = [r["OData__x30b9__x30c8__x30a2_"] for r in numbering]
        assert stores == ["S-1", "S-2", "S-3"]

    def test_移動工数列なしは入力順で採番(self):
        """移動工数列が存在しない DataFrame（束ね代表行など）は入力順で採番されること。"""
        rows = [
            {"山通番": 1, "ストア": "I12-B-3", "NONYUHIBIN": "03",
             "UKEIRE": "A", "納入先": "日野", "SEBANGO": "740",
             "_merged_rows": [
                 {"ストア": "I12-B-3", "NONYUHIBIN": "03", "UKEIRE": "A",
                  "納入先": "日野", "SEBANGO": "740"},
                 {"ストア": "I12-B-3", "NONYUHIBIN": "03", "UKEIRE": "A",
                  "納入先": "日野", "SEBANGO": "742"},
             ]},
        ]
        df = pd.DataFrame(rows)
        # 移動工数列が存在しないことを確認
        assert "移動工数" not in df.columns
        # KeyError が発生せず、番号1が振られること
        result = json.loads(build_groupeddata_json_for_mountain(df))
        assert len(result) == 1
        assert result[0]["番号"] == 1
