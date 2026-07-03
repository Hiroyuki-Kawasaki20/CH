# -*- coding: utf-8 -*-
"""CHかんばんセット — SPO安全出力のユニットテスト"""

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services import exporter
from src.services import spo_export


def test_write_via_temp_then_copy_creates_output_and_cleans_temp(tmp_path, monkeypatch):
    df = pd.DataFrame({"A": [1, 2], "B": ["x", "y"]})
    output_path = tmp_path / "out.xlsx"

    forced_tmp_path = tmp_path / "forced_tmp.xlsx"

    def fake_mkstemp(suffix: str):
        fd = os.open(str(forced_tmp_path), os.O_CREAT | os.O_RDWR)
        return fd, str(forced_tmp_path)

    monkeypatch.setattr(spo_export.tempfile, "mkstemp", fake_mkstemp)

    returned = spo_export._write_via_temp_then_copy(df, str(output_path))
    assert returned == str(output_path)
    assert output_path.exists()
    out_df = pd.read_excel(output_path, engine="openpyxl")
    assert list(out_df.columns) == ["A", "B"]
    assert out_df.to_dict(orient="records") == [{"A": 1, "B": "x"}, {"A": 2, "B": "y"}]
    assert not forced_tmp_path.exists()


def test_wait_for_sync_returns_true_for_stable_file(tmp_path):
    p = tmp_path / "stable.xlsx"
    p.write_bytes(b"abc")

    ok = spo_export._wait_for_sync(
        str(p),
        stable_sec=0.0,
        check_interval=0.001,
        timeout=0.2,
    )
    assert ok is True


def test_wait_for_sync_timeout_for_missing_file(monkeypatch):
    monkeypatch.setattr(spo_export.time, "sleep", lambda _: None)

    ticks = {"n": 0}

    def fake_monotonic():
        ticks["n"] += 1
        return ticks["n"] * 0.06

    monkeypatch.setattr(spo_export.time, "monotonic", fake_monotonic)

    ok = spo_export._wait_for_sync(
        "C:/does-not-exist.xlsx",
        stable_sec=0.2,
        check_interval=0.0,
        timeout=0.1,
    )
    assert ok is False


def test_wait_for_sync_timeout_when_file_keeps_changing(monkeypatch):
    monkeypatch.setattr(spo_export.time, "sleep", lambda _: None)

    ticks = {"n": 0}

    def fake_monotonic():
        ticks["n"] += 1
        return ticks["n"] * 0.05

    monkeypatch.setattr(spo_export.time, "monotonic", fake_monotonic)

    stats = {"n": 0}

    def fake_stat(_path: str):
        stats["n"] += 1
        return SimpleNamespace(st_size=100, st_mtime=float(stats["n"]))

    monkeypatch.setattr(spo_export.os, "stat", fake_stat)

    ok = spo_export._wait_for_sync(
        "dummy.xlsx",
        stable_sec=0.2,
        check_interval=0.0,
        timeout=0.15,
    )
    assert ok is False


def test_export_lock_serializes_parallel_calls(tmp_path, monkeypatch):
    df = pd.DataFrame({"x": [1]})
    output_path = tmp_path / "serialized.xlsx"

    active = {"count": 0, "max": 0}
    counters_lock = threading.Lock()

    def fake_write(_df: pd.DataFrame, output_path: str):
        with counters_lock:
            active["count"] += 1
            if active["count"] > active["max"]:
                active["max"] = active["count"]
        # lockの直列化が無いとここが重なる
        time.sleep(0.02)
        Path(output_path).write_text("ok", encoding="utf-8")
        with counters_lock:
            active["count"] -= 1
        return output_path

    monkeypatch.setattr(spo_export, "_write_via_temp_then_copy", fake_write)
    monkeypatch.setattr(spo_export, "_wait_for_sync", lambda *_args, **_kwargs: True)

    threads = [
        threading.Thread(target=spo_export.export_to_spo, args=(df, str(output_path)))
        for _ in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert active["max"] == 1
    assert output_path.exists()


def test_export_spo_xlsx_adds_spoexport_table(tmp_path):
    spo_df = pd.DataFrame(
        [
            {
                "タイトル": "山1",
                "工程": "1工程",
                "groupdata": "[]",
            }
        ]
    )
    out_path = exporter.export_spo_xlsx(spo_df, str(tmp_path), base_name="SPO_test")

    wb = load_workbook(out_path)
    ws = wb.active
    assert "SPOExport" in ws.tables
