# -*- coding: utf-8 -*-
"""OneDrive同期先へのSPO Excel出力を安全化するモジュール。

注意:
- 本モジュールは競合発生率を下げるための防御策であり、既に発生した
  OneDrive/SharePoint側の競合を自動解消するものではない。
- 既存競合が残っている場合は、従来どおり手動での競合解消が前提となる。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from typing import Optional, Tuple

import pandas as pd


# 層1: 同一プロセス内の同時書込を防ぐための排他ロック
_export_lock = threading.Lock()


def export_to_spo(df: pd.DataFrame, output_path: str) -> str:
    """SPO用Excelを3段防御で出力する。

    層1: プロセス内排他で同時書込を直列化。
    層2: 一時領域で完成させてから同期フォルダへ1回コピー。
    層3: ファイル状態の安定を監視し、同期の追従を待つ。
    """
    with _export_lock:
        _write_via_temp_then_copy(df, output_path=output_path)
        _wait_for_sync(output_path)
    return output_path


def _write_via_temp_then_copy(df: pd.DataFrame, output_path: str) -> str:
    """層2: 同期フォルダ外で完成させ、完成品だけを1回コピーする。"""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        df.to_excel(tmp_path, index=False)
        shutil.copy2(tmp_path, output_path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
    return output_path


def _wait_for_sync(
    output_path: str,
    stable_sec: float = 3.0,
    check_interval: float = 0.5,
    timeout: float = 30.0,
) -> bool:
    """層3: サイズ/更新時刻が一定時間変化しないことを同期完了の目安とする。"""
    start = time.monotonic()
    last_sig: Optional[Tuple[int, float]] = None
    stable_since: Optional[float] = None

    while True:
        now = time.monotonic()
        try:
            st = os.stat(output_path)
            sig: Optional[Tuple[int, float]] = (int(st.st_size), float(st.st_mtime))
        except FileNotFoundError:
            sig = None

        if sig is not None and sig == last_sig:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return True
        else:
            last_sig = sig
            stable_since = None

        if now - start >= timeout:
            print(
                f"[spo_export] 同期待機タイムアウト: {output_path} "
                f"(timeout={timeout}s, stable_sec={stable_sec}s)"
            )
            return False

        time.sleep(check_interval)
