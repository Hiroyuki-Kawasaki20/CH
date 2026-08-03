import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import _build_size1_mixed


def test_size21_stack_must_not_include_size1_even_without_special_hinban():
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

    by_mountain = details.groupby("山通番")["サイズ種類"].apply(lambda s: set(s.astype(str).str.strip()))
    for yama_no, size_set in by_mountain.items():
        if "21" in size_set:
            assert "1" not in size_set, f"山通番 {yama_no} で size21 と size1 が同居: {size_set}"
