# -*- coding: utf-8 -*-  
"""課題③: _try_front_pack_to_main_idle_gap の前詰め救済が機能することを検証する。  
  
破損行（rr.get("山通番") == ""）の状態では main_rows が常に空になり  
前詰め救済が無効化されるため、本テストはFAILする（fail先行）。  
修正（rr.get("山工程") == PROC_MAIN）後にPASSする。  
"""  
import pandas as pd  
  
from src.services.process_assigner import assign_processes_by_arrival_time  
from src.models.constants import PROC_MAIN  
  
  
def _build_fixture():  
    # 入車時間マスタ（セットありフラグ列なし＝旧マスタ経路で単純化）  
    # 便03は山を持たないが、山3(便04)の開始下限13:10（>締切13:05）を作るために必要  
    master_df = pd.DataFrame([  
        {"OData_納入先": "テスト", "NONYUHIBIN": "01", "入車時間": "08:00"},  
        {"OData_納入先": "テスト", "NONYUHIBIN": "02", "入車時間": "12:30"},  
        {"OData_納入先": "テスト", "NONYUHIBIN": "03", "入車時間": "13:00"},  
        {"OData_納入先": "テスト", "NONYUHIBIN": "04", "入車時間": "13:15"},  
    ])  
    proc_details = pd.DataFrame([  
        {"山通番": 1, "納入先": "テスト", "NONYUHIBIN": "01", "移動工数": 60},  
        {"山通番": 2, "納入先": "テスト", "NONYUHIBIN": "02", "移動工数": 60},  
        {"山通番": 3, "納入先": "テスト", "NONYUHIBIN": "04", "移動工数": 60},  
    ])  
    return proc_details, master_df  
  
  
def test_front_pack_rescues_into_main_idle_gap():  
    proc_details, master_df = _build_fixture()  
    out = assign_processes_by_arrival_time(proc_details, master_df)  
    procs = dict(zip(out["山通番"].astype(int), out["山工程"].astype(str)))  
  
    # 山3は逐次配置では開始下限(13:10)が締切(13:05)より遅く必ず間に合わないが、  
    # メインの空き窓（山1終了〜山2開始下限08:10）へ前詰めすれば救済できる。  
    assert procs.get(3) == PROC_MAIN, (  
        f"山3が前詰め救済されていません（実際: {procs.get(3)}）。"  
        "_try_front_pack_to_main_idle_gap の main_rows フィルタ破損の疑い。"  
    )  
    # 前詰め採用なら山3の開始は山2の開始下限(08:10)より前のはず  
    yama3_start = str(out.loc[out["山通番"] == 3, "実開始時間"].iloc[0])  
    assert yama3_start < "08:10", f"山3の開始が空き窓内にありません: {yama3_start}"  
