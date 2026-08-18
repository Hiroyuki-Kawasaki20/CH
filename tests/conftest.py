from __future__ import annotations

"""Issue #39: pytest実行で実マスタが書き換わる事故の再発防止。"""

import hashlib
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


@pytest.fixture(scope="session", autouse=True)
def assert_real_master_untouched() -> None:
    """Issue #34の保険（検出型）。guard_master_path_with_tmp_fileが予防型ガード
    （get_master_pathの差し替え）で防ぎきれない抜け穴を、セッション終端の
    ハッシュ差分検出で補う最後の砦。"""

    real_master_path = Path(__file__).resolve().parents[1] / "入車時間マスタ.xlsx"

    def _hash() -> str | None:
        if not real_master_path.exists():
            return None
        return hashlib.sha256(real_master_path.read_bytes()).hexdigest()

    before_hash = _hash()
    yield
    after_hash = _hash()
    assert before_hash == after_hash, (
        "テストが実マスタ『入車時間マスタ.xlsx』を書き換えました"
        "（テスト分離違反 / Issue #34）"
    )