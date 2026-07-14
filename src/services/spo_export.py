# -*- coding: utf-8 -*-
"""OneDrive同期先へのSPO Excel出力を安全化するモジュール。

注意:
- 本モジュールは競合発生率を下げるための防御策であり、既に発生した
  OneDrive/SharePoint側の競合を自動解消するものではない。
- 既存競合が残っている場合は、従来どおり手動での競合解消が前提となる。
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from typing import Optional, Tuple

import pandas as pd

from ..utils.excel_utils import _add_table_exact


# 層1: 同一プロセス内の同時書込を防ぐための排他ロック
_export_lock = threading.Lock()

# Staging + Move方式の定数
DEFAULT_STAGING_DIR = r"C:\Temp\spo_staging"
SPO_TABLE_NAME = "SPOExport"

# ロギング
logger = logging.getLogger(__name__)


def _generate_unique_filename(base_name: str) -> str:
    """秒単位+マイクロ秒+UUID4先頭8桁で一意なファイル名を生成する。
    
    例: SPOアップロード用_20260714_070802_123456_a1b2c3d4.xlsx
    同時実行や短時間の連続出力でも重複しないことを保証する。
    
    Args:
        base_name: ファイル名の基本部分（例：SPOアップロード用）
    
    Returns:
        一意なタイムスタンプ+UUID付きファイル名（.xlsx拡張子）
    """
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    microsec = now.microsecond
    uuid_prefix = str(uuid.uuid4())[:8]
    return f"{base_name}_{ts}_{microsec:06d}_{uuid_prefix}.xlsx"


def export_to_spo_staged(
    df: pd.DataFrame,
    watch_dir: str,
    staging_dir: str = DEFAULT_STAGING_DIR,
    table_name: str = SPO_TABLE_NAME,
    base_name: str = "SPOアップロード用",
) -> Optional[str]:
    """Staging領域で完成させてからwatch_dirに移動するSPO出力。
    
    OneDrive/SharePoint同期競合を根本回避するため、staging領域で
    完全なファイル（テーブル付き）を作成してから、watch_dir（同期対象）
    に移動する方式を採用。
    
    処理順序:
      1. df.empty の場合はファイルを作成せず None を返す（空トリガー防止）
      2. staging_dir・watch_dir を os.makedirs(exist_ok=True) で用意する
      3. staging_dir に一意ファイル名で df.to_excel（openpyxl engine, .xlsx形式）
      4. 既存の _add_table_exact(path, table_name) を再利用してテーブル化
         （1行目=ヘッダー、列名の重複/空欄/前後空白/改行なしは既存DataFrame
         の列構成のまま維持し、ここでは変更しない）
      5. os.replace(staging_path, final_path) を試み、OSError（別ドライブ間
         など）の場合のみ shutil.move にフォールバック（処理の最後の1手）
      6. 移動後、os.path.exists(final_path) で存在確認。無ければ例外
      7. staging_path が残っていれば削除（通常は3で既に消えている）
      8. 例外発生時（try/exceptで捕捉）は staging_path・final_path 双方を
         削除してから re-raise し、watch_dirに不完全ファイルを残さない
      9. すべての工程をloggerでINFO/EXCEPTIONログ出力する
      10. 既存の _export_lock（同一プロセス内排他ロック）でwithブロックする
    
    Args:
        df: 出力対象のDataFrame
        watch_dir: 同期対象フォルダのパス（Power Automate監視先）
        staging_dir: staging領域のパス（OneDrive/SharePoint同期対象外）
        table_name: Excelテーブル名（デフォルト: "SPOExport"）
        base_name: ファイル名の基本部分（デフォルト: "SPOアップロード用"）
    
    Returns:
        移動後の最終ファイルパス（成功時）、None（空DataFrame時）
        
    Raises:
        Exception: ファイル操作失敗時（staging・watch_dir 双方 cleanup 後 re-raise）
    """
    with _export_lock:
        # 1. 空DataFrame判定
        if df.empty:
            logger.info(f"export_to_spo_staged: 空DataFrameのため処理スキップ")
            return None
        
        try:
            # 2. ディレクトリ確保
            os.makedirs(staging_dir, exist_ok=True)
            os.makedirs(watch_dir, exist_ok=True)
            logger.info(f"export_to_spo_staged: staging_dir={staging_dir}, watch_dir={watch_dir} 確保")
            
            # 3. staging領域でファイル作成
            unique_filename = _generate_unique_filename(base_name)
            staging_path = os.path.join(staging_dir, unique_filename)
            logger.info(f"export_to_spo_staged: staging_path={staging_path}")
            
            df.to_excel(staging_path, index=False, engine="openpyxl")
            logger.info(f"export_to_spo_staged: DataFrame を Excel に書込 ({staging_path})")
            
            # 4. テーブル化（staging領域で完成させる）
            _add_table_exact(staging_path, table_name)
            logger.info(f"export_to_spo_staged: テーブル'{table_name}' を追加")
            
            # 5. watch_dirに移動（os.replace → shutil.move フォールバック）
            final_path = os.path.join(watch_dir, unique_filename)
            try:
                os.replace(staging_path, final_path)
                logger.info(f"export_to_spo_staged: os.replace で移動成功 ({final_path})")
            except OSError as e:
                logger.warning(f"export_to_spo_staged: os.replace 失敗（{e}）、shutil.move にフォールバック")
                shutil.move(staging_path, final_path)
                logger.info(f"export_to_spo_staged: shutil.move で移動成功 ({final_path})")
            
            # 6. 移動後の存在確認
            if not os.path.exists(final_path):
                raise FileNotFoundError(f"移動後のファイルが見つかりません: {final_path}")
            logger.info(f"export_to_spo_staged: 最終ファイルの存在確認 OK")
            
            # 7. staging_path の残存削除
            try:
                if os.path.exists(staging_path):
                    os.remove(staging_path)
                    logger.info(f"export_to_spo_staged: staging 残存ファイル削除")
            except OSError as e:
                logger.warning(f"export_to_spo_staged: staging 残存削除失敗（{e}）")
            
            logger.info(f"export_to_spo_staged: 正常終了 ({final_path})")
            return final_path
            
        except Exception as e:
            # 8. 例外時の cleanup
            logger.exception(f"export_to_spo_staged: 例外発生 ({e})")
            try:
                if 'staging_path' in locals() and os.path.exists(staging_path):
                    os.remove(staging_path)
                    logger.info(f"export_to_spo_staged: cleanup - staging_path 削除")
            except OSError as cleanup_err:
                logger.warning(f"export_to_spo_staged: cleanup - staging_path 削除失敗（{cleanup_err}）")
            
            try:
                if 'final_path' in locals() and os.path.exists(final_path):
                    os.remove(final_path)
                    logger.info(f"export_to_spo_staged: cleanup - final_path 削除")
            except OSError as cleanup_err:
                logger.warning(f"export_to_spo_staged: cleanup - final_path 削除失敗（{cleanup_err}）")
            
            raise


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
        _add_table_exact(tmp_path, "SPOExport")
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
