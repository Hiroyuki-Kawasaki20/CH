import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import _build_size1_mixed


def test_size1_and_size21_stack_are_merged_with_size1_before_size21():
    expanded = pd.DataFrame(
        [
            {
                "HINBAN": "210000000001",
                "サイズ種類": "21",
                "NONYUHIBIN": "07",
                "納入先": "店A",
                "SYUKKASAKI": "店A",
                "高さ": 700,
                "移動工数": 10,
                "PLANKANBANSU": 1,
            },
            {
                "HINBAN": "210000000002",
                "サイズ種類": "21",
                "NONYUHIBIN": "07",
                "納入先": "店A",
                "SYUKKASAKI": "店A",
                "高さ": 700,
                "移動工数": 9,
                "PLANKANBANSU": 1,
            },
            {
                "HINBAN": "100000000001",
                "サイズ種類": "1",
                "NONYUHIBIN": "07",
                "納入先": "店A",
                "SYUKKASAKI": "店A",
                "高さ": 500,
                "移動工数": 8,
                "PLANKANBANSU": 1,
            },
            {
                "HINBAN": "100000000002",
                "サイズ種類": "1",
                "NONYUHIBIN": "07",
                "納入先": "店A",
                "SYUKKASAKI": "店A",
                "高さ": 500,
                "移動工数": 7,
                "PLANKANBANSU": 1,
            },
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 1
    assert len(details) == 4

    size_types = details["サイズ種類"].astype(str).str.strip().tolist()
    assert size_types == ["1", "1", "21", "21"]
