from __future__ import annotations

from pathlib import Path

from src.services import process_assigner as pa
from src.services.data_loader import load_pickup_time_master_xlsx

from tests.unit.test_relief_earliest_start import (
    _build_detail_rows_from_spo_vendor_aware,
    _compute_deadline_map,
    _compute_work_secs_by_yama,
)
from tests.unit.test_overflow_beam_vs_exhaustive import _load_input_files


def test_front_pack_declined_when_violates_other_deadline():
    spo_df, _ = _load_input_files()
    root = Path(__file__).resolve().parents[2]
    master_df = load_pickup_time_master_xlsx(root / "入車時間マスタ.xlsx")

    # 織機02の入車時間を00:14に設定する意図：
    # この値だと、山2を空き窓へ前詰めすると、照合180秒反映後の最終表示時刻で
    # 山3が締切を約27秒超過する（86707 > 86640）。
    # → 仕様②「他山を侵すなら前詰め断念・現状維持」により、山2はリリーフのまま
    #   維持されるべき。この境界値で断念経路が正しく働くことを検証する。
    mask = (
        master_df["OData_納入先"].astype(str).str.strip() == "織機"
    ) & (
        master_df["NONYUHIBIN"].astype(str).str.strip() == "02"
    )
    master_df.loc[mask, "入車時間"] = "00:14"

    details_df = _build_detail_rows_from_spo_vendor_aware(spo_df, master_df)
    proc_details = pa.compute_proc_details(details_df)
    assigned = pa.assign_processes_by_arrival_time(proc_details, master_df)

    proc_map = {
        int(r["山通番"]): str(r["山工程"])
        for _, r in assigned[["山通番", "山工程"]].drop_duplicates(subset=["山通番"]).iterrows()
    }
    start_map = {
        int(r["山通番"]): pa._to_operational_timeline_secs(pa._time_to_seconds(str(r.get("実開始時間", ""))))
        for _, r in assigned[["山通番", "実開始時間"]].drop_duplicates(subset=["山通番"]).iterrows()
    }
    work_map = _compute_work_secs_by_yama(details_df)
    deadline_map = _compute_deadline_map(details_df, master_df)

    failures = []

    # (d) 前詰めは断念され、山2は現状維持でリリーフに残るべき。
    if proc_map.get(2) != "リリーフ":
        failures.append(f"(d) expected yama2 to remain リリーフ but got {proc_map.get(2)}")

    # (e)(f) 守るべき山を含め全山 late=False
    late = []
    for yama_no, deadline in deadline_map.items():
        st = start_map.get(yama_no)
        if st is None:
            continue
        end_secs = pa._calc_work_end_with_breaks(int(st), int(work_map.get(yama_no, 0)))
        if end_secs > int(deadline):
            late.append((yama_no, int(st), int(end_secs), int(deadline)))

    if any(yama_no == 3 for yama_no, *_ in late):
        failures.append(f"(e) expected yama3 deadline to remain protected but got late={late}")
    if late:
        failures.append(f"(f) expected all yamas late=False but got {late}")

    assert not failures, "\n".join(failures)
