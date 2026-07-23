# -*- coding: utf-8 -*-  
"""  
fail先行テスト: 高岡01便（便番号最小）の山が深夜0時起点(00:xx)で  
割り付けられる不具合の最小再現。  
  
業務仕様: 便番号は循環しており、01便の前便は最大便番号の便（高岡なら04便17:16）。  
よって01便の引取開始は04便入車(17:16)以降〜締切(23:09)以前の実時間帯であるべき。  
現HEAD(96cc99f)では前便解決がwrap不許可のため start_floor=0 となり、  
実開始時間が 00:00 台となって本テストは【失敗＝赤】想定。  
修正後（wrap解禁＋軸補正）は 17:16〜23:09 の実時間帯となり【成功＝緑】想定。  
※本テストは追加のみ。既存コード・既存テストの変更を含まない。  
"""  
import pandas as pd  
  
from src.services.process_assigner import (  
    assign_processes_by_arrival_time,  
    _time_to_seconds,  
)  
  
# 入車時間マスタ実値（確定値）: 高岡 01便=23:19 が便番号最小  
TAKAOKA_MASTER = pd.DataFrame([  
    {"OData_納入先": "高岡", "NONYUHIBIN": "02", "入車時間": "07:34"},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "03", "入車時間": "13:22"},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "04", "入車時間": "17:16"},  
    {"OData_納入先": "高岡", "NONYUHIBIN": "01", "入車時間": "23:19"},  
])  
  
  
def _build_proc_details() -> pd.DataFrame:  
    # 1山のみ・高岡01便のみ（混載なし）の最小構成。移動工数は実データ相当値。  
    return pd.DataFrame([  
        {"山通番": 1, "納入先": "高岡", "NONYUHIBIN": "01", "移動工数": 16.6501},  
        {"山通番": 1, "納入先": "高岡", "NONYUHIBIN": "01", "移動工数": 12.0},  
        {"山通番": 1, "納入先": "高岡", "NONYUHIBIN": "01", "移動工数": 10.0},  
    ])  
  
  
def test_takaoka_bin01_start_must_not_be_midnight_origin():  
    out = assign_processes_by_arrival_time(_build_proc_details(), TAKAOKA_MASTER)  
    row = out[out["山通番"] == 1].iloc[0]  
    start_str = str(row["実開始時間"]).strip()  
    start_secs = _time_to_seconds(start_str)  
  
    print(f"[EVIDENCE] 山工程={row.get('山工程')} 実開始時間={start_str!r}")  
  
    assert start_secs is not None, f"実開始時間が空: {row.to_dict()}"  
  
    prev_bin_arrival = _time_to_seconds("17:16")          # 前便=04便の入車  
    deadline_2309 = _time_to_seconds("23:19") - 10 * 60   # 締切 23:09（当日軸）  
  
    # 【本丸】01便の前便は最大便番号(04便17:16)。開始は 17:16〜23:09 であるべき。  
    # 生の秒数で判定する（00:00=0秒 は運用タイムライン化すると24:00に化けて  
    # 誤PASSするため、意図的に生値で比較する）。  
    assert prev_bin_arrival <= start_secs <= deadline_2309, (  
        f"start_floor=0 が絶対時刻0:00として扱われている疑い: 実開始時間={start_str}"  
    )  
