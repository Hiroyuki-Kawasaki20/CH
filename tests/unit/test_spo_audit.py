import hashlib
import json
from pathlib import Path

import pandas as pd

from src.models.constants import BASE_ONE_TIME, BASE_PER_PAL, MIDDLE_WORK
from src.services.export_validator import audit_spo_dataframe, verify_export_invariant
from tools.audit_spo_history import audit_history


def _items(count=4, start=719):
    return [{"番号": index, "SEBANGO": start + index - 1} for index in range(1, count + 1)]


def _spo_row(items, pallets=4, max_cost=313.7402, cost=719, title="山2"):
    encoded = json.dumps(items, ensure_ascii=False)
    return {
        "タイトル": title,
        "工程": "1工程",
        "groupdata": encoded,
        "GroupedData": encoded,
        "Max移動工数": max_cost,
        "グループ番号": 1,
        "パレット数": pallets,
        "引取工数": cost,
    }


def test_audit_measured_normal_row_has_no_findings():
    assert audit_spo_dataframe(pd.DataFrame([_spo_row(_items())])) == []


def test_audit_detects_issue129_json_missing_item_as_d1():
    row = _spo_row(_items(3), pallets=4, cost=719)
    findings = audit_spo_dataframe(pd.DataFrame([row]))
    assert any(finding.check_name.startswith("D-1") for finding in findings)
    report = verify_export_invariant(pd.DataFrame(), pd.DataFrame(), pd.DataFrame([row]), "GroupedData")
    assert report.is_lost is True


def test_audit_cannot_detect_upstream_loss_without_gui_count():
    cost = round(313.7402 + BASE_ONE_TIME + (2 * MIDDLE_WORK) + (3 * BASE_PER_PAL))
    row = _spo_row(_items(3), pallets=3, cost=cost)
    findings = audit_spo_dataframe(pd.DataFrame([row]))
    assert not any(finding.check_name.startswith("D-1") for finding in findings)
    assert not any(finding.check_name.startswith("D-2") for finding in findings)
    assert not any(finding.check_name.startswith("D-4") for finding in findings)
    assert "上流で両方が同時に欠けた場合" in audit_spo_dataframe.__doc__


def test_audit_reports_json_parse_error():
    row = _spo_row(_items())
    row["GroupedData"] = "{not-json"
    findings = audit_spo_dataframe(pd.DataFrame([row]))
    assert any("JSONパース(GroupedData)" == finding.check_name for finding in findings)


def test_audit_reports_groupdata_mismatch_and_nonsequential_numbers():
    row = _spo_row(_items())
    row["groupdata"] = json.dumps(_items(3))
    row["GroupedData"] = json.dumps([{"番号": 1}, {"番号": 3}, {"番号": 4}, {"番号": 5}])
    findings = audit_spo_dataframe(pd.DataFrame([row]))
    assert any(finding.check_name.startswith("D-3") for finding in findings)
    assert any(finding.check_name.startswith("D-4") for finding in findings)


def test_history_cli_does_not_modify_xlsx(tmp_path):
    xlsx_path = tmp_path / "history.xlsx"
    csv_path = tmp_path / "audit.csv"
    pd.DataFrame([_spo_row(_items(3), pallets=4, cost=719)]).to_excel(xlsx_path, index=False)
    before = hashlib.sha256(xlsx_path.read_bytes()).digest()

    exit_code = audit_history(xlsx_path, csv_path)

    assert exit_code == 1
    assert csv_path.exists()
    assert hashlib.sha256(xlsx_path.read_bytes()).digest() == before


def test_history_cli_rejects_missing_required_columns(tmp_path):
    xlsx_path = tmp_path / "incomplete.xlsx"
    csv_path = tmp_path / "audit.csv"
    pd.DataFrame({"GroupedData": ["[]"]}).to_excel(xlsx_path, index=False)
    assert audit_history(xlsx_path, csv_path) == 2
    assert not csv_path.exists()
