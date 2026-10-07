# -*- coding: utf-8 -*-
"""GroupedData の各パレットに入車時間を書き込む（attach_entry_time_to_groupeddata）。"""
import json

import pandas as pd

from src.services.exporter import attach_entry_time_to_groupeddata


def _item(vendor, nony, ukeire=""):
    return {
        "OData__x30b9__x30c8__x30a2_": "ST1",
        "NONYUHIBIN": nony,
        "UKEIRE": ukeire,
        "OData__x7d0d__x5165__x5148_": vendor,
        "SEBANGO": "A001",
        "番号": 1,
        "引取済": "",
    }


def _spo(*rows_of_items):
    gd = [json.dumps(items, ensure_ascii=False) for items in rows_of_items]
    return pd.DataFrame({
        "groupdata": gd,
        "GroupedData": gd,
        "引取開始時間": ["08:00"] * len(gd),
    })


def _master(*rows):
    return pd.DataFrame(rows, columns=["OData_納入先", "NONYUHIBIN", "入車時間"])


def _times(out, row=0):
    return [it["入車時間"] for it in json.loads(out.at[row, "GroupedData"])]


def test_plain_vendor_gets_entry_time():
    """通常の便: 納入先と便番号(末尾2桁)でマスタを引く。"""
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201")]),
        _master(("日野", "01", "06:45")),
    )
    assert _times(out) == ["06:45"]


def test_split_ukeire_uses_vendor_ukeire_key():
    """KVC・元町・織機は「納入先-受入」の行を引く（元町-PK を含む）。"""
    out = attach_entry_time_to_groupeddata(
        _spo([
            _item("KVC", "2026100201", "B7"),
            _item("KVC", "2026100201", "B3"),
            _item("元町", "2026100201", "PK"),
        ]),
        _master(
            ("KVC-B7", "01", "18:46"),
            ("KVC-B3", "01", "18:50"),
            ("元町-PK", "01", "10:00"),
        ),
    )
    assert _times(out) == ["18:46", "18:50", "10:00"]


def test_midnight_time_uses_24h_notation():
    """00:09 は引取開始時間と同じく 24:09 で出す。"""
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201")]),
        _master(("日野", "01", "00:09")),
    )
    assert _times(out) == ["24:09"]


def test_unmatched_pallet_gets_empty_string_and_row_is_kept():
    """マスタに無い便は空文字。パレットも行も消さない。"""
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201"), _item("日野", "2026100209")]),
        _master(("日野", "01", "06:45")),
    )
    assert len(out) == 1
    assert _times(out) == ["06:45", ""]


def test_mixed_yama_each_pallet_gets_its_own_time():
    """混載の山: 便ごとに別々の時刻が付く。"""
    out = attach_entry_time_to_groupeddata(
        _spo([
            _item("日野", "2026100213"),
            _item("高岡", "2026100204"),
            _item("KVC", "2026100205", "B7"),
        ]),
        _master(
            ("日野", "13", "07:00"),
            ("高岡", "04", "07:00"),
            ("KVC-B7", "05", "07:30"),
        ),
    )
    assert _times(out) == ["07:00", "07:00", "07:30"]


def test_groupdata_and_groupeddata_stay_identical():
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201")]),
        _master(("日野", "01", "06:45")),
    )
    assert out.at[0, "groupdata"] == out.at[0, "GroupedData"]


def test_existing_keys_and_other_columns_are_kept():
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201")]),
        _master(("日野", "01", "06:45")),
    )
    item = json.loads(out.at[0, "GroupedData"])[0]
    assert item["番号"] == 1
    assert item["SEBANGO"] == "A001"
    assert list(item.keys())[-1] == "入車時間"      # 既存キーの後ろに足す
    assert out["引取開始時間"].tolist() == ["08:00"]  # 引取開始時間には触らない


def test_second_call_is_idempotent():
    spo = _spo([_item("日野", "2026100201")])
    master = _master(("日野", "01", "06:45"))
    once = attach_entry_time_to_groupeddata(spo, master)
    twice = attach_entry_time_to_groupeddata(once, master)
    pd.testing.assert_frame_equal(once, twice)


def test_empty_master_adds_empty_entry_time_and_does_not_raise():
    out = attach_entry_time_to_groupeddata(
        _spo([_item("日野", "2026100201")]),
        pd.DataFrame(),
    )
    assert _times(out) == [""]


def test_unparsable_groupeddata_is_left_as_is():
    spo = pd.DataFrame({
        "groupdata": ["not json"],
        "GroupedData": ["not json"],
        "引取開始時間": ["08:00"],
    })
    out = attach_entry_time_to_groupeddata(spo, _master(("日野", "01", "06:45")))
    assert out.at[0, "GroupedData"] == "not json"
    assert out.at[0, "groupdata"] == "not json"


def test_input_dataframe_is_not_modified():
    spo = _spo([_item("日野", "2026100201")])
    before = spo.copy(deep=True)
    attach_entry_time_to_groupeddata(spo, _master(("日野", "01", "06:45")))
    pd.testing.assert_frame_equal(spo, before)