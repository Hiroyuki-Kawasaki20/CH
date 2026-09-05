"""出力前のかんばん枚数不変条件を検証するサービス。"""


from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..models.constants import (
    BASE_ONE_TIME, BASE_PER_PAL, MIDDLE_WORK,
    SPO_EXPORT_REQUIRED_COLUMNS, VIRTUAL_YAMA_NO, is_virtual_yama,
)
from ..utils.normalizer import _normalize_dest_name, _normalize_ukeire, _ZEN2HAN_DIGIT_COLON


@dataclass
class SpoAuditFinding:
    title: str
    group_number: Any
    process: str
    check_name: str
    expected: Any
    actual: Any
    severity: str


@dataclass
class ExportInvariantReport:
    gui_count: int = 0
    pipeline_count: int = 0
    exported_count: int = 0
    missing_kanban: List[dict] = None
    unexpanded_stores: List[str] = None
    is_lost: bool = False
    has_unexplained_count_gap: bool = False
    explained_bundle_yamas: Dict[str, int] = None
    parse_failed_rows: List[Any] = None
    audit_findings: List[SpoAuditFinding] = None
    error: str = ""
    errors: List[str] = None
    is_unverifiable: bool = False

    def __post_init__(self):
        self.missing_kanban = list(self.missing_kanban or [])
        self.unexpanded_stores = list(self.unexpanded_stores or [])
        self.parse_failed_rows = list(self.parse_failed_rows or [])
        self.audit_findings = list(self.audit_findings or [])
        self.explained_bundle_yamas = dict(self.explained_bundle_yamas or {})
        self.errors = list(self.errors or [])
        if self.error and self.error not in self.errors:
            self.errors.append(self.error)
        self.error = "\n".join(self.errors)

    @property
    def has_unexpanded(self) -> bool:
        """旧API互換。未展開警告は原因不明の件数差だけを指す。"""
        return self.has_unexplained_count_gap

    def summary(self) -> str:
        flags = []
        if self.is_lost:
            flags.append("消失")
        if self.has_unexplained_count_gap:
            flags.append("束ね未展開")
        if self.audit_findings:
            flags.append("xlsx監査不整合")
        status = "・".join(flags) if flags else "正常"
        return f"{status}: GUI={self.gui_count}, pipeline={self.pipeline_count}, exported={self.exported_count}"


def _is_virtual(value: Any) -> bool:
    try:
        return is_virtual_yama(int(value))
    except (TypeError, ValueError):
        return value == VIRTUAL_YAMA_NO


def _is_merged_rows(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _is_missing_yama(value: Any) -> bool:
    """山通番が欠損（未設定/None/NaN/pd.NA/pd.NaT/空文字）かを判定する。"""
    if value is None:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def count_kanban(df: pd.DataFrame) -> int:
    """束ね元行を展開した実物かんばん枚数を数える。"""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    if "山通番" not in df.columns:
        return 0
    # 仮想山を除外してから、束ね元行の件数をベクトル化して合計する。
    work = df.loc[~df["山通番"].map(_is_virtual)]
    if work.empty:
        return 0
    if "_merged_rows" not in work.columns:
        return int(len(work))
    merged = work["_merged_rows"]
    return int(merged.map(lambda value: len(value) if _is_merged_rows(value) else 1).sum())


def _parse_json_items(value: Any) -> Tuple[List[dict], bool]:
    try:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)], True
        if isinstance(value, dict):
            return [value], True
        if value is None or pd.isna(value):
            return [], True
        decoded = json.loads(str(value))
        if isinstance(decoded, str):
            decoded = json.loads(decoded)
        if isinstance(decoded, dict):
            decoded = [decoded]
        if not isinstance(decoded, list):
            return [], False
        return [item for item in decoded if isinstance(item, dict)], True
    except (TypeError, ValueError, json.JSONDecodeError):
        return [], False


def _count_exported_details(spo_df: pd.DataFrame, json_column: str) -> Tuple[int, List[Any], Dict[Any, int]]:
    if spo_df is None or not isinstance(spo_df, pd.DataFrame) or spo_df.empty or json_column not in spo_df.columns:
        return 0, [], {}
    total = 0
    failed = []
    by_yama: Dict[Any, int] = {}
    for row_number, (_, row) in enumerate(spo_df.iterrows()):
        items, parsed = _parse_json_items(row.get(json_column))
        if not parsed:
            failed.append(row_number)
        count = len(items)
        total += count
        yama = row.get("グループ番号", row.get("山通番"))
        by_yama[yama] = by_yama.get(yama, 0) + count
    return total, failed, by_yama


def count_exported_kanban(spo_df: pd.DataFrame, json_column: str) -> int:
    """GroupedData JSON の全要素数を合計する。"""
    total, _, _ = _count_exported_details(spo_df, json_column)
    return total


def _audit_finding(row: Any, check_name: str, expected: Any, actual: Any, severity: str) -> SpoAuditFinding:
    return SpoAuditFinding(
        title=str(row.get("タイトル", "")),
        group_number=row.get("グループ番号", ""),
        process=str(row.get("工程", "")),
        check_name=check_name,
        expected=expected,
        actual=actual,
        severity=severity,
    )


def audit_spo_dataframe(spo_df: pd.DataFrame, audit_cost: bool = False) -> List[SpoAuditFinding]:
    """SPO xlsx 単体で D-1〜D-4 を検査する。

    ``パレット数`` と ``GroupedData`` は同じ出力元明細から作られるため、
    上流で両方が同時に欠けた場合（例: 束ね処理前の消失）は単体では検知できない。
    この場合は A（GUI表示）との突合が必要である。
    """
    findings: List[SpoAuditFinding] = []
    if spo_df is None or not isinstance(spo_df, pd.DataFrame) or spo_df.empty:
        return findings
    for _, row in spo_df.iterrows():
        if _is_virtual(row.get("グループ番号")):
            continue
        title = row.get("タイトル", "")
        group_number = row.get("グループ番号", "")
        process = str(row.get("工程", ""))
        grouped_items, grouped_ok = _parse_json_items(row.get("GroupedData"))
        groupdata_items, groupdata_ok = _parse_json_items(row.get("groupdata"))

        if not grouped_ok:
            findings.append(_audit_finding(row, "JSONパース(GroupedData)", "JSON配列", row.get("GroupedData"), "ERROR"))
        if not groupdata_ok:
            findings.append(_audit_finding(row, "JSONパース(groupdata)", "JSON配列", row.get("groupdata"), "ERROR"))

        try:
            pallet_count = int(row.get("パレット数"))
        except (TypeError, ValueError):
            pallet_count = None
        if pallet_count != len(grouped_items):
            findings.append(_audit_finding(row, "D-1 パレット数とGroupedData件数", pallet_count, len(grouped_items), "ERROR"))

        if len(groupdata_items) != len(grouped_items):
            findings.append(_audit_finding(row, "D-3 groupdataとGroupedData件数", len(grouped_items), len(groupdata_items), "ERROR"))

        numbers = [item.get("番号") for item in grouped_items]
        expected_numbers = list(range(1, len(grouped_items) + 1))
        if numbers != expected_numbers:
            findings.append(_audit_finding(row, "D-4 GroupedData番号連番", expected_numbers, numbers, "WARNING"))

        try:
            max_cost = float(row.get("Max移動工数"))
            expected_cost = round(
                max_cost + BASE_ONE_TIME
                + ((pallet_count - 1) * MIDDLE_WORK)
                + (pallet_count * BASE_PER_PAL),
            ) if pallet_count is not None else None
            actual_cost = int(row.get("引取工数"))
        except (TypeError, ValueError):
            expected_cost = None
            actual_cost = row.get("引取工数")
        if audit_cost and (expected_cost is None or not isinstance(actual_cost, (int, float)) or abs(actual_cost - expected_cost) > 1):
            findings.append(_audit_finding(row, "D-2 引取工数再計算", expected_cost, actual_cost, "WARNING"))
    return findings


def _bundle_signature(row: Any) -> tuple:
    return tuple(_norm(row.get(field, ""), field) for field in ("山通番", "NONYUHIBIN", "UKEIRE", "納入先"))


def _bundle_label(row: Any) -> str:
    return "/".join(str(row.get(field, "")).strip() for field in ("納入先", "NONYUHIBIN", "UKEIRE", "SEBANGO"))


def audit_clustered_rows(export_df: pd.DataFrame) -> List[SpoAuditFinding]:
    """クラスタ後の束ね属性を検査し、別便等の誤った束ねを D-5 で検出する。"""
    findings: List[SpoAuditFinding] = []
    if export_df is None or not isinstance(export_df, pd.DataFrame) or export_df.empty:
        return findings
    if "山通番" not in export_df.columns or "_merged_rows" not in export_df.columns:
        return findings
    for _, row in export_df.iterrows():
        merged = row.get("_merged_rows")
        if not _is_merged_rows(merged):
            continue
        malformed_rows = [item for item in merged if not isinstance(item, dict)]
        missing_yama = [
            item for item in merged
            if isinstance(item, dict) and (
                "山通番" not in item
                or _is_missing_yama(item.get("山通番"))
            )
        ]
        if malformed_rows:
            findings.append(SpoAuditFinding(
                title=str(row.get("タイトル", "")),
                group_number=row.get("山通番", ""),
                process=str(row.get("工程", "")),
                check_name="D-5 検証不能（束ね元行が不正）",
                expected="束ね元行はdict",
                actual=f"不正行数={len(malformed_rows)}",
                severity="ERROR",
            ))
        if missing_yama:
            findings.append(SpoAuditFinding(
                title=str(row.get("タイトル", "")),
                group_number=row.get("山通番", ""),
                process=str(row.get("工程", "")),
                check_name="D-5 検証不能（山通番欠落）",
                expected="全ての束ね元行に山通番",
                actual=f"欠落行数={len(missing_yama)}",
                severity="ERROR",
            ))
            continue
        valid_rows = [item for item in merged if isinstance(item, dict) and not _is_virtual(item.get("山通番"))]
        if not valid_rows:
            findings.append(SpoAuditFinding(
                title=str(row.get("タイトル", "")),
                group_number=row.get("山通番", ""),
                process=str(row.get("工程", "")),
                check_name="D-5 検証不能（実行行なし）",
                expected="仮想山以外の実行行",
                actual="0行",
                severity="ERROR",
            ))
            continue
        representative = valid_rows[0] if valid_rows else None
        signatures = {_bundle_signature(item) for item in valid_rows}
        if len(signatures) <= 1:
            continue
        if representative is None:
            continue
        for disappeared in valid_rows[1:]:
            if _bundle_signature(disappeared) == _bundle_signature(representative):
                continue
            findings.append(SpoAuditFinding(
                title=str(row.get("タイトル", "")),
                group_number=row.get("山通番", ""),
                process=str(row.get("工程", "")),
                check_name="D-5 誤った束ね（別パレットの消滅）",
                expected=f"代表行=山通番{representative.get('山通番', '')} {_bundle_label(representative)}",
                actual=f"消滅行=山通番{disappeared.get('山通番', '')} {_bundle_label(disappeared)} / STORE={row.get('ストア', '')}",
                severity="ERROR",
            ))
    return findings


def _norm(value: Any, field: str) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().translate(_ZEN2HAN_DIGIT_COLON)
    if field in {"山通番", "NONYUHIBIN", "SEBANGO"}:
        try:
            number = float(text)
            if number.is_integer():
                return str(int(number))
        except (TypeError, ValueError):
            pass
    if field == "納入先":
        return _normalize_dest_name(text)
    if field == "UKEIRE":
        return _normalize_ukeire(text)
    return text


def _row_key(row: Any) -> tuple:
    return tuple(_norm(row.get(field, ""), field) for field in (
        "山通番", "ストア", "NONYUHIBIN", "UKEIRE", "納入先", "SEBANGO"
    ))


def _expanded_rows(df: pd.DataFrame) -> List[dict]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    rows = []
    for row in df.to_dict(orient="records"):
        if _is_virtual(row.get("山通番")):
            continue
        merged = row.get("_merged_rows")
        if _is_merged_rows(merged):
            rows.extend(item for item in merged if isinstance(item, dict))
        else:
            rows.append(row)
    return [row for row in rows if not _is_virtual(row.get("山通番"))]


def verify_export_invariant(display_df, export_df, spo_df, json_column, audit_cost: bool = False) -> ExportInvariantReport:
    """GUI、パイプライン、SPO JSON の枚数を比較し、検証不能も fail-closed で報告する。"""
    try:
        if display_df is None and export_df is None:
            raise ValueError("GUI表示データとパイプラインデータがともにありません")
        if display_df is not None and (not isinstance(display_df, pd.DataFrame) or "山通番" not in display_df.columns):
            raise ValueError("GUI表示データに山通番列がありません")
        if export_df is not None and (not isinstance(export_df, pd.DataFrame) or "山通番" not in export_df.columns):
            raise ValueError("パイプラインデータに山通番列がありません")
        required_spo_columns = set(SPO_EXPORT_REQUIRED_COLUMNS)
        if spo_df is not None and not isinstance(spo_df, pd.DataFrame):
            raise ValueError("SPOデータがDataFrameではありません")
        if spo_df is not None:
            missing_spo_columns = sorted(required_spo_columns - set(spo_df.columns))
            if missing_spo_columns:
                raise ValueError(f"SPOデータに必須列がありません: {', '.join(missing_spo_columns)}")
            if json_column not in spo_df.columns:
                raise ValueError(f"SPOデータに{json_column}列がありません")
        gui_rows = _expanded_rows(display_df)
        pipeline_rows = _expanded_rows(export_df)
        gui_keys = {_row_key(row): row for row in gui_rows}
        pipeline_keys = {_row_key(row) for row in pipeline_rows}
        missing = [row for key, row in gui_keys.items() if key not in pipeline_keys]
        exported_count, parse_failed_rows, exported_by_yama = _count_exported_details(spo_df, json_column)

        unexpanded = set()
        unexplained_unexpanded_yamas = set()
        explained_bundle_yamas = {}
        explained_unexpanded_yamas = set()
        if export_df is not None and isinstance(export_df, pd.DataFrame) and not export_df.empty:
            expected_by_yama = {}
            for row in pipeline_rows:
                yama = row.get("山通番")
                expected_by_yama[yama] = expected_by_yama.get(yama, 0) + 1
            for _, row in export_df.iterrows():
                yama = row.get("山通番")
                if _is_virtual(yama) or not _is_merged_rows(row.get("_merged_rows")):
                    continue
                if exported_by_yama.get(yama, 0) != expected_by_yama.get(yama, 0):
                    merged_rows = row.get("_merged_rows")
                    signatures = {
                        _bundle_signature(item) for item in merged_rows
                        if isinstance(item, dict)
                    } if _is_merged_rows(merged_rows) else set()
                    if len(signatures) == 1:
                        explained_bundle_yamas[_norm(yama, "山通番")] = (
                            expected_by_yama.get(yama, 0) - exported_by_yama.get(yama, 0)
                        )
                        continue
                    unexplained_unexpanded_yamas.add(_norm(yama, "山通番"))
                    store = row.get("ストア", row.get("SYUKKASAKI", ""))
                    unexpanded.add(str(store).strip())
            for yama, expected_count in expected_by_yama.items():
                if exported_by_yama.get(yama, 0) != expected_count:
                    yama_key = _norm(yama, "山通番")
                    if yama_key not in explained_bundle_yamas:
                        unexplained_unexpanded_yamas.add(yama_key)

        audit_findings = audit_spo_dataframe(spo_df, audit_cost=audit_cost)
        audit_findings.extend(audit_clustered_rows(export_df))
        report = ExportInvariantReport(
            gui_count=count_kanban(display_df),
            pipeline_count=count_kanban(export_df),
            exported_count=exported_count,
            missing_kanban=missing,
            unexpanded_stores=sorted(unexpanded),
            parse_failed_rows=parse_failed_rows,
            audit_findings=audit_findings,
            explained_bundle_yamas=explained_bundle_yamas,
        )
        d5_findings = [finding for finding in audit_findings if finding.check_name.startswith("D-5")]
        report.is_lost = (
            report.gui_count != report.pipeline_count
            or bool(report.missing_kanban)
            or bool(d5_findings)
            or any(finding.severity == "ERROR" and finding.check_name.startswith(("D-1", "D-3", "JSON"))
                   for finding in audit_findings)
        )
        report.is_unverifiable = bool(report.parse_failed_rows)
        report_reasons = []
        if report.is_unverifiable:
            report_reasons.append(f"GroupedData JSONのパースに失敗した行があります: {report.parse_failed_rows}")
        report.has_unexplained_count_gap = bool(unexplained_unexpanded_yamas)
        unverifiable_findings = [
            finding for finding in audit_findings
            if finding.check_name.startswith("D-5 検証不能")
        ]
        if unverifiable_findings:
            report.is_unverifiable = True
            report_reasons.extend(
                f"{finding.check_name}: {finding.actual}"
                for finding in unverifiable_findings
            )
        report.errors = report_reasons
        report.error = "\n".join(report_reasons)
        return report
    except Exception as error:
        return ExportInvariantReport(
            error=str(error),
            is_unverifiable=True,
            is_lost=True,
        )


def report_as_dict(report: ExportInvariantReport) -> dict:
    """アーカイブ用にレポートを JSON 化できる辞書へ変換する。"""
    return asdict(report)
