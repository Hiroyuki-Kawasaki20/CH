import json
import pytest
from src.services import exporter


class TestDisplayHhmm24h:
    """Issue #44-1: 深夜0時跨ぎの 00:xx 表記を 24:xx 表記へ統一する。"""

    def test_helper_exists(self):
        assert hasattr(exporter, "_to_display_hhmm_24h")

    @pytest.mark.parametrize(
        "src,expected",
        [
            ("00:09", "24:09"),
            ("00:40", "24:40"),
            ("01:30", "25:30"),
            ("02:59", "26:59"),
            ("03:00", "03:00"),
            ("07:40", "07:40"),
            ("24:00", "24:00"),
            ("24:09", "24:09"),
            ("", ""),
            ("00:00", "24:00"),
        ],
    )
    def test_conversion(self, src, expected):
        assert exporter._to_display_hhmm_24h(src) == expected


import pandas as pd


class TestAttachPickupStartTime24h:
    """Issue #44-1: attach_pickup_start_time が GroupedData 経由で 24h 表記を書き込む。"""

    def _master(self, pickup):
        return pd.DataFrame(
            [{"OData_納入先": "TESTV", "NONYUHIBIN": "01", "入車時間": pickup}]
        )

    def _spo(self, existing):
        gd = json.dumps(
            [{"OData_納入先": "TESTV", "NONYUHIBIN": "01"}], ensure_ascii=False
        )
        return pd.DataFrame([{"GroupedData": gd, "引取開始時間": existing}])

    def test_master_midnight_value_is_written_as_24h(self):
        out = exporter.attach_pickup_start_time(self._spo(""), self._master("00:09"))
        got = str(out.at[0, "引取開始時間"]).strip()
        assert got == "24:19", f"expected 24:19 but got {got!r}"

    def test_daytime_value_is_unchanged(self):
        out = exporter.attach_pickup_start_time(self._spo(""), self._master("07:30"))
        assert str(out.at[0, "引取開始時間"]).strip() == "07:40"

    def test_existing_value_is_not_overwritten(self):
        out = exporter.attach_pickup_start_time(self._spo("07:40"), self._master("00:09"))
        assert str(out.at[0, "引取開始時間"]).strip() == "07:40"
