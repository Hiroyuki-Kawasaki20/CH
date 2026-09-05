"""SPO履歴xlsxを読み取り専用で一括監査するCLI。"""

import argparse
from collections import Counter
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.export_validator import SpoAuditFinding, audit_spo_dataframe
from src.models.constants import LOCAL_OUTPUT_DIR


def _default_history_path() -> Path:
    return Path(LOCAL_OUTPUT_DIR) / "SPOアップロード用_履歴.xlsx"


def _finding_row(finding: SpoAuditFinding) -> dict:
    return {
        "タイトル": finding.title,
        "グループ番号": finding.group_number,
        "工程": finding.process,
        "検査名": finding.check_name,
        "期待値": finding.expected,
        "実測値": finding.actual,
        "重大度": finding.severity,
    }


def audit_history(input_path: Path, csv_path: Path) -> int:
    """履歴を読むだけで監査し、findingを標準出力とCSVへ出力する。"""
    history = pd.read_excel(input_path, engine="openpyxl")
    required = {"タイトル", "工程", "groupdata", "GroupedData", "パレット数", "グループ番号"}
    missing = sorted(required - set(history.columns))
    if missing:
        print(f"必須列不足のため監査を中止します: {', '.join(missing)}", file=sys.stderr)
        return 2
    findings = audit_spo_dataframe(history)
    finding_rows = [_finding_row(finding) for finding in findings]

    duplicate_keys = []
    if "更新日時" in history.columns and "グループ番号" in history.columns:
        dates = pd.to_datetime(history["更新日時"], errors="coerce").dt.date
        keys = list(zip(dates, history["グループ番号"]))
        duplicate_keys = [key for key, count in Counter(keys).items() if pd.notna(key[0]) and count > 1]
    for key in duplicate_keys:
        print(f"再出力候補: 日付={key[0]} グループ番号={key[1]}")

    print(f"監査対象: {input_path}")
    print(f"行数: {len(history)}, findings: {len(findings)}")
    for finding in findings:
        print(
            f"[{finding.severity}] {finding.title}（山通番{finding.group_number}）/ "
            f"{finding.check_name}: 期待={finding.expected}, 実測={finding.actual}"
        )
    pd.DataFrame(finding_rows, columns=["タイトル", "グループ番号", "工程", "検査名", "期待値", "実測値", "重大度"]).to_csv(
        csv_path, index=False, encoding="utf-8-sig"
    )
    print(f"CSV: {csv_path}")
    return 1 if findings else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SPO履歴xlsxの自己整合監査")
    parser.add_argument("xlsx", nargs="?", type=Path, default=_default_history_path())
    parser.add_argument("--csv", type=Path, default=None, help="監査結果CSVの出力先")
    args = parser.parse_args(argv)
    csv_path = args.csv or args.xlsx.with_name(f"{args.xlsx.stem}_audit.csv")
    try:
        return audit_history(args.xlsx, csv_path)
    except Exception as error:
        print(f"監査エラー: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())