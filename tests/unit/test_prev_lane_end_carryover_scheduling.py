# -*- coding: utf-8 -*-
"""Issue #83: 前回仕分けの終了時刻(previous_lane_end_times)の引継ぎ検証。

連続で仕分けを実行したとき、各レーン（メイン/リリーフ）の山は、
同一レーンの「前回仕分けの最終終了時刻」より前に開始してはならない
（作業者は前回の作業が終わるまで次の山に着手できないため）。

従来は初期割当でのみ前回終了時刻を参照しており、T0シフト・探索
（_reschedule_rows → _schedule_proc_rows）の再計算で prev_end=0 から
組み直されるため、前回終了時刻が最終出力で失われていた。
"""

import pandas as pd

from src.models.constants import (
    BASE_ONE_TIME,
    BASE_PER_PAL,
    PROC_MAIN,
    PROC_OVERFLOW,
    PROC_RELIEF,
    SPLIT_UKEIRE_ROUTES,
)
from src.services.process_assigner import assign_processes_by_arrival_time

_VENDOR = "テスト"


def _secs(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 3600 + int(mm) * 60


def _start_secs(row) -> int:
    return _secs(str(row["実開始時間"]))


def _master(rows) -> pd.DataFrame:
    """セットありフラグ列なし（旧マスタ形式）→ 前便入車+10分ルールが適用される。"""
    return pd.DataFrame(rows, columns=["OData_納入先", "NONYUHIBIN", "入車時間"])


def _proc_details(mountains) -> pd.DataFrame:
    """mountains: [(山通番, 便2桁, 移動工数), ...]。1山=1パレット構成。"""
    rows = []
    for yama, bin2, cost in mountains:
        rows.append(
            {
                "山通番": yama,
                "納入先": _VENDOR,
                "NONYUHIBIN": f"20260819{bin2}",
                "移動工数": cost,
            }
        )
    return pd.DataFrame(rows)


def _work_secs_1pal(cost: float) -> int:
    """1パレット山の引取工数（秒）。"""
    return int(round(cost + BASE_ONE_TIME + BASE_PER_PAL))


def test_precondition_vendor_is_not_split_route():
    """前提: テスト用納入先が UKEIRE 分割対象でない（マスタキーが素の納入先名）。"""
    assert _VENDOR not in SPLIT_UKEIRE_ROUTES


def test_main_lane_respects_previous_main_end_time():
    """メイン山は前回メイン終了時刻(13:00)より前に開始してはならない。

    山1: 02便（入車12:00 → 締切11:50、開始下限=01便10:00+10分=10:10）。
    前回メイン終了が13:00のため、メインでは締切11:50に間に合わない。
    「10:10からメインで開始」は前回作業を無視した誤りであり、
    リリーフまたはあふれへ退避されるべき。
    """
    master = _master(
        [
            (_VENDOR, "01", "10:00"),
            (_VENDOR, "02", "12:00"),
        ]
    )
    proc = _proc_details([(1, "02", 60)])
    prev = {PROC_MAIN: _secs("13:00"), PROC_RELIEF: 0, PROC_OVERFLOW: 0}

    out = assign_processes_by_arrival_time(
        proc, master, previous_lane_end_times=prev
    )

    assert not out.empty
    for _, r in out.iterrows():
        if str(r["山工程"]) == PROC_MAIN:
            assert _start_secs(r) >= _secs("13:00"), (
                f"山{int(r['山通番'])}が前回メイン終了(13:00)より前に開始: "
                f"{r['実開始時間']}"
            )


def test_relief_lane_respects_previous_relief_end_time():
    """リリーフ山は前回リリーフ終了時刻(13:00)より前に開始してはならない。

    山1・山2: いずれも02便（入車12:10 → 締切12:00、開始下限10:10）。
    前回メイン終了11:45のためメインには1山しか収まらず、残る1山は
    リリーフ候補となるが、前回リリーフ終了13:00より前には開始できない
    （間に合わない場合はあふれへ退避されるべき）。
    """
    master = _master(
        [
            (_VENDOR, "01", "10:00"),
            (_VENDOR, "02", "12:10"),
        ]
    )
    base = _work_secs_1pal(0)
    cost = max(60, 840 - base)  # 引取工数がおよそ14分になるよう調整
    proc = _proc_details([(1, "02", cost), (2, "02", cost)])
    prev = {
        PROC_MAIN: _secs("11:45"),
        PROC_RELIEF: _secs("13:00"),
        PROC_OVERFLOW: 0,
    }

    out = assign_processes_by_arrival_time(
        proc, master, previous_lane_end_times=prev
    )

    assert not out.empty
    for _, r in out.iterrows():
        proc_label = str(r["山工程"])
        if proc_label == PROC_MAIN:
            assert _start_secs(r) >= _secs("11:45"), (
                f"山{int(r['山通番'])}が前回メイン終了(11:45)より前に開始: "
                f"{r['実開始時間']}"
            )
        if proc_label == PROC_RELIEF:
            assert _start_secs(r) >= _secs("13:00"), (
                f"山{int(r['山通番'])}が前回リリーフ終了(13:00)より前に開始: "
                f"{r['実開始時間']}"
            )


def test_no_carryover_keeps_existing_behavior():
    """後方互換: 前回終了時刻を全レーン0で渡した結果は、引数省略時と完全一致する。

    （注: 当初は「全山メインに収まる」を期待していたが、現行の探索は
    メインに収まる場合でも山をリリーフへ分散させることがあると判明。
    これは #83 とは無関係の既存挙動のため、本テストは「床0の明示指定が
    既存挙動を一切変えない」ことの等価比較に改めた）
    """
    master = _master(
        [
            (_VENDOR, "01", "10:00"),
            (_VENDOR, "02", "12:10"),
        ]
    )
    base = _work_secs_1pal(0)
    cost = max(60, 840 - base)
    proc = _proc_details([(1, "02", cost), (2, "02", cost)])

    out_default = assign_processes_by_arrival_time(proc.copy(), master.copy())
    out_zero = assign_processes_by_arrival_time(
        proc.copy(),
        master.copy(),
        previous_lane_end_times={
            PROC_MAIN: 0,
            PROC_RELIEF: 0,
            PROC_OVERFLOW: 0,
        },
    )

    key_cols = ["山通番", "山工程", "実開始時間"]
    a = out_default[key_cols].sort_values("山通番").reset_index(drop=True)
    b = out_zero[key_cols].sort_values("山通番").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)