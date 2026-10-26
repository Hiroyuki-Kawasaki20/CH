"""Windows利用者別保存。実設定・本番同期フォルダを使用しない。"""
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.services import data_loader as loader
from src.services import lane_end_times_history as history

# conftestの実マスタ保護で差し替えられる前の関数を保持する。
_original_master_resolver = loader.get_master_path


@pytest.fixture(autouse=True)
def isolated_user(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-A"))
    # REDでも旧実装が本物のrepo/exe隣へ書かないように配置場所だけを偽装。
    fake_repo = tmp_path / "app"
    monkeypatch.setattr(loader, "__file__", str(fake_repo / "src/services/data_loader.py"))
    monkeypatch.setattr(history, "__file__", str(fake_repo / "src/services/lane_end_times_history.py"))
    monkeypatch.setattr(sys, "executable", str(fake_repo / "CH.exe"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)


@pytest.mark.parametrize("frozen", [False, True])
def test_config_path_uses_user_area_in_source_and_frozen(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    assert loader.get_config_path() == tmp_path / "user-A/CHKanban/ch_kanban_settings.json"
    assert not loader.get_config_path().parent.exists()


def test_users_do_not_share_settings(monkeypatch, tmp_path):
    settings = {"base_dir": "A-input", "export_dir": "A-output", "master_path": "A-master", "archive_dir": "A-archive", "unknown_key": {"keep": True}}
    path_a = loader.get_config_path()
    loader.save_config(settings)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-B"))
    path_b = loader.get_config_path()
    assert path_b != path_a
    assert loader.load_config() == {}
    loader.save_config({"base_dir": "B-input"})
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-A"))
    assert loader.load_config() == settings


@pytest.mark.parametrize("frozen", [False, True])
def test_old_settings_are_not_adopted(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    old_folder = tmp_path / "app" / ("" if frozen else "config")
    old_folder.mkdir(parents=True)
    old_path = old_folder / "ch_kanban_settings.json"
    old_path.write_text(json.dumps({"base_dir": "other-user", "export_dir": "other-watch", "master_path": "other-master", "archive_dir": "other-archive"}), encoding="utf-8")
    assert loader.load_config() == {}
    assert not (tmp_path / "user-A").exists()


def test_config_missing_and_parent_created_on_save():
    assert loader.load_config() == {}
    path = loader.get_config_path()
    assert not path.parent.exists()
    loader.save_config({"auto_reload_minute": 25, "custom": "keep"})
    assert path.is_file()
    assert loader.load_config() == {"auto_reload_minute": 25, "custom": "keep"}


@pytest.mark.parametrize("content", ["{invalid", "[]", "null", "42", '"text"'])
def test_invalid_or_non_object_json_is_initial_state(content):
    path = loader.get_config_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert loader.load_config() == {}
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_failed_save_preserves_existing_settings(monkeypatch, failure):
    loader.save_config({"keep": "original"})
    path = loader.get_config_path()
    before = path.read_bytes()
    if failure == "replace":
        def denied(*args):
            raise PermissionError("replacement denied")
        monkeypatch.setattr(os, "replace", denied)
        payload = {"new": "value"}
        error = PermissionError
    else:
        payload = {"not_json": object()}
        error = TypeError
    with pytest.raises(error):
        loader.save_config(payload)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_config_parent_permission_error_is_not_success(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("folder denied")
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(PermissionError):
        loader.save_config({"value": 1})


def test_history_is_per_user_and_old_history_is_not_adopted(monkeypatch, tmp_path):
    old = tmp_path / "app/config/lane_end_times_history.json"
    old.parent.mkdir(parents=True)
    history.save_lane_end_times_history([{"メイン": 99}], old)
    assert history.load_lane_end_times_history() == []
    assert history.save_lane_end_times_history([{"メイン": 100}])
    path_a = history.get_history_path()
    assert path_a == tmp_path / "user-A/CHKanban/lane_end_times_history.json"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-B"))
    assert history.get_history_path() != path_a
    assert history.load_lane_end_times_history() == []
    assert history.save_lane_end_times_history([{"メイン": 200}])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-A"))
    assert history.load_lane_end_times_history() == [{"メイン": 100}]


@pytest.mark.parametrize("missing_parent", [False, True])
def test_missing_base_master_never_uses_app_neighbor(tmp_path, missing_parent):
    base = tmp_path / "input"
    if not missing_parent:
        base.mkdir()
    neighbor = tmp_path / "app/入車時間マスタ.xlsx"
    neighbor.parent.mkdir(parents=True)
    neighbor.write_bytes(b"another user's master")
    assert loader._resolve_master_path({"base_dir": str(base)}, neighbor) == base / loader.MASTER_FILENAME


def test_master_configured_precedence_and_explicit_legacy_argument(tmp_path):
    base = tmp_path / "input"
    base.mkdir()
    base_master = base / loader.MASTER_FILENAME
    base_master.touch()
    explicit = tmp_path / "explicit.xlsx"
    config = {"base_dir": str(base), "master_path": str(explicit)}
    assert loader._resolve_master_path(config) == base_master
    explicit.touch()
    assert loader._resolve_master_path(config) == explicit
    assert loader._resolve_master_path({}, explicit) == explicit


def test_unconfigured_master_does_not_select_app_neighbor(monkeypatch, tmp_path):
    neighbor = tmp_path / "app/入車時間マスタ.xlsx"
    neighbor.parent.mkdir(parents=True)
    neighbor.touch()
    with pytest.raises(loader.MasterFileError, match="入力フォルダ"):
        _original_master_resolver()


def test_initial_folder_selection_and_second_launch_reuse(monkeypatch, tmp_path):
    from tkinter import messagebox
    base = tmp_path / "input"
    watch = tmp_path / "watch"
    base.mkdir()
    watch.mkdir()
    for name in ("出荷情報_CH_最新版.csv", "出荷場一覧.csv"):
        (base / name).touch()
    calls = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a: None)
    monkeypatch.setattr(loader, "select_data_folder", lambda: calls.append("input") or base)
    monkeypatch.setattr(loader, "select_export_folder", lambda: calls.append("output") or watch)
    loader.save_config({"unknown_key": "preserved"})
    for _ in range(2):
        assert loader.get_base_dir() == base
        assert loader.get_export_dir() == watch
    assert calls == ["input", "output"]
    assert loader.load_config()["unknown_key"] == "preserved"
    assert list(watch.iterdir()) == []  # 書込権限の試験ファイルを作らない。


def test_home_fallback_and_no_import_side_effect(monkeypatch, tmp_path):
    from src.utils import app_paths
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    importlib.reload(app_paths)
    assert app_paths.get_user_data_dir() == home / "AppData/Local/CHKanban"
    assert app_paths.get_output_dir() == home / "AppData/Local/CHKanban/output"
    assert not home.exists()


def test_outputs_and_default_archive_follow_current_user(monkeypatch, tmp_path):
    from src.app import gui
    from src.services.export_archive import resolve_archive_dir
    for user in ("A", "B"):
        local = tmp_path / user
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        dirs = gui.resolve_spo_output_dirs(str(tmp_path / "watch"))
        output = local / "CHKanban/output"
        assert Path(dirs["history_dir"]) == output
        assert Path(dirs["unmatched_dir"]) == output
        assert dirs["spo_xlsx_dir"] == str(tmp_path / "watch")
        assert Path(resolve_archive_dir(dirs["spo_xlsx_dir"], local_output_dir=dirs["history_dir"])) == output / "_export_archive"
        assert not local.exists()


def test_logging_initialization_uses_user_output(monkeypatch, tmp_path):
    from src.app import gui
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.delenv("CH_TRACE_135", raising=False)
    captured = []
    directories = []
    monkeypatch.setattr(Path, "mkdir", lambda path, **kwargs: directories.append(path))
    monkeypatch.setattr(logging, "FileHandler", lambda path, **kwargs: captured.append(path) or logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    gui._setup_logging()
    assert captured == [tmp_path / "user-A/CHKanban/output/logs/ch_kanban.log"]
    assert directories == [tmp_path / "user-A/CHKanban/output/logs"]


@pytest.mark.parametrize("user", ["A", "B"])
@pytest.mark.parametrize("frozen", [False, True])
def test_compatibility_constants_in_fresh_user_process(tmp_path, user, frozen):
    # 定数は起動時に確定するため、Windows利用者同様に別プロセスで検証。
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / user), PYTHONDONTWRITEBYTECODE="1")
    code = f"import sys; sys.frozen={frozen!r}; from src.models.constants import LOCAL_OUTPUT_DIR; from src.services.spo_export import DEFAULT_STAGING_DIR; print(LOCAL_OUTPUT_DIR); print(DEFAULT_STAGING_DIR)"
    # isolated_userが変更したsys.executableではなく、元の実行環境を使用。
    executable = Path(sys.prefix) / ("python.exe" if os.name == "nt" else "bin/python")
    result = subprocess.run([str(executable), "-c", code], cwd=repo, env=env, text=True, capture_output=True, check=True)
    output, staging = result.stdout.strip().splitlines()
    assert Path(output) == tmp_path / user / "CHKanban/output"
    assert Path(staging).is_relative_to(Path(output))
    assert not (tmp_path / user).exists()


def test_startup_missing_master_shows_selected_input_guidance(monkeypatch, tmp_path):
    from src.app import gui
    base = tmp_path / "selected-input"
    base.mkdir()
    loader.save_config({"base_dir": str(base)})
    monkeypatch.setattr(gui, "get_master_path", _original_master_resolver)
    warnings = []
    refreshes = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda title, message: warnings.append(message))
    app = SimpleNamespace(
        refresh_master_tree=lambda: refreshes.append("master"),
        refresh_routes=lambda: refreshes.append("routes"),
    )
    gui.App._initial_load_master(app)
    assert app.master_data.empty
    assert refreshes == ["master", "routes"]
    assert len(warnings) == 1
    assert str(base / loader.MASTER_FILENAME) in warnings[0]
    assert str(loader.get_config_path()) in warnings[0]
    assert "base_dir" in warnings[0]
    assert not (base / loader.MASTER_FILENAME).exists()
