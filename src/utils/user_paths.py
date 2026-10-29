"""Tk非依存のユーザー領域解決。パスを返すだけでファイルは作成しない。"""

import os
from pathlib import Path


def get_user_data_dir() -> Path:
    """実行ユーザーの設定・履歴・ローカル成果物の基準フォルダ。"""
    local_app_data = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local_app_data / "CHKanban"
