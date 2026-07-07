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