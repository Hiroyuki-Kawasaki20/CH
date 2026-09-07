from __future__ import annotations

import builtins
from pathlib import Path

import pandas as pd
import pytest

from src.services import data_loader
from src.services.data_loader import (
    MASTER_COLUMNS,
    MASTER_FILENAME,
    MasterFileError,
    MasterFileLockedError,
    MasterFileReadError,
    _resolve_master_path,
    _resolve_master_path_candidates,
    load_pickup_time_master_xlsx,
    save_pickup_time_master_xlsx,
)


def _master_df(value: str = "08:30") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "OData_納入先": "テスト納入先",
                "NONYUHIBIN": "01",
                "入車時間": value,
                "セットありフラグ": "1",
            }
        ]
    )


def test_candidates_default_to_legacy_only(tmp_path: Path):
    legacy = tmp_path / MASTER_FILENAME

    assert _resolve_master_path_candidates({}, legacy) == [legacy]


def test_candidates_accept_master_path_file(tmp_path: Path):
    configured = tmp_path / "custom.xlsx"
    legacy = tmp_path / "legacy" / MASTER_FILENAME

    assert _resolve_master_path_candidates({"master_path": str(configured)}, legacy) == [configured, legacy]


def test_candidates_accept_master_path_folder(tmp_path: Path):
    folder = tmp_path / "spo"
    legacy = tmp_path / "legacy" / MASTER_FILENAME


    assert _resolve_master_path_candidates({"master_path": str(folder)}, legacy) == [folder / MASTER_FILENAME, legacy]


def test_candidates_use_base_dir_second(tmp_path: Path):
    base_dir = tmp_path / "base"
    legacy = tmp_path / "legacy" / MASTER_FILENAME

    assert _resolve_master_path_candidates({"base_dir": str(base_dir)}, legacy) == [base_dir / MASTER_FILENAME, legacy]


def test_candidates_are_deduplicated(tmp_path: Path):
    base_dir = tmp_path / "base"
    legacy = tmp_path / "legacy" / MASTER_FILENAME


    assert _resolve_master_path_candidates(
        {"master_path": str(base_dir / MASTER_FILENAME), "base_dir": str(base_dir)}, legacy
    ) == [base_dir / MASTER_FILENAME, legacy]


def test_resolve_existing_master_path_wins_over_base_and_legacy(tmp_path: Path):
    master_dir = tmp_path / "master"
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    for folder in (master_dir, base_dir, legacy_dir):
        folder.mkdir()
        (folder / MASTER_FILENAME).write_text("dummy", encoding="utf-8")

    result = _resolve_master_path(
        {"master_path": str(master_dir), "base_dir": str(base_dir)},
        legacy_dir / MASTER_FILENAME,
    )

    assert result == master_dir / MASTER_FILENAME


def test_resolve_base_dir_wins_when_master_path_missing(tmp_path: Path):
    master_dir = tmp_path / "master"
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    master_dir.mkdir()
    base_dir.mkdir()
    legacy_dir.mkdir()
    (base_dir / MASTER_FILENAME).write_text("dummy", encoding="utf-8")
    (legacy_dir / MASTER_FILENAME).write_text("dummy", encoding="utf-8")

    result = _resolve_master_path(
        {"master_path": str(master_dir), "base_dir": str(base_dir)},
        legacy_dir / MASTER_FILENAME,
    )

    assert result == base_dir / MASTER_FILENAME


def test_resolve_legacy_when_only_legacy_exists(tmp_path: Path):
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    base_dir.mkdir()
    legacy_dir.mkdir()
    legacy = legacy_dir / MASTER_FILENAME
    legacy.write_text("dummy", encoding="utf-8")

    assert _resolve_master_path({"base_dir": str(base_dir)}, legacy) == legacy


def test_resolve_returns_first_accessible_parent_as_new_file(tmp_path: Path):
    master_dir = tmp_path / "master"
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    for folder in (master_dir, base_dir, legacy_dir):
        folder.mkdir()

    result = _resolve_master_path(
        {"master_path": str(master_dir), "base_dir": str(base_dir)},
        legacy_dir / MASTER_FILENAME,
    )

    assert result == master_dir / MASTER_FILENAME
    assert not result.exists()


def test_resolve_falls_back_to_legacy_when_configured_parent_is_missing(tmp_path: Path):
    missing_base = tmp_path / "missing"
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy = legacy_dir / MASTER_FILENAME

    assert _resolve_master_path({"base_dir": str(missing_base)}, legacy) == legacy


def test_resolve_falls_back_to_legacy_when_no_parent_is_accessible(tmp_path: Path):
    missing_master = tmp_path / "missing-master" / MASTER_FILENAME
    missing_base = tmp_path / "missing-base"
    legacy = tmp_path / "missing-legacy" / MASTER_FILENAME

    result = _resolve_master_path(
        {"master_path": str(missing_master), "base_dir": str(missing_base)},
        legacy,
    )

    assert result == legacy


def test_resolve_skips_exists_oserror_and_uses_next_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    master_dir = tmp_path / "master"
    base_dir = tmp_path / "base"
    master_dir.mkdir()
    base_dir.mkdir()
    master_path = master_dir / MASTER_FILENAME
    base_path = base_dir / MASTER_FILENAME
    base_path.write_text("dummy", encoding="utf-8")
    original_exists = Path.exists

    def exists_with_error(path: Path) -> bool:
        if path == master_path:
            raise OSError("network unavailable")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists_with_error)

    assert _resolve_master_path({"master_path": str(master_dir), "base_dir": str(base_dir)}, tmp_path / "legacy.xlsx") == base_path


def test_resolve_skips_parent_is_dir_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    master_dir = tmp_path / "master"
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    for folder in (master_dir, base_dir, legacy_dir):
        folder.mkdir()
    master_path = master_dir / MASTER_FILENAME
    original_is_dir = Path.is_dir

    def is_dir_with_error(path: Path) -> bool:
        if path == master_path.parent:
            raise OSError("network unavailable")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir_with_error)

    assert _resolve_master_path({"master_path": str(master_dir), "base_dir": str(base_dir)}, legacy_dir / MASTER_FILENAME) == base_dir / MASTER_FILENAME


def test_read_and_write_use_same_resolved_path(tmp_path: Path):
    base_dir = tmp_path / "base"
    legacy_dir = tmp_path / "legacy"
    base_dir.mkdir()
    legacy_dir.mkdir()
    master_path = _resolve_master_path({"base_dir": str(base_dir)}, legacy_dir / MASTER_FILENAME)

    save_pickup_time_master_xlsx(_master_df("09:15"), master_path)
    loaded = load_pickup_time_master_xlsx(master_path)

    assert master_path == base_dir / MASTER_FILENAME
    assert loaded.loc[0, "入車時間"] == "09:15"


def test_save_locked_rescues_and_does_not_touch_existing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    master_path = tmp_path / MASTER_FILENAME
    save_pickup_time_master_xlsx(_master_df("07:00"), master_path)
    before_bytes = master_path.read_bytes()
    rescue_dir = tmp_path / "rescue"
    original_open = builtins.open

    def locked_open(file, mode="r", *args, **kwargs):
        if Path(file) == master_path and mode == "r+b":
            raise PermissionError("locked")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", locked_open)
    monkeypatch.setattr(data_loader, "_master_rescue_dir", lambda: rescue_dir)

    with pytest.raises(MasterFileLockedError) as excinfo:
        save_pickup_time_master_xlsx(_master_df("10:45"), master_path)

    message = str(excinfo.value)
    assert "ファイルがExcelで開かれている可能性があります" in message
    assert str(rescue_dir) in message
    assert master_path.read_bytes() == before_bytes
    assert len(list(rescue_dir.glob("入車時間マスタ_未保存_*.xlsx"))) == 1


def test_save_permission_error_from_writer_rescues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    master_path = tmp_path / MASTER_FILENAME
    rescue_dir = tmp_path / "rescue"
    calls: list[Path] = []
    real_writer = data_loader._write_master_excel

    def write_or_lock(df: pd.DataFrame, path: Path) -> None:
        calls.append(path)
        if path == master_path:
            raise PermissionError("locked")
        real_writer(df, path)

    monkeypatch.setattr(data_loader, "_master_rescue_dir", lambda: rescue_dir)
    monkeypatch.setattr(data_loader, "_write_master_excel", write_or_lock)

    with pytest.raises(MasterFileLockedError) as excinfo:
        save_pickup_time_master_xlsx(_master_df(), master_path)

    assert "ファイルがExcelで開かれている可能性があります" in str(excinfo.value)
    assert any(path.parent == rescue_dir for path in calls)


def test_save_does_not_create_missing_destination_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    master_path = tmp_path / "missing" / MASTER_FILENAME
    rescue_dir = tmp_path / "rescue"
    monkeypatch.setattr(data_loader, "_master_rescue_dir", lambda: rescue_dir)

    with pytest.raises(MasterFileError) as excinfo:
        save_pickup_time_master_xlsx(_master_df(), master_path)

    assert not master_path.parent.exists()
    assert "保存先フォルダが見つかりません" in str(excinfo.value)
    assert len(list(rescue_dir.glob("入車時間マスタ_未保存_*.xlsx"))) == 1


def test_load_missing_master_returns_empty_and_reports_conflicts(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    master_path = tmp_path / MASTER_FILENAME
    (tmp_path / "入車時間マスタ (競合コピー).xlsx").write_text("dummy", encoding="utf-8")
    (tmp_path / "~$入車時間マスタ.xlsx").write_text("dummy", encoding="utf-8")

    loaded = load_pickup_time_master_xlsx(master_path)

    message = caplog.text


    assert loaded.empty
    assert list(loaded.columns) == list(MASTER_COLUMNS)
    assert "OneDrive同期の競合の可能性" in message
    assert "~$入車時間マスタ.xlsx" not in message


def test_load_read_failure_raises_read_error_with_conflict_guidance(tmp_path: Path):
    master_path = tmp_path / MASTER_FILENAME
    master_path.write_text("not excel", encoding="utf-8")
    (tmp_path / "入車時間マスタ - コピー.xlsx").write_text("dummy", encoding="utf-8")

    with pytest.raises(MasterFileReadError) as excinfo:
        load_pickup_time_master_xlsx(master_path)

    assert isinstance(excinfo.value, ValueError)
    assert "OneDrive同期の競合の可能性" in str(excinfo.value)


def test_load_missing_required_columns_raises_read_error(tmp_path: Path):
    master_path = tmp_path / MASTER_FILENAME
    pd.DataFrame([{"OData_納入先": "A"}]).to_excel(master_path, index=False)

    with pytest.raises(MasterFileReadError) as excinfo:
        load_pickup_time_master_xlsx(master_path)

    assert "入車時間マスタに必要な列がありません" in str(excinfo.value)