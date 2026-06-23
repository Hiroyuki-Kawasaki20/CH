# -*- coding: utf-8 -*-
"""CHかんばんセット — データローダーのユニットテスト"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.data_loader import parse_ukeire_ch_excel
from src.utils.csv_utils import read_csv_ja


def test_read_csv_ja_raises_clear_error_for_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    try:
        read_csv_ja(path)
        assert False, "empty csv should raise ValueError"
    except ValueError as e:
        assert "CSVが空です" in str(e)
        assert str(path) in str(e)


def test_parse_ukeire_ch_excel_filters_only_ch_and_formats_bin(tmp_path):
    src = pd.DataFrame(
        {
            "受入": ["CH", "GH", "ch"],
            "納入先": ["日野プレス", "武部", "TMK"],
            "納入便": [1, 2, "03"],
            "入車時間": ["8:30", "09:10", "10:05:00"],
        }
    )
    path = tmp_path / "sample.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        src.to_excel(writer, sheet_name="全受入_納入便データ", index=False)

    out = parse_ukeire_ch_excel(path)

    assert len(out) == 2
    assert list(out.columns) == ["OData_納入先", "NONYUHIBIN", "入車時間"]
    assert out.iloc[0]["OData_納入先"] == "KVC"
    assert out.iloc[0]["NONYUHIBIN"] == "03"
    assert out.iloc[0]["入車時間"] == "10:05"
    assert out.iloc[1]["OData_納入先"] == "日野"
    assert out.iloc[1]["NONYUHIBIN"] == "01"
    assert out.iloc[1]["入車時間"] == "08:30"


def test_parse_ukeire_ch_excel_accepts_header_aliases(tmp_path):
    src = pd.DataFrame(
        {
            "受入": ["CH"],
            "便名": ["三栄SE"],
            "便No.": ["12"],
            "到着時間": ["１２：４０"],
        }
    )
    path = tmp_path / "alias.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        src.to_excel(writer, sheet_name="全受入_納入便データ", index=False)

    out = parse_ukeire_ch_excel(path)

    assert len(out) == 1
    assert out.iloc[0]["OData_納入先"] == "三栄"
    assert out.iloc[0]["NONYUHIBIN"] == "12"
    assert out.iloc[0]["入車時間"] == "12:40"


def test_parse_ukeire_ch_excel_detects_header_after_title_rows(tmp_path):
    # 先頭にタイトル行・切替日行があり、3行目に実ヘッダーがあるケース
    raw = pd.DataFrame(
        [
            ["納入便データ", "切替日: 2026年5月6日", None, None],
            [None, None, None, None],
            ["受入", "便名", "便No.", "到着時間"],
            ["CH", "日野プレス", "1", "07:30"],
            ["CH", "TMK", "03", "17:30"],
        ]
    )
    path = tmp_path / "title_rows.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        raw.to_excel(writer, sheet_name="全受入_納入便データ", index=False, header=False)

    out = parse_ukeire_ch_excel(path)

    assert len(out) == 2
    assert list(out["OData_納入先"]) == ["KVC", "日野"]
    assert list(out["NONYUHIBIN"]) == ["03", "01"]
    assert list(out["入車時間"]) == ["17:30", "07:30"]


def test_parse_ukeire_ch_excel_ignores_irrelevant_columns(tmp_path):
    src = pd.DataFrame(
        {
            "受入": ["CH"],
            "プラットNo.": ["P-01"],
            "便No.": ["05"],
            "便名": ["TMK"],
            "到着時刻": ["06:45"],
            "出発時刻": ["07:10"],
            "荷役時間(分)": [25],
        }
    )
    path = tmp_path / "ignore_extra_cols.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        src.to_excel(writer, sheet_name="全受入_納入便データ", index=False)

    out = parse_ukeire_ch_excel(path)

    assert len(out) == 1
    assert out.iloc[0]["OData_納入先"] == "KVC"
    assert out.iloc[0]["NONYUHIBIN"] == "05"
    assert out.iloc[0]["入車時間"] == "06:45"


def test_parse_ukeire_ch_excel_converts_requested_vendor_rules(tmp_path):
    src = pd.DataFrame(
        {
            "受入": ["CH", "CH", "CH", "CH", "CH"],
            "便名": ["6HN-TP", "6W-KVC", "6W-RH", "三栄本社", "織機成形"],
            "便No.": ["01", "02", "03", "04", "05"],
            "到着時刻": ["08:00", "08:30", "09:00", "10:00", "11:00"],
        }
    )
    path = tmp_path / "tp_rh.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        src.to_excel(writer, sheet_name="全受入_納入便データ", index=False)

    out = parse_ukeire_ch_excel(path)

    assert len(out) == 6
    recs = {
        (r["OData_納入先"], r["NONYUHIBIN"], r["入車時間"])
        for _, r in out.iterrows()
    }
    assert ("日野", "01", "08:00") in recs
    assert ("KVC", "02", "08:30") in recs
    assert ("元町", "03", "09:00") in recs
    assert ("高岡", "03", "09:00") in recs
    assert ("三栄", "04", "10:00") in recs
    assert ("織機", "05", "11:00") in recs
