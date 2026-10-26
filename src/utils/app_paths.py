# -*- coding: utf-8 -*-
"""Windows利用者別の保存先。Tk非依存で、解決時にはディレクトリを作らない。"""

import os
from pathlib import Path


def get_user_data_dir() -> Path:
    """開発版・exe版共通。呼出時点の利用者領域以外へは退避しない。"""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "CHKanban"


def get_output_dir() -> Path:
    """ログ・履歴Excel・未ヒットCSV・既定アーカイブ等のローカル保存先。"""
    return get_user_data_dir() / "output"
