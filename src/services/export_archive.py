"""SPO 出力と入力データの調査用アーカイブ。"""

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Iterable, Optional

import pandas as pd

from .export_validator import ExportInvariantReport
from ..models.constants import is_virtual_yama


def resolve_archive_dir(export_dir: str, configured_dir: str = "", local_output_dir: str = "") -> str:
    """既定ではSPO監視フォルダ外のローカル出力先配下へ保存する。"""
    if configured_dir:
        return str(Path(configured_dir))
    root = Path(local_output_dir) if local_output_dir else Path(export_dir).resolve().parent
    return str(root / "_export_archive")


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"保存先が空いていません: {path}")


def _input_metadata(paths: Iterable[Path]) -> list:
    metadata = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        stat = path.stat()
        metadata.append({
            "パス": str(path),
            "最終更新日時": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "サイズ": stat.st_size,
        })
    return metadata


def _counts_by_mountain(export_df: pd.DataFrame) -> dict:
    counts = {}
    if export_df is None or not isinstance(export_df, pd.DataFrame) or export_df.empty:
        return counts
    for row in export_df.to_dict(orient="records"):
        try:
            yama = int(row.get("山通番"))
        except (TypeError, ValueError):
            continue
        if is_virtual_yama(yama):
            continue
        merged = row.get("_merged_rows")
        counts[str(yama)] = counts.get(str(yama), 0) + (len(merged) if isinstance(merged, list) and merged else 1)
    return counts


def archive_export(
    output_path: Optional[str] = None,
    input_paths: Iterable[Path] = (),
    export_df: Optional[pd.DataFrame] = None,
    report: Optional[ExportInvariantReport] = None,
    settings_snapshot: Optional[dict] = None,
    archive_dir: str = "",
    result: str = "出力",
) -> Optional[str]:
    """出力成功後にファイルと検証結果を保存する。呼び出し側で例外を捕捉する。"""
    report = report or ExportInvariantReport()
    settings_snapshot = settings_snapshot or {}
    root = Path(archive_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = root / timestamp
    if folder.exists():
        for index in range(1, 1000):
            candidate = root / f"{timestamp}_{index:02d}"
            if not candidate.exists():
                folder = candidate
                break
    folder.mkdir(parents=True, exist_ok=False)

    copied_output = None
    if output_path:
        copied_output = _unique_path(folder / Path(output_path).name)
        shutil.copy2(output_path, copied_output)
    copied_inputs = []
    for raw_path in input_paths:
        source = Path(raw_path)
        if not source.exists() or not source.is_file():
            continue
        destination = _unique_path(folder / source.name)
        shutil.copy2(source, destination)
        copied_inputs.append(str(destination))

    manifest = {
        "出力日時": datetime.now().isoformat(timespec="seconds"),
        "結果": result,
        "出力ファイル名": copied_output.name if copied_output else "",
        "A_gui_count": report.gui_count,
        "B_pipeline_count": report.pipeline_count,
        "C_exported_count": report.exported_count,
        "山通番ごとのかんばん枚数": _counts_by_mountain(export_df),
        "入力ファイル": _input_metadata(input_paths),
        "アーカイブ内入力ファイル": copied_inputs,
        "ExportInvariantReport": asdict(report),
        "設定値スナップショット": settings_snapshot,
    }
    with (folder / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2, default=str)
    return str(folder)