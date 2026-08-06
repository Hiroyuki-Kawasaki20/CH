from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.services.data_loader import get_master_path, save_pickup_time_master_xlsx


def test_get_master_path_is_redirected_to_tmp_path(tmp_path: Path):
    repo_master_path = Path(__file__).resolve().parents[2] / "入車時間マスタ.xlsx"
    guarded_path = get_master_path()

    assert guarded_path == tmp_path / "入車時間マスタ.xlsx"
    assert guarded_path != repo_master_path


def test_save_via_get_master_path_does_not_touch_repo_master(tmp_path: Path):
    repo_master_path = Path(__file__).resolve().parents[2] / "入車時間マスタ.xlsx"
    if not repo_master_path.exists():
        pytest.skip("リポジトリ直下の実マスタが存在しないため検証をスキップ")

    before_mtime_ns = repo_master_path.stat().st_mtime_ns
    before_bytes = repo_master_path.read_bytes()

    guarded_path = get_master_path()
    save_pickup_time_master_xlsx(
        pd.DataFrame(
            [
                {
                    "OData_納入先": "テスト納入先",
                    "NONYUHIBIN": "01",
                    "入車時間": "08:30",
                    "セットありフラグ": "1",
                }
            ]
        ),
        guarded_path,
    )

    assert guarded_path == tmp_path / "入車時間マスタ.xlsx"
    assert guarded_path.exists()
    assert repo_master_path.stat().st_mtime_ns == before_mtime_ns
    assert repo_master_path.read_bytes() == before_bytes