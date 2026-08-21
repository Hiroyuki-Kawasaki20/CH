"""Issue #87: 前回終了時刻の履歴が空でも、深夜起点のスケジュールを作らないこと。

previous_lane_end_times=None（初回起動・履歴クリア直後）で 16 山（EDF 比較が
発動する規模）を割り付けたとき、EDF 経路がレーン床 0 のまま候補を作り、
1 直開始（06:25）より前に開始する空想スケジュールを採用してしまう不具合の再現。
"""

import pandas as pd
import pytest

from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW
from src.services.process_assigner import assign_processes_by_arrival_time

_FIRST_SHIFT_START_SECS = 6 * 3600 + 25 * 60  # 06:25
_DEEP_NIGHT_LIMIT_SECS = 5 * 3600  # 05:00 未満は深夜起点とみなす


def _hhmm_to_secs(value):
    s = str(value).strip()
    hh, mm = s.split(":")
    return int(hh) * 3600 + int(mm) * 60


def _build_frames():
    # 06:25 〜 11:00 を 16 便に配分（全て 1 直）
    start = _FIRST_SHIFT_START_SECS
    end = 11 * 3600
    step = (end - start) // 15
    pickups = [start + step * i for i in range(16)]

    master_df = pd.DataFrame([
        {
            "OData_納入先": "テスト拠点",
            "NONYUHIBIN": f"{i + 1:02d}",
            "入車時間": f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}",
            "セットありフラグ": "",
        }
        for i, secs in enumerate(pickups)
    ])

    proc_details = pd.DataFrame([
        {
            "山通番": i + 1,
            "納入先": "テスト拠点",
            "NONYUHIBIN": f"{i + 1:02d}",
            "移動工数": 300,
        }
        for i in range(16)
    ])
    return proc_details, master_df


def _build_single_bin_frames():
    """各山が別納入先の単独便（前便なし＝開始時間_秒が 0 になる）16山。"""
    start = _FIRST_SHIFT_START_SECS
    step = (11 * 3600 - start) // 15
    master_df = pd.DataFrame([
        {
            "OData_納入先": f"拠点{i + 1:02d}",
            "NONYUHIBIN": "01",
            "入車時間": f"{(start + step * i) // 3600:02d}:{((start + step * i) % 3600) // 60:02d}",
        }
        for i in range(16)
    ])
    proc_details = pd.DataFrame([
        {
            "山通番": i + 1,
            "納入先": f"拠点{i + 1:02d}",
            "NONYUHIBIN": "01",
            "移動工数": 300,
        }
        for i in range(16)
    ])
    return proc_details, master_df


def test_empty_history_does_not_schedule_before_first_shift_start():
    proc_details, master_df = _build_frames()

    out_df, lane_end_times = assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times=None,
        return_lane_end_times=True,
    )

    _assert_after_first_shift(out_df, lane_end_times)


def test_garbage_lane_floor_does_not_schedule_before_first_shift_start():
    """1直開始前のゴミ床が履歴に残っていても、解禁時刻より前には着手しない。"""
    proc_details, master_df = _build_frames()

    out_df, lane_end_times = assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times={PROC_MAIN: 900, PROC_RELIEF: 780, PROC_OVERFLOW: 900},
        return_lane_end_times=True,
    )

    _assert_after_first_shift(out_df, lane_end_times)


def test_garbage_lane_floor_with_no_prev_bin_avoids_deep_night():
    """Issue #87 スコープ: 前便が無く山床 0 の山でも、深夜起点にならない。"""
    proc_details, master_df = _build_single_bin_frames()

    out_df, lane_end_times = assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times={PROC_MAIN: 900, PROC_RELIEF: 780, PROC_OVERFLOW: 900},
        return_lane_end_times=True,
    )

    for _, row in out_df.iterrows():
        start_secs = _hhmm_to_secs(row["実開始時間"])
        assert start_secs >= _DEEP_NIGHT_LIMIT_SECS, (
            f"山{int(row['山通番'])}({row['山工程']}): 実開始時間 {row['実開始時間']} が深夜帯"
        )

    for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        end_secs = int(lane_end_times.get(lane, 0) or 0)
        if end_secs == 0:
            continue  # 未使用レーン
        assert end_secs >= _FIRST_SHIFT_START_SECS, (
            f"{lane}: lane_end_times={end_secs} が 1直開始 06:25({_FIRST_SHIFT_START_SECS}) より前"
        )


@pytest.mark.xfail(
    reason="Issue #93: 通常経路の前倒し(T0シフト/front-pack)が解禁床を無視する",
    strict=True,
)
def test_garbage_lane_floor_with_no_prev_bin_respects_release_time():
    """前便が無く山床が 0 の山でも、ゴミ床の下で解禁時刻(06:25)以降に着手する。"""
    proc_details, master_df = _build_single_bin_frames()

    out_df, lane_end_times = assign_processes_by_arrival_time(
        proc_details,
        master_df,
        previous_lane_end_times={PROC_MAIN: 900, PROC_RELIEF: 780, PROC_OVERFLOW: 900},
        return_lane_end_times=True,
    )

    _assert_after_first_shift(out_df, lane_end_times)


def _assert_after_first_shift(out_df, lane_end_times):
    # (a) 全山の実開始時間が 1 直開始（06:25）以降であること
    for _, row in out_df.iterrows():
        start_secs = _hhmm_to_secs(row["実開始時間"])
        assert start_secs >= _FIRST_SHIFT_START_SECS, (
            f"山{int(row['山通番'])}({row['山工程']}): 実開始時間 {row['実開始時間']} が "
            f"1直開始 06:25 より前"
        )

    # (b) lane_end_times に 1 直開始前の秒数（深夜相当）が入らないこと
    for lane in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        end_secs = int(lane_end_times.get(lane, 0) or 0)
        if end_secs == 0:
            continue  # 未使用レーン
        assert end_secs >= _FIRST_SHIFT_START_SECS, (
            f"{lane}: lane_end_times={end_secs} が 1直開始 06:25({_FIRST_SHIFT_START_SECS}) より前"
        )
