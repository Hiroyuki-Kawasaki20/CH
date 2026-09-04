import json

import pandas as pd

from src.services.export_validator import (
    count_exported_kanban,
    count_kanban,
    verify_export_invariant,
)


def _row(yama, store, nonyuhibin, ukeire, dest="KVC", sebango=""):
    return {
        "山通番": yama, "ストア": store, "NONYUHIBIN": nonyuhibin,
        "UKEIRE": ukeire, "納入先": dest, "SEBANGO": sebango,
    }


def test_issue_129_missing_pallet_is_detected():
    display = pd.DataFrame([
        _row(1, "L12-C-5", "2026082806", "B7"),
        _row(1, "L12-D-8", "2026082806", "B7", sebango=720),
        _row(2, "C15-A-1", "2026082806", "B7", sebango=700),
        _row(3, "Q10-B-3", "2026090414", "07", dest="日野", sebango=439),
    ])
    export = display.iloc[[1, 2, 3]].copy()
    spo = pd.DataFrame({"グループ番号": [1, 2, 3], "GroupedData": [
        json.dumps([_row(1, "L12-D-8", "2026082806", "B7", sebango=720)]),
        json.dumps([_row(2, "C15-A-1", "2026082806", "B7", sebango=700)]),
        json.dumps([_row(3, "Q10-B-3", "2026090414", "07", dest="日野", sebango=439)]),
    ]})

    report = verify_export_invariant(display, export, spo, "GroupedData")

    assert report.is_lost is True
    assert report.gui_count == 4
    assert report.pipeline_count == 3
    assert sum(row["ストア"] == "L12-C-5" for row in report.missing_kanban) == 1


def test_normal_export_is_consistent():
    rows = pd.DataFrame([_row(1, "A", "1", "1"), _row(1, "B", "1", "1")])
    spo = pd.DataFrame({"グループ番号": [1], "GroupedData": [json.dumps(rows.to_dict("records"))]})
    report = verify_export_invariant(rows, rows, spo, "GroupedData")
    assert report.is_lost is False
    assert report.has_unexpanded is False


def test_merged_rows_count_as_pipeline_pallets():
    merged = [_row(1, "A", "1", "1"), _row(1, "B", "1", "1")]
    export = pd.DataFrame([{**merged[0], "_merged_rows": merged}])
    spo = pd.DataFrame({"グループ番号": [1], "GroupedData": [json.dumps(merged)]})
    report = verify_export_invariant(export, export, spo, "GroupedData")
    assert report.pipeline_count == 2
    assert report.is_lost is False


def test_unexpanded_merged_rows_are_reported():
    merged = [_row(1, "A", "1", "1"), _row(1, "B", "1", "1")]
    export = pd.DataFrame([{**merged[0], "_merged_rows": merged}])
    spo = pd.DataFrame({"グループ番号": [1], "GroupedData": [json.dumps([merged[0]])]})
    report = verify_export_invariant(export, export, spo, "GroupedData")
    assert report.has_unexpanded is True
    assert report.unexpanded_stores == ["A"]


def test_virtual_mountain_is_excluded():
    rows = pd.DataFrame([_row(-1, "virtual", "1", "1"), _row(1, "A", "1", "1")])
    assert count_kanban(rows) == 1
    assert count_kanban(rows.iloc[[0]]) == 0


def test_empty_and_none_are_zero():
    assert count_kanban(None) == 0
    assert count_kanban(pd.DataFrame()) == 0
    assert count_exported_kanban(None, "GroupedData") == 0
    assert count_exported_kanban(pd.DataFrame(), "GroupedData") == 0