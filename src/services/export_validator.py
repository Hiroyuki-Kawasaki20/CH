"""出力前のかんばん枚数不変条件を検証するサービス。"""

from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Tuple

import pandas as pd

from ..models.constants import VIRTUAL_YAMA_NO, is_virtual_yama
from ..utils.normalizer import _normalize_dest_name, _normalize_ukeire, _ZEN2HAN_DIGIT_COLON


@dataclass
class ExportInvariantReport:
    gui_count: int = 0
    pipeline_count: int = 0
    exported_count: int = 0
    missing_kanban: List[dict] = None
    unexpanded_stores: List[str] = None
    is_lost: bool = False
    has_unexpanded: bool = False
    parse_failed_rows: List[Any] = None

    def __post_init__(self):
        self.missing_kanban = list(self.missing_kanban or [])
        self.unexpanded_stores = list(self.unexpanded_stores or [])
        self.parse_failed_rows = list(self.parse_failed_rows or [])

    def summary(self) -> str:
        flags = []
        if self.is_lost:
            flags.append("消失")
        if self.has_unexpanded:
            flags.append("束ね未展開")
        status = "・".join(flags) if flags else "正常"
        return f"{status}: GUI={self.gui_count}, pipeline={self.pipeline_count}, exported={self.exported_count}"


def _is_virtual(value: Any) -> bool:
    try:
        return is_virtual_yama(int(value))
    except (TypeError, ValueError):
        return value == VIRTUAL_YAMA_NO


def _is_merged_rows(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


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


def _norm(value: Any, field: str) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().translate(_ZEN2HAN_DIGIT_COLON)
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


def verify_export_invariant(display_df, export_df, spo_df, json_column) -> ExportInvariantReport:
    """GUI、パイプライン、SPO JSON の枚数を比較し、例外を外へ出さず報告する。"""
    try:
        gui_rows = _expanded_rows(display_df)
        pipeline_rows = _expanded_rows(export_df)
        gui_keys = {_row_key(row): row for row in gui_rows}
        pipeline_keys = {_row_key(row) for row in pipeline_rows}
        missing = [row for key, row in gui_keys.items() if key not in pipeline_keys]
        exported_count, parse_failed_rows, exported_by_yama = _count_exported_details(spo_df, json_column)

        unexpanded = set()
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
                    store = row.get("ストア", row.get("SYUKKASAKI", ""))
                    unexpanded.add(str(store).strip())

        report = ExportInvariantReport(
            gui_count=count_kanban(display_df),
            pipeline_count=count_kanban(export_df),
            exported_count=exported_count,
            missing_kanban=missing,
            unexpanded_stores=sorted(unexpanded),
            parse_failed_rows=parse_failed_rows,
        )
        report.is_lost = report.gui_count != report.pipeline_count
        report.has_unexpanded = report.pipeline_count != report.exported_count
        return report
    except Exception:
        return ExportInvariantReport()


def report_as_dict(report: ExportInvariantReport) -> dict:
    """アーカイブ用にレポートを JSON 化できる辞書へ変換する。"""
    return asdict(report)