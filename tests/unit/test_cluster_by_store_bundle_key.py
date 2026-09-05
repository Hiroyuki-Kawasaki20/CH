import pytest

from src.services.scheduler import cluster_by_store


def test_different_mountain_and_route_rows_are_not_merged():
    rows = [
        {
            "山通番": 2,
            "ストア": "L12-C-5",
            "納入先": "高岡",
            "NONYUHIBIN": "2026090404",
            "UKEIRE": "K5",
            "HINBAN": "X",
            "SEBANGO": "111",
        },
        {
            "山通番": 7,
            "ストア": "L12-C-5",
            "納入先": "KVC",
            "NONYUHIBIN": "2026082806",
            "UKEIRE": "B7",
            "HINBAN": "Y",
            "SEBANGO": "719",
        },
    ]

    result = cluster_by_store(rows)

    assert len(result) == 2
    assert {row["SEBANGO"] for row in result} == {"111", "719"}
    assert all("_merged_rows" not in row for row in result)


def test_same_bundle_key_with_different_hinban_is_merged():
    rows = [
        {"山通番": 3, "ストア": "A", "NONYUHIBIN": "1", "UKEIRE": "B7", "納入先": "KVC", "HINBAN": "X"},
        {"山通番": 3, "ストア": "A", "NONYUHIBIN": "1", "UKEIRE": "B7", "納入先": "KVC", "HINBAN": "Y"},
    ]

    result = cluster_by_store(rows)

    assert len(result) == 1
    assert len(result[0]["_merged_rows"]) == 2
    assert len(result[0]["_merged_hinban"]) == 2


def test_missing_mountain_column_keeps_existing_merge_behavior():
    rows = [
        {"ストア": "A", "NONYUHIBIN": "1", "UKEIRE": "B7", "納入先": "KVC", "HINBAN": "X"},
        {"ストア": "A", "NONYUHIBIN": "1", "UKEIRE": "B7", "納入先": "KVC", "HINBAN": "Y"},
    ]

    result = cluster_by_store(rows)

    assert len(result) == 1
    assert len(result[0]["_merged_rows"]) == 2
