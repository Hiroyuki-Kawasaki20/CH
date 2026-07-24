# -*- coding: utf-8 -*-  
"""通常逆行（日跨ぎなし）回帰テスト — Issue #35 物証3。  
  
再現の要点（2026-07-23 23:49 SPO実データ・PR #26適用後も発生）:  
- 日野13便4山（山2,9,10,11,12が13便を含む）は締切45300秒(12:35)、  
  開始下限36240秒(10:04)が完全同一  
- うち山11だけがリリーフへ落ち、work完全同一の山9はメインに残った  
  （処理順依存の不安定性の直接証拠）  
- 総山数15 > EXHAUSTIVE_THRESHOLD(14) のためビーム探索経路を通る  
あるべき姿: 全15山メイン・リリーフゼロ（手計算で実行可能解の存在を確認済み）。  
"""  
import pandas as pd  
  
from src.services.process_assigner import (  
    compute_proc_details,  
    _legacy_assign_processes_by_arrival_time,  
    _time_to_seconds,  
    _to_operational_timeline_secs,  
    ARRIVAL_BUFFER_SECS,  
)  
from src.models.constants import PROC_MAIN  
  
MASTER_ROWS = [  
    {"OData_納入先": "6W-HO", "NONYUHIBIN": "01", "入車時間": "06:25", "セットありフラグ": ""},  
    {"OData_納入先": "6W-HO", "NONYUHIBIN": "02", "入車時間": "14:31", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "03", "入車時間": "08:15", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "04", "入車時間": "10:50", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "05", "入車時間": "14:11", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "06", "入車時間": "17:53", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "01", "入車時間": "21:34", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B7", "NONYUHIBIN": "02", "入車時間": "00:09", "セットありフラグ": ""},  
    {"OData_納入先": "フタバ岡崎", "NONYUHIBIN": "01", "入車時間": "19:55", "セットありフラグ": ""},  
    {"OData_納入先": "三栄", "NONYUHIBIN": "01", "入車時間": "07:10", "セットありフラグ": ""},  
    {"OData_納入先": "三栄", "NONYUHIBIN": "02", "入車時間": "11:25", "セットありフラグ": ""},  
    {"OData_納入先": "三栄", "NONYUHIBIN": "03", "入車時間": "17:30", "セットありフラグ": ""},  
    {"OData_納入先": "三栄", "NONYUHIBIN": "04", "入車時間": "22:00", "セットありフラグ": ""},  
    {"OData_納入先": "元町", "NONYUHIBIN": "02", "入車時間": "07:34", "セットありフラグ": ""},  
    {"OData_納入先": "元町", "NONYUHIBIN": "03", "入車時間": "13:22", "セットありフラグ": ""},  
    {"OData_納入先": "元町", "NONYUHIBIN": "04", "入車時間": "17:16", "セットありフラグ": ""},  
    {"OData_納入先": "元町", "NONYUHIBIN": "01", "入車時間": "23:19", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "08", "入車時間": "06:29", "セットありフラグ": "1"},  
    {"OData_納入先": "日野", "NONYUHIBIN": "09", "入車時間": "07:54", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "10", "入車時間": "09:02", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "11", "入車時間": "09:54", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "12", "入車時間": "12:00", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "12:45", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "14", "入車時間": "13:52", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "15", "入車時間": "14:59", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "16:59", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "18:30", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "19:39", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "21:18", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "05", "入車時間": "22:20", "セットありフラグ": ""},  
    {"OData_納入先": "日野", "NONYUHIBIN": "06", "入車時間": "23:50", "セットありフラグ": "1"},  
    {"OData_納入先": "日野", "NONYUHIBIN": "07", "入車時間": "00:24", "セットありフラグ": ""},  
    {"OData_納入先": "日野補給引取", "NONYUHIBIN": "01", "入車時間": "10:10", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "03", "入車時間": "08:30", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "04", "入車時間": "10:30", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "05", "入車時間": "12:30", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "06", "入車時間": "16:00", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "07", "入車時間": "18:15", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "08", "入車時間": "20:35", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "01", "入車時間": "23:35", "セットありフラグ": ""},  
    {"OData_納入先": "織機", "NONYUHIBIN": "02", "入車時間": "01:00", "セットありフラグ": ""},  
    {"OData_納入先": "額田広久手支給", "NONYUHIBIN": "01", "入車時間": "11:40", "セットありフラグ": ""},  
    {"OData_納入先": "額田広久手支給", "NONYUHIBIN": "02", "入車時間": "00:40", "セットありフラグ": ""},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "02", "入車時間": "07:34", "セットありフラグ": ""},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "03", "入車時間": "13:22", "セットありフラグ": ""},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "04", "入車時間": "17:16", "セットありフラグ": ""},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "01", "入車時間": "23:19", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "05", "入車時間": "08:15", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "06", "入車時間": "10:50", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "08", "入車時間": "14:11", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "01", "入車時間": "17:53", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "02", "入車時間": "21:34", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "04", "入車時間": "00:09", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "07", "入車時間": "10:50", "セットありフラグ": ""},  
    {"OData_納入先": "KVC-B3", "NONYUHIBIN": "03", "入車時間": "21:34", "セットありフラグ": ""},  
]  
  
  
def _rows(yama, vendor, nony, cost, n, ukeire=""):  
    return [  
        {"山通番": yama, "移動工数": cost, "納入先": vendor,  
         "NONYUHIBIN": nony, "UKEIRE": ukeire, "高さ": 300}  
        for _ in range(n)  
    ]  
  
  
# 2026-07-23 23:49 SPO実データの15グループを忠実に再現  
# （移動工数は各グループのMax移動工数を全パレットに適用。工数式はmaxのみ参照のため等価）  
DETAIL_ROWS = (  
    _rows(1, "元町", "2026072003", 313.7401, 1) + _rows(1, "高岡", "2026072003", 313.7401, 2)  
    + _rows(2, "元町", "2026072003", 72.914, 1) + _rows(2, "日野", "2026072013", 72.914, 2)  
    + _rows(3, "元町", "2026072003", 182.97, 1)  
    + _rows(4, "高岡", "2026072003", 16.6501, 3)  
    + _rows(5, "KVC", "2026072005", 346.5, 2, "B7") + _rows(5, "織機", "2026072005", 346.5, 2)  
    + _rows(6, "日野", "2026072014", 313.7402, 2) + _rows(6, "KVC", "2026072005", 313.7402, 1, "B7")  
    + _rows(7, "織機", "2026072005", 16.65, 1)  
    + _rows(8, "日野", "2026072014", 313.7402, 3) + _rows(8, "KVC", "2026072008", 313.7402, 1, "B3")  
    + _rows(9, "日野", "2026072013", 72.916, 2)  
    + _rows(10, "日野", "2026072013", 72.911, 3)  
    + _rows(11, "日野", "2026072013", 72.904, 2)  
    + _rows(12, "日野", "2026072013", 72.917, 1)  
    + _rows(13, "日野", "2026072014", 72.916, 2)  
    + _rows(14, "日野", "2026072014", 72.91, 3)  
    + _rows(15, "日野", "2026072014", 72.918, 1)  
)  
  
HINO13_YAMAS = (2, 9, 10, 11, 12)  # 日野13便を含む山  
ALL_YAMAS = tuple(range(1, 16))  
  
  
def _run_assignment():  
    details = pd.DataFrame(DETAIL_ROWS)  
    proc_details = compute_proc_details(details)  
    master_df = pd.DataFrame(MASTER_ROWS)  
    return _legacy_assign_processes_by_arrival_time(proc_details, master_df)  
  
  
def _proc_by_yama(result):  
    assert isinstance(result, pd.DataFrame), f"result must be DataFrame, got {type(result)}"  
    return {int(r["山通番"]): str(r["山工程"]) for _, r in result.iterrows()}  
  
  
class TestHino13NormalRegression:  
    def test_premise_no_daycross_axis(self):  
        """再現忠実性: 日野13便は締切45300(12:35)・開始下限36240(10:04)、日跨ぎなし。"""  
        d13 = _to_operational_timeline_secs(_time_to_seconds("12:45")) - ARRIVAL_BUFFER_SECS  
        floor13 = _to_operational_timeline_secs(_time_to_seconds("09:54")) + ARRIVAL_BUFFER_SECS  
        assert d13 == 45300  
        assert floor13 == 36240  
  
    def test_premise_beam_search_scale(self):  
        """再現忠実性: 総山数15 > EXHAUSTIVE_THRESHOLD(14) → ビーム探索経路。"""  
        details = pd.DataFrame(DETAIL_ROWS)  
        assert details["山通番"].nunique() == 15  
  
    def test_hino13_yamas_should_all_be_main(self):  
        """物証3の核心: 日野13便5山は全山メイン（実データでは山11相当がリリーフ落ち）。"""  
        proc = _proc_by_yama(_run_assignment())  
        for yama in HINO13_YAMAS:  
            assert proc.get(yama) == PROC_MAIN, (  
                f"山{yama}(日野13便) expected メイン but got {proc.get(yama)!r} / 全体={proc}"  
            )  
  
    def test_all_yamas_should_be_main(self):  
        """あるべき姿: 全15山メイン（手計算で実行可能解の存在確認済み。実データはリリーフ6山）。"""  
        proc = _proc_by_yama(_run_assignment())  
        for yama in ALL_YAMAS:  
            assert proc.get(yama) == PROC_MAIN, (  
                f"山{yama} expected メイン but got {proc.get(yama)!r} / 全体={proc}"  
            )  