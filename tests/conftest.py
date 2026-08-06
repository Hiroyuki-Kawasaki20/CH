from __future__ import annotations

"""Issue #39: pytest実行で実マスタが書き換わる事故の再発防止。"""

import sys
from pathlib import Path

import pytest

from src.services import data_loader


@pytest.fixture(autouse=True)
def guard_master_path_with_tmp_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Issue #39: pytest実行で実マスタが書き換わる事故の再発防止。"""

    temp_master_path = tmp_path / "入車時間マスタ.xlsx"
    original_get_master_path = data_loader.get_master_path

    def _get_temp_master_path() -> Path:
        return temp_master_path

    monkeypatch.setattr(data_loader, "get_master_path", _get_temp_master_path)

    for module in list(sys.modules.values()):
        if module is None or not hasattr(module, "get_master_path"):
            continue
        if getattr(module, "get_master_path") is original_get_master_path:
            monkeypatch.setattr(module, "get_master_path", _get_temp_master_path, raising=False)