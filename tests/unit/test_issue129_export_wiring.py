import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import src.app.gui as gui_module
from src.app.gui import App
from src.services.export_archive import archive_export, resolve_archive_dir
from src.services.export_validator import ExportInvariantReport


def _row(store, sebango=""):
    return {
        "山通番": 1,
        "ストア": store,
        "NONYUHIBIN": "2026082806",
        "UKEIRE": "B7",
        "納入先": "KVC",
        "SEBANGO": sebango,
    }


def _app(tmp_path, strict=True):
    display = pd.DataFrame([
        _row("L12-C-5"),
        _row("L12-D-8", "720"),
        _row("C15-A-1", "700"),
        {**_row("Q10-B-3", "439"), "山通番": 2, "NONYUHIBIN": "2026090414", "UKEIRE": "07", "納入先": "日野"},
    ])
    export = display.iloc[[1, 2, 3]].copy()
    spo = pd.DataFrame({
        "GroupedData": [json.dumps([row]) for row in export.to_dict("records")],
        "グループ番号": [1, 1, 2],
    })
    app = SimpleNamespace(
        export_dir=str(tmp_path / "spo-watch"),
        archive_enabled=False,
        archive_dir="",
        export_invariant_strict=strict,
        all_mountain_details_display=display,
        all_mountain_details=export,
        proc_details=pd.DataFrame(),
        mountain_proc=pd.DataFrame(),
        mountain_proc_map={},
        mountain_start_times={},
        _spo=spo,
    )
    return app, spo


def _patch_spo_pipeline(monkeypatch, app, tmp_path):
    monkeypatch.setattr(gui_module, "resolve_spo_output_dirs", lambda _: {
        "spo_xlsx_dir": str(tmp_path / "spo-watch"),
        "history_dir": str(tmp_path / "history"),
        "unmatched_dir": str(tmp_path / "unmatched"),
    })
    monkeypatch.setattr(gui_module, "build_spo_export_df", lambda *args, **kwargs: app._spo)
    monkeypatch.setattr(gui_module, "load_pickup_time_master_xlsx", lambda _: pd.DataFrame())


def test_issue129_strict_loss_calls_no_output_functions(monkeypatch, tmp_path):
    app, _ = _app(tmp_path, strict=True)
    _patch_spo_pipeline(monkeypatch, app, tmp_path)
    calls = {"spo": 0, "history": 0, "kanban": 0}
    monkeypatch.setattr(gui_module, "export_spo_xlsx_staged", lambda *a, **k: calls.__setitem__("spo", calls["spo"] + 1))
    monkeypatch.setattr(gui_module, "append_to_spo_history", lambda *a, **k: calls.__setitem__("history", calls["history"] + 1))
    monkeypatch.setattr(gui_module, "export_kanban_xlsx", lambda *a, **k: calls.__setitem__("kanban", calls["kanban"] + 1))
    monkeypatch.setattr(gui_module.messagebox, "showerror", lambda *a, **k: None)

    App._auto_export_spo(app)

    assert calls == {"spo": 0, "history": 0, "kanban": 0}


def test_issue129_non_strict_loss_continues_actual_spo_outputs(monkeypatch, tmp_path):
    app, _ = _app(tmp_path, strict=False)
    _patch_spo_pipeline(monkeypatch, app, tmp_path)
    calls = {"spo": 0, "history": 0, "kanban": 0}
    monkeypatch.setattr(gui_module, "export_spo_xlsx_staged", lambda *a, **k: calls.__setitem__("spo", calls["spo"] + 1) or str(tmp_path / "out.xlsx"))
    monkeypatch.setattr(gui_module, "append_to_spo_history", lambda *a, **k: calls.__setitem__("history", calls["history"] + 1))
    monkeypatch.setattr(gui_module, "export_kanban_xlsx", lambda *a, **k: calls.__setitem__("kanban", calls["kanban"] + 1))
    monkeypatch.setattr(gui_module.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui_module.messagebox, "showinfo", lambda *a, **k: None)

    App._auto_export_spo(app)

    assert calls["spo"] == 1
    assert calls["history"] == 1
    assert calls["kanban"] == 0


def test_issue129_validator_exception_does_not_fail_open(monkeypatch, tmp_path):
    app, _ = _app(tmp_path, strict=True)
    _patch_spo_pipeline(monkeypatch, app, tmp_path)
    calls = []
    monkeypatch.setattr(gui_module, "verify_export_invariant", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("validator failure")))
    monkeypatch.setattr(gui_module, "export_spo_xlsx_staged", lambda *a, **k: calls.append("spo"))
    monkeypatch.setattr(gui_module, "append_to_spo_history", lambda *a, **k: calls.append("history"))

    with pytest.raises(RuntimeError, match="validator failure"):
        App._auto_export_spo(app)

    assert calls == []


def test_archive_manifest_contains_counts(tmp_path):
    output = tmp_path / "SPO.xlsx"
    output.write_bytes(b"xlsx")
    report = ExportInvariantReport(gui_count=4, pipeline_count=3, exported_count=3)
    archive_dir = archive_export(
        str(output), [], pd.DataFrame([_row("A")]), report, {"archive_enabled": True}, str(tmp_path / "archive")
    )

    manifest_path = next((tmp_path / "archive").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert archive_dir is not None
    assert manifest["A_gui_count"] == 4
    assert manifest["B_pipeline_count"] == 3
    assert manifest["C_exported_count"] == 3


def test_archive_failure_does_not_fail_output(monkeypatch, tmp_path):
    app, spo = _app(tmp_path, strict=True)
    app.all_mountain_details_display = app.all_mountain_details.copy()
    _patch_spo_pipeline(monkeypatch, app, tmp_path)
    calls = []
    monkeypatch.setattr(gui_module, "verify_export_invariant", lambda *a, **k: ExportInvariantReport(3, 3, 3))
    monkeypatch.setattr(gui_module, "export_spo_xlsx_staged", lambda *a, **k: calls.append("spo") or str(tmp_path / "out.xlsx"))
    monkeypatch.setattr(gui_module, "archive_export", lambda *a, **k: (_ for _ in ()).throw(OSError("archive failure")))
    monkeypatch.setattr(gui_module, "append_to_spo_history", lambda *a, **k: calls.append("history"))
    monkeypatch.setattr(gui_module.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui_module.messagebox, "showinfo", lambda *a, **k: None)
    app.archive_enabled = True

    App._auto_export_spo(app)

    assert calls == ["spo", "history"]


def test_default_archive_is_outside_spo_watch_folder(tmp_path):
    export_dir = tmp_path / "spo-watch"
    resolved = resolve_archive_dir(str(export_dir))
    assert Path(resolved).parent == tmp_path
    assert not Path(resolved).is_relative_to(export_dir)