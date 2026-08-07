import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import _build_size1_mixed, build_all_mountain_details


def _row(size_type, vendor, nonyuhibin, height, move_cost, hinban=None):
    normalized_size = str(size_type).strip()
    if hinban is None:
        hinban = f"{normalized_size}{move_cost:011d}"
    return {
        "HINBAN": hinban,
        "サイズ種類": normalized_size,
        "NONYUHIBIN": str(nonyuhibin),
        "納入先": vendor,
        "SYUKKASAKI": vendor,
        "高さ": height,
        "移動工数": move_cost,
        "PLANKANBANSU": 1,
    }


def _assert_size1_before_size21(details):
    for _, sub in details.groupby("山通番", sort=False):
        size_types = sub["サイズ種類"].astype(str).str.strip().tolist()
        if "1" in size_types and "21" in size_types:
            first_21 = size_types.index("21")
            assert all(size == "1" for size in size_types[:first_21])
            assert all(size == "21" for size in size_types[first_21:])


def test_size1_and_size21_non_hino_can_merge_across_different_vendors():
    expanded = pd.DataFrame(
        [
            _row("1", "高岡", "07", 1000, 10),
            _row("21", "店A", "07", 1400, 9),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 1


def test_size1_and_size21_do_not_merge_when_height_exceeds_cap():
    expanded = pd.DataFrame(
        [
            _row("1", "高岡", "07", 1200, 10),
            _row("21", "店A", "08", 1300, 9),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 2


def test_cross_role_merge_is_allowed_when_only_one_side_is_hino():
    expanded = pd.DataFrame(
        [
            _row("1", "日野", "07", 1000, 10),
            _row("21", "高岡", "08", 1400, 9),
            _row("1", "高岡", "09", 1000, 8),
            _row("21", "日野", "10", 1400, 7),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 2
    for _, sub in details.groupby("山通番"):
        assert set(sub["納入先"].astype(str)) in ({"日野", "高岡"},)


def test_hino_to_hino_cross_role_merge_requires_same_vendor_and_same_bin():
    expanded_same_bin = pd.DataFrame(
        [
            _row("1", "日野", "07", 1000, 10),
            _row("21", "日野", "07", 1400, 9),
        ]
    )
    _, same_bin_details = _build_size1_mixed(expanded_same_bin, DEFAULT_HEIGHT_CAP, mixing_key=None)
    assert same_bin_details["山通番"].nunique() == 1

    expanded_diff_bin = pd.DataFrame(
        [
            _row("1", "日野", "07", 1000, 10),
            _row("21", "日野", "08", 1400, 9),
        ]
    )
    _, diff_bin_details = _build_size1_mixed(expanded_diff_bin, DEFAULT_HEIGHT_CAP, mixing_key=None)
    assert diff_bin_details["山通番"].nunique() == 2


def test_hino_and_hinoeh_do_not_merge_even_with_same_bin():
    expanded = pd.DataFrame(
        [
            _row("1", "日野", "07", 1000, 10),
            _row("21", "日野EH", "07", 1400, 9),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 2


def test_merged_stack_orders_size1_before_size21_in_size1_mixed_details():
    expanded = pd.DataFrame(
        [
            _row("21", "店A", "07", 700, 10),
            _row("21", "店A", "07", 700, 9),
            _row("1", "店A", "07", 500, 8),
            _row("1", "店A", "07", 500, 7),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    assert details["山通番"].nunique() == 1
    _assert_size1_before_size21(details)


def test_build_all_mountain_details_preserves_size1_before_size21_order():
    expanded = pd.DataFrame(
        [
            _row("21", "店A", "07", 700, 10),
            _row("21", "店A", "07", 700, 9),
            _row("1", "店A", "07", 500, 8),
            _row("1", "店A", "07", 500, 7),
        ]
    )

    _, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)
    all_details = build_all_mountain_details({}, details)

    assert all_details["山通番"].nunique() == 1
    _assert_size1_before_size21(all_details)