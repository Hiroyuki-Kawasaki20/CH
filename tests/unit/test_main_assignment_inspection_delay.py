# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pandas as pd

from src.models.constants import BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL, PROC_MAIN
from src.services.data_loader import load_pickup_time_master_xlsx
from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    _time_to_seconds,
    _calc_work_end_with_breaks,
)


def _parse_groupeddata(cell_text):
    try:
        obj = json.loads(str(cell_text))
    except Exception:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        return [obj]
    return []


def _build_proc_details_from_spo(spo_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in spo_df.iterrows():
        yama_no = int(pd.to_numeric(r.get("グループ番号", 0), errors="coerce") or 0)
        max_cost = float(pd.to_numeric(r.get("Max移動工数", 0), errors="coerce") or 0.0)
        for it in _parse_groupeddata(r.get("GroupedData", "")):
            rows.append(
                {
                    "山通番": yama_no,
                    "移動工数": max_cost,
                    "OData_納入先": str(it.get("OData_納入先", "")).strip(),
                    "納入先": str(it.get("OData_納入先", "")).strip(),
                    "NONYUHIBIN": str(it.get("NONYUHIBIN", "")).strip(),
                    "UKEIRE": str(it.get("UKEIRE", "")).strip(),
                    "OData_ストア": str(it.get("OData_ストア", "")).strip(),
                }
            )
    return pd.DataFrame(rows)


def test_yama1_is_assigned_to_main_process():
    """回帰: fixture 内の山1がメイン工程に割り当てられること。
    
    NOTE: 検査遅延ルール (order_idx >= 2 and order_idx % 2 == 0) は山1では発火しない
    (GroupedData が2項目のみで order_idx = 0,1 のため)。
    本テストは単なる通常割当の動作確認であり、検査遅延ロジック自体の検証ではない。
    """
    root = Path(__file__).resolve().parents[2]
    # Use snapshot fixtures instead of live data files
    spo_path = root / "tests" / "fixtures" / "issue42" / "spo_upload_snapshot.xlsx"
    master_path = root / "tests" / "fixtures" / "issue42" / "nyusha_master_snapshot.xlsx"

    assert spo_path.exists(), f"SPO fixture file not found: {spo_path}"
    assert master_path.exists(), f"Master fixture file not found: {master_path}"

    spo_df = pd.read_excel(spo_path)
    proc_details = _build_proc_details_from_spo(spo_df)
    master_df = load_pickup_time_master_xlsx(master_path)

    out_df, _ = assign_processes_by_arrival_time(
        proc_details=proc_details,
        master_df=master_df,
        return_lane_end_times=True,
    )

    # Note: Original test referenced yama8, but current snapshot only has yamas 1-5.
    # Using yama1 instead to verify inspection delay assignment logic works.
    # The assertion remains: verify a yama from SPO data gets assigned to "メイン" process.
    yama1 = out_df[out_df["山通番"] == 1]
    assert not yama1.empty, "山通番1が結果に存在しません"

    actual_proc = str(yama1.iloc[0]["山工程"])
    assert actual_proc == "メイン", f"expected yama1 process=メイン, got {actual_proc}"


def test_inspection_delay_rule_fires_with_synthetic_grouped_data():
    """検査遅延ルール（order_idx >= 2 and order_idx % 2 == 0）が実際に発火することを検証。
    
    Synthetic data approach:
    - GroupedData を3項目以上にして order_idx=2 で検査遅延が発火する状況を作成
    - メイン工程の順序割当で、3番目の山（order_idx=2）に 180秒の検査遅延が適用されることを確認
    - テスト検証: 山の「照合追加180秒」フラグを確認し、ルール発火有無で結果が変わることを示す
    """
    root = Path(__file__).resolve().parents[2]
    
    # Synthetic proc_details: 3 yamas to trigger inspection_delay at order_idx=2
    # All are PROC_MAIN to ensure they get sequentially scheduled
    proc_details = pd.DataFrame([
        {
            "山通番": 1,
            "移動工数": 300,
            "OData_納入先": "取引先A",
            "納入先": "取引先A",
            "NONYUHIBIN": "0101",
            "UKEIRE": "A",
            "OData_ストア": "ストア1",
        },
        {
            "山通番": 2,
            "移動工数": 300,
            "OData_納入先": "取引先A",
            "納入先": "取引先A",
            "NONYUHIBIN": "0101",
            "UKEIRE": "A",
            "OData_ストア": "ストア1",
        },
        {
            "山通番": 3,
            "移動工数": 300,
            "OData_納入先": "取引先A",
            "納入先": "取引先A",
            "NONYUHIBIN": "0101",
            "UKEIRE": "A",
            "OData_ストア": "ストア1",
        },
    ])
    
    # Synthetic master_df: simple pickup time master
    master_df = pd.DataFrame([
        {
            "OData_納入先": "取引先A",
            "NONYUHIBIN": "01",
            "入車時間": "09:00",
        },
    ])
    
    # Call assign_processes_by_arrival_time which triggers sequential scheduling
    assigned, _ = assign_processes_by_arrival_time(
        proc_details=proc_details,
        master_df=master_df,
        return_lane_end_times=True,
    )
    
    # Extract assigned processes
    # All 3 yamas should be assigned to メイン for sequential scheduling
    main_assigned = assigned[assigned["山工程"] == PROC_MAIN].sort_values("実開始時間")
    
    assert len(main_assigned) == 3, f"Expected 3 yamas in メイン process, got {len(main_assigned)}"
    
    # Verify inspection_delay rule firing pattern:
    # order_idx=0 (yama1): no delay (order_idx < 2)
    # order_idx=1 (yama2): no delay (order_idx < 2)
    # order_idx=2 (yama3): DELAY FIRES HERE (order_idx >= 2 AND order_idx % 2 == 0)
    
    # Extract 照合追加180秒 flags
    delay_flags = []
    for idx, row in main_assigned.iterrows():
        has_delay = bool(row.get("照合追加180秒", False))
        yama_no = int(row["山通番"])
        delay_flags.append((yama_no, has_delay))
    
    # Verify delay pattern
    assert len(delay_flags) == 3, f"Expected 3 delay flags, got {len(delay_flags)}"
    
    # order_idx=0 (1st in メイン): no delay expected
    yama1_no, yama1_has_delay = delay_flags[0]
    assert yama1_no == 1, f"Expected yama1 at position 0, got {yama1_no}"
    assert yama1_has_delay is False, (
        f"Yama1 (order_idx=0) should NOT have inspection delay, but 照合追加180秒={yama1_has_delay}"
    )
    
    # order_idx=1 (2nd in メイン): no delay expected
    yama2_no, yama2_has_delay = delay_flags[1]
    assert yama2_no == 2, f"Expected yama2 at position 1, got {yama2_no}"
    assert yama2_has_delay is False, (
        f"Yama2 (order_idx=1) should NOT have inspection delay, but 照合追加180秒={yama2_has_delay}"
    )
    
    # order_idx=2 (3rd in メイン): DELAY FIRES HERE (order_idx >= 2 AND order_idx % 2 == 0)
    yama3_no, yama3_has_delay = delay_flags[2]
    assert yama3_no == 3, f"Expected yama3 at position 2, got {yama3_no}"
    assert yama3_has_delay is True, (
        f"Yama3 (order_idx=2) MUST have inspection delay (rule should fire), "
        f"but 照合追加180秒={yama3_has_delay}. "
        f"This indicates the inspection_delay rule DID NOT fire correctly."
    )
