# -*- coding: utf-8 -*-
"""日跨ぎ締切の軸不一致(日野07便リリーフ落ち)回帰テスト。

再現の要点:
- 08便(セットあり)の開始下限は同レーン前便(06便=23:50)+10分=24:00(86400秒)
- 08便の締切22740(当日軸)が生のままソートに使われ07便(87240)より先に
  メインを占有し、07便がリリーフへ落ちる(バグ)
あるべき姿: 07便3山が先にメインで処理され、全7山メイン・リリーフゼロ。
"""
import pandas as pd

from src.services.process_assigner import (
    compute_proc_details,
    _legacy_assign_processes_by_arrival_time,
    _time_to_seconds,
    _to_operational_timeline_secs,
    ARRIVAL_BUFFER_SECS,
    DAY_SECS,
)
from src.models.constants import PROC_MAIN


MASTER_ROWS = [
    {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "21:30", "セットありフラグ": "0"},
    {"OData_納入先": "日野", "NONYUHIBIN": "06", "入車時間": "23:50", "セットありフラグ": "0"},
    {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "00:24", "セットありフラグ": "0"},
    {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "06:29", "セットありフラグ": "1"},
]

DETAIL_ROWS = (
    [{"山通番": i, "移動工数": 600, "納入先": "日野", "NONYUHIBIN": "2026070707", "高さ": 300} for i in (1, 2, 3)]
    + [{"山通番": i, "移動工数": 600, "納入先": "日野", "NONYUHIBIN": "2026070708", "高さ": 300} for i in (4, 5, 6, 7)]
)


def _run_assignment():
    details = pd.DataFrame(DETAIL_ROWS)
    proc_details = compute_proc_details(details)
    master_df = pd.DataFrame(MASTER_ROWS)
    return _legacy_assign_processes_by_arrival_time(proc_details, master_df)


def _proc_by_yama(result):
    assert isinstance(result, pd.DataFrame), f"result must be DataFrame, got {type(result)}"
    mapping = {}
    for _, row in result.iterrows():
        mapping[int(row["山通番"])] = str(row["山工程"])
    return mapping


class TestHinoDayCrossDeadline:
    def test_premise_deadlines_cross_day_axis(self):
        """再現忠実性: 07便締切=87240(翌日軸), 08便締切=22740(当日軸)。"""
        d07 = _to_operational_timeline_secs(_time_to_seconds("00:24")) - ARRIVAL_BUFFER_SECS
        d08 = _to_operational_timeline_secs(_time_to_seconds("06:29")) - ARRIVAL_BUFFER_SECS
        assert d07 == 87240
        assert d08 == 22740
        assert d07 >= DAY_SECS
        assert d08 < DAY_SECS

    def test_premise_hino08_starts_after_daycross(self):
        """再現忠実性: 08便4山は全てメイン。"""
        proc = _proc_by_yama(_run_assignment())
        for yama in (4, 5, 6, 7):
            assert proc.get(yama) == PROC_MAIN, (
                f"山{yama}(08便) expected メイン but got {proc.get(yama)!r}"
            )

    def test_hino07_all_yamas_should_be_main(self):
        """あるべき姿: 07便3山もメイン(バグがあればリリーフに落ちてFAILする)。"""
        proc = _proc_by_yama(_run_assignment())
        for yama in (1, 2, 3):
            assert proc.get(yama) == PROC_MAIN, (
                f"山{yama}(07便) expected メイン but got {proc.get(yama)!r}"
            )
