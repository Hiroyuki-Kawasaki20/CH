"""Regression tests for SPO pickup start time attachment."""

import json

import pandas as pd

from src.services.exporter import attach_pickup_start_time


def test_attach_pickup_start_time_prefers_earliest_candidate_for_mixed_hino_bins():
    spo_df = pd.DataFrame(
        [
            {
                "GroupedData": json.dumps(
                    [
                        {"OData_納入先": "日野", "NONYUHIBIN": "2026060101"},
                        {"OData_納入先": "日野", "NONYUHIBIN": "2026060115"},
                    ],
                    ensure_ascii=False,
                ),
                "引取開始時間": "",
            }
        ]
    )
    master_df = pd.DataFrame(
        [
            {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "06:50"},
            {"OData_納入先": "日野", "NONYUHIBIN": "15", "入車時間": "23:40"},
        ]
    )

    result = attach_pickup_start_time(spo_df, master_df)

    assert str(result.at[0, "引取開始時間"]) == "07:00"


def test_attach_pickup_start_time_uses_split_vendor_prev_bin_for_motomachi():
    spo_df = pd.DataFrame(
        [
            {
                "GroupedData": json.dumps(
                    [
                        {
                            "OData_納入先": "元町",
                            "NONYUHIBIN": "2026060102",
                            "UKEIRE": "1W",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "引取開始時間": "",
            }
        ]
    )
    master_df = pd.DataFrame(
        [
            {"OData_納入先": "元町-1W", "NONYUHIBIN": "01", "入車時間": "08:00"},
            {"OData_納入先": "元町-1W", "NONYUHIBIN": "02", "入車時間": "09:00"},
            # 誤参照を検知するため、素名には異なる時刻を置く
            {"OData_納入先": "元町", "NONYUHIBIN": "01", "入車時間": "05:00"},
            {"OData_納入先": "元町", "NONYUHIBIN": "02", "入車時間": "06:00"},
        ]
    )

    result = attach_pickup_start_time(spo_df, master_df)

    # prev_bin=01 を 元町-1W で引いて 08:00+10分 が採用されること
    assert str(result.at[0, "引取開始時間"]) == "08:10"


def test_attach_pickup_start_time_records_lookup_vendor_for_unmatched_split_row(tmp_path):
    spo_df = pd.DataFrame(
        [
            {
                "GroupedData": json.dumps(
                    [
                        {
                            "OData_納入先": "元町",
                            "NONYUHIBIN": "2026060102",
                            "UKEIRE": "9P",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "引取開始時間": "",
            }
        ]
    )
    master_df = pd.DataFrame(
        [
            # split vendor 自体は存在するが対象便(02)は未登録
            {"OData_納入先": "元町-9P", "NONYUHIBIN": "01", "入車時間": "07:30"},
        ]
    )
    unmatched_csv_path = tmp_path / "unmatched.csv"

    _ = attach_pickup_start_time(spo_df, master_df, unmatched_csv_path=unmatched_csv_path)

    unmatched = pd.read_csv(unmatched_csv_path, encoding="utf-8-sig")
    assert int(unmatched.iloc[0]["index"]) == 0
    assert str(unmatched.iloc[0]["vendor"]) == "元町-9P"
    assert int(unmatched.iloc[0]["order2"]) == 2