import json

import pandas as pd

from src.services.export_validator import (
    count_exported_kanban,
    count_kanban,
    verify_export_invariant,
    audit_clustered_rows,
)
from src.services.exporter import build_spo_export_df


def _row(yama, store, nonyuhibin, ukeire, dest="KVC", sebango=""):
    return {
        "山通番": yama, "ストア": store, "NONYUHIBIN": nonyuhibin,
        "UKEIRE": ukeire, "納入先": dest, "SEBANGO": sebango,
    }

def _spo(rows, group_numbers):
    encoded = [json.dumps([row]) for row in rows]
    return pd.DataFrame({
        "タイトル": [f"山{i + 1}" for i in range(len(rows))],
        "工程": ["1工程"] * len(rows),
        "groupdata": encoded,
        "GroupedData": encoded,
        "グループ番号": group_numbers,
        "パレット数": [1] * len(rows),
        "Max移動工数": [0.0] * len(rows),
        "引取工数": [0] * len(rows),
    })


def test_issue_129_missing_pallet_is_detected():
    display = pd.DataFrame([
        _row(1, "L12-C-5", "2026082806", "B7"),
        _row(1, "L12-D-8", "2026082806", "B7", sebango=720),
        _row(2, "C15-A-1", "2026082806", "B7", sebango=700),
        _row(3, "Q10-B-3", "2026090414", "07", dest="日野", sebango=439),
    ])
    export = display.iloc[[1, 2, 3]].copy()
    spo = _spo(export.to_dict("records"), [1, 2, 3])

    report = verify_export_invariant(display, export, spo, "GroupedData")

    assert report.is_lost is True
    assert report.gui_count == 4
    assert report.pipeline_count == 3
    assert sum(row["ストア"] == "L12-C-5" for row in report.missing_kanban) == 1


def test_normal_export_is_consistent():
    rows = pd.DataFrame([_row(1, "A", "1", "1"), _row(1, "B", "1", "1")])
    items = rows.to_dict("records")
    spo = pd.DataFrame({
        "タイトル": ["山1"], "工程": ["1工程"],
        "groupdata": [json.dumps(items)], "GroupedData": [json.dumps(items)],
        "グループ番号": [1], "パレット数": [2], "Max移動工数": [0.0], "引取工数": [0],
    })
    report = verify_export_invariant(rows, rows, spo, "GroupedData")
    assert report.is_lost is False
    assert report.has_unexpanded is False


def test_merged_rows_count_as_pipeline_pallets():
    merged = [_row(1, "A", "1", "1"), _row(1, "B", "1", "1")]
    export = pd.DataFrame([{**merged[0], "_merged_rows": merged}])
    spo = _spo([merged[0]], [1])
    spo.loc[0, "groupdata"] = json.dumps(merged)
    spo.loc[0, "GroupedData"] = json.dumps(merged)
    spo.loc[0, "パレット数"] = 2
    report = verify_export_invariant(export, export, spo, "GroupedData")
    assert report.pipeline_count == 2
    assert report.is_lost is False


def test_valid_merged_rows_are_not_unexpanded():
    merged = [_row(1, "A", "1", "1"), _row(1, "B", "1", "1")]
    export = pd.DataFrame([{**merged[0], "_merged_rows": merged}])
    spo = _spo([merged[0]], [1])
    report = verify_export_invariant(export, export, spo, "GroupedData")
    assert report.has_unexpanded is False
    assert report.explained_bundle_yamas == {"1": 1}
    assert report.unexpanded_stores == []


def test_virtual_mountain_is_excluded():
    rows = pd.DataFrame([_row(-1, "virtual", "1", "1"), _row(1, "A", "1", "1")])
    assert count_kanban(rows) == 1
    assert count_kanban(rows.iloc[[0]]) == 0


def test_empty_and_none_are_zero():
    assert count_kanban(None) == 0
    assert count_kanban(pd.DataFrame()) == 0
    assert count_exported_kanban(None, "GroupedData") == 0
    assert count_exported_kanban(pd.DataFrame(), "GroupedData") == 0


def test_attribution_mismatch_is_lost_even_when_counts_match():
    display = pd.DataFrame([_row(1, "A", "1", "1"), _row(2, "B", "1", "1")])
    export = display.copy()
    export.loc[1, "山通番"] = 3
    spo = _spo(export.to_dict("records"), [1, 3])
    report = verify_export_invariant(display, export, spo, "GroupedData")
    assert report.gui_count == report.pipeline_count == 2
    assert report.is_lost is True
    assert report.missing_kanban


def test_numeric_dtype_difference_does_not_create_missing_row():
    display = pd.DataFrame([_row(1, "A", "1", "1", sebango=720)])
    export = display.copy()
    export["山通番"] = export["山通番"].astype(float)
    export["SEBANGO"] = export["SEBANGO"].astype(float)
    spo = _spo(export.to_dict("records"), [1])
    report = verify_export_invariant(display, export, spo, "GroupedData")
    assert report.missing_kanban == []


def test_missing_required_spo_columns_is_unverifiable():
    rows = pd.DataFrame([_row(1, "A", "1", "1")])
    report = verify_export_invariant(rows, rows, pd.DataFrame({"GroupedData": ["[]"]}), "GroupedData")
    assert report.is_unverifiable is True
    assert report.is_lost is True


def test_both_input_frames_none_are_unverifiable():
    report = verify_export_invariant(None, None, None, "GroupedData")
    assert report.is_unverifiable is True
    assert report.is_lost is True


def test_missing_yama_in_merged_rows_is_unverifiable():
    merged = [_row(1, "A", "1", "1"), _row(1, "B", "1", "1")]
    for item in merged:
        item.pop("山通番")
    export = pd.DataFrame([{"山通番": 1, "ストア": "A", "_merged_rows": merged}])
    findings = audit_clustered_rows(export)
    assert findings[0].check_name == "D-5 検証不能（山通番欠落）"
    assert findings[0].severity == "ERROR"
    spo = _spo([{"山通番": 1, "ストア": "A"}], [1])
    report = verify_export_invariant(export, export, spo, "GroupedData")
    assert report.is_unverifiable is True
    assert report.is_lost is True


def test_verify_real_build_spo_export_output_is_verifiable():
    details = pd.DataFrame([
        {"山通番": 1, "移動工数": 10.0, "高さ": 100, "ストア": "A", "納入先": "KVC",
         "NONYUHIBIN": "1", "UKEIRE": "1", "SEBANGO": "1", "工程内No": 1,
         "サイズ種類": "1"},
        {"山通番": 1, "移動工数": 20.0, "高さ": 100, "ストア": "B", "納入先": "KVC",
         "NONYUHIBIN": "1", "UKEIRE": "1", "SEBANGO": "2", "工程内No": 2,
         "サイズ種類": "1"},
    ])
    spo = build_spo_export_df(details, {1: "メイン"}, {1: "08:00"})
    report = verify_export_invariant(details, details, spo, "GroupedData")
    assert report.is_unverifiable is False
    assert report.is_lost is False
