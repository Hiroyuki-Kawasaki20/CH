# -*- coding: utf-8 -*-
"""Issue #201: 休憩と山全体の工数で間に合わない混載を実際に分離する。"""

import logging

import numpy as np
import pandas as pd
import pytest

from src.models.constants import BASE_ONE_TIME, BASE_PER_PAL, DEFAULT_HEIGHT_CAP, MIDDLE_WORK
from src.services.bin_time_rules import build_bin_time_map, unit_floor_deadline
from src.services import sorter
from src.services.process_assigner import (
    _adjust_start_for_breaks, _calc_work_end_with_breaks, _time_to_seconds,
    assign_processes_by_arrival_time, compute_proc_details,
)
from src.services.sorter import (
    _build_size1_mixed, _needs_mixed_deadline_rescue,
    build_all_mountain_details, run_pipeline,
)


class _StubDataManager:
    def __init__(self, shipments):
        self.shipments = shipments

    def filter_shipments(self, selections):
        return self.shipments.copy()


def _secs(h, m=0, s=0):
    return h * 3600 + m * 60 + s


def _case(vendor="豊鉄広久手"):
    if vendor == "豊鉄広久手":
        vendor_rows = [("豊鉄広久手", "01", "00:40"), ("豊鉄広久手", "02", "11:40")]
        order = "02"
    else:
        vendor_rows = [("日野", "10", "09:25"), ("日野", "11", "11:06"), ("日野", "12", "12:05")]
        order = "12"
    master = pd.DataFrame([
        {"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}
        for v, b, t in vendor_rows + [
            ("織機-28", "03", "08:30"),
            ("織機-28", "04", "10:30"),
            ("織機-28", "05", "12:30"),
        ]
    ])
    shipments = pd.DataFrame([
        {
            "HINBAN": f"TEST{i}", "サイズ種類": "1",
            "NONYUHIBIN": f"20261016{b}", "納入先": v, "SYUKKASAKI": v,
            "UKEIRE": u, "高さ": 700, "移動工数": move,
            "PLANKANBANSU": 1, "ストア": store,
        }
        for i, (v, b, u, move, store) in enumerate([
            (vendor, order, "07", 72.9, "C15-A-1"),
            ("織機", "05", "28", 313.74, "C15-A-3"),
            ("織機", "05", "28", 313.74, "C15-A-3"),
        ])
    ])
    return shipments, master


def _run(shipments, master):
    return run_pipeline(
        _StubDataManager(shipments), selections=None,
        height_cap=DEFAULT_HEIGHT_CAP, mixing_key="UKEIRE", master_df=master,
    )


def _assert_split(details, vendor):
    urgent = details.loc[details["納入先"] == vendor]
    orihata = details.loc[details["納入先"] == "織機"]
    assert len(details) == 3
    assert len(urgent) == 1 and len(orihata) == 2
    assert orihata["山通番"].nunique() == 1
    assert set(urgent["山通番"]).isdisjoint(set(orihata["山通番"])), (
        details[["納入先", "NONYUHIBIN", "高さ", "山通番"]].to_string(index=False)
    )


@pytest.mark.parametrize("vendor", ["豊鉄広久手", "日野"])
@pytest.mark.parametrize("legacy", [False, True], ids=["normal", "legacy"])
def test_break_aware_rescue_splits_urgent_vendor(vendor, legacy):
    shipments, master = _case(vendor)
    _, expanded, _, _, summary, details = _run(shipments, master)
    if legacy:
        summary, details = _build_size1_mixed(
            expanded, DEFAULT_HEIGHT_CAP, "UKEIRE", master_df=master, _legacy=True,
        )
    btm = build_bin_time_map(master)
    floor, deadline = unit_floor_deadline(
        "織機", "2026101605", "12:30", btm, ukeire="28",
    )
    assert (floor, deadline) == (_secs(10, 40), _secs(12, 20))
    _assert_split(details, vendor)
    assert summary["パレット数"].sum() == 3
    for name, work in [(vendor, 253), ("織機", 549)]:
        yama = details.loc[details["納入先"] == name, "山通番"].iloc[0]
        row = summary.set_index("山通番").loc[yama]
        assert row["パレット数"] == (1 if name == vendor else 2)
        assert row["引取工数"] == work


@pytest.mark.parametrize("legacy", [False, True], ids=["normal", "legacy"])
def test_short_break_five_second_overrun_splits_mixed_mountain(legacy):
    master = pd.DataFrame([
        {"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}
        for v, b, t in [
            ("拠点A", "06", "13:00"), ("拠点A", "07", "13:30"),
            ("拠点C", "01", "14:00"),
        ]
    ])
    shipments = pd.DataFrame([
        {
            "HINBAN": f"SHORT{i}", "サイズ種類": "1",
            "NONYUHIBIN": f"20261016{order}", "納入先": vendor, "SYUKKASAKI": vendor,
            "UKEIRE": "", "高さ": height, "移動工数": move, "PLANKANBANSU": 1,
        }
        for i, (vendor, order, height, move) in enumerate([
            ("拠点A", "07", 1000, 10), ("拠点C", "01", 1200, 9),
        ])
    ])
    bounds = [
        unit_floor_deadline(row["納入先"], row["NONYUHIBIN"], "", build_bin_time_map(master))
        for _, row in shipments.iterrows()
    ]
    floor = max(f for f, _ in bounds)
    deadline = min(d for _, d in bounds if d is not None)
    work = int(np.round(
        shipments["移動工数"].max() + BASE_ONE_TIME
        + (len(shipments) - 1) * MIDDLE_WORK + len(shipments) * BASE_PER_PAL, 0,
    ))
    assert work == 245
    assert (floor, deadline) == (_secs(13, 10), _secs(13, 20))
    start = _adjust_start_for_breaks(floor, work)
    finish = _calc_work_end_with_breaks(start, work)
    assert start == _secs(13, 16)
    assert finish == _secs(13, 20, 5)
    assert finish - deadline == 5

    _, expanded, _, _, summary, details = _run(shipments, master)
    if legacy:
        summary, details = _build_size1_mixed(
            expanded, DEFAULT_HEIGHT_CAP, "UKEIRE", master_df=master, _legacy=True,
        )
    a_yamas = set(details.loc[details["納入先"] == "拠点A", "山通番"])
    c_yamas = set(details.loc[details["納入先"] == "拠点C", "山通番"])
    assert a_yamas and c_yamas and a_yamas.isdisjoint(c_yamas)
    assert len(details) == 2
    assert set(details["HINBAN"]) == set(shipments["HINBAN"])
    assert summary["パレット数"].sum() == 2


@pytest.mark.parametrize(
    "floor,work,deadline,finish,needs_rescue",
    [
        (_secs(7), 600, _secs(7, 9, 59), _secs(7, 10), True),
        (_secs(10, 20), 600, _secs(10, 30), _secs(10, 30), False),
        (_secs(10, 20), 601, _secs(11, 30), _secs(12, 0, 1), True),
        (_secs(10, 40), 600, _secs(12), _secs(12), False),
        (_secs(10, 40), 600, _secs(11, 59, 59), _secs(12), True),
        (_secs(20, 35), 600, _secs(20, 45), _secs(20, 45), False),
        (_secs(20, 35), 601, _secs(22, 15), _secs(22, 15, 1), True),
        (_secs(20, 55), 600, _secs(22, 15), _secs(22, 15), False),
        (_secs(7), 600, _secs(8), _secs(7, 10), False),
        (_secs(10, 40), 600, None, _secs(12), False),
        (_secs(7), 600, _secs(6, 59), _secs(7, 10), True),
    ],
    ids=[
        "duration-overrun", "lunch-pre-exact", "lunch-pre-plus-one",
        "lunch-post-exact", "lunch-post-plus-one", "night-pre-exact",
        "night-pre-plus-one", "night-post-exact", "ample-time",
        "no-deadline", "floor-conflict",
    ],
)
def test_rescue_deadline_boundaries(floor, work, deadline, finish, needs_rescue):
    # 1Pの移動工数を逆算し、実際の休憩APIと秒単位で照合する。
    mountain = pd.DataFrame({"移動工数": [work - BASE_ONE_TIME - BASE_PER_PAL]})
    before = mountain.copy(deep=True)
    start = _adjust_start_for_breaks(floor, work)
    assert _calc_work_end_with_breaks(start, work) == finish
    assert _needs_mixed_deadline_rescue(mountain, floor, deadline) is needs_rescue
    pd.testing.assert_frame_equal(mountain, before)


@pytest.mark.parametrize(
    "moves,work",
    [
        ([72.9], 253),
        ([313.74, 313.74], 549),
        ([72.9, 313.74, 313.74], 604),
        ([72.9, None], 308),
        ([None, None], 235),
        ([float("nan"), "invalid"], 235),
        (["313.74", None], 549),
    ],
    ids=["1p", "2p", "3p", "partial-missing", "all-missing", "coerce-missing", "numeric-text"],
)
def test_rescue_work_uses_max_move_and_expanded_row_count(moves, work):
    mountain = pd.DataFrame({"移動工数": moves, "PLANKANBANSU": [9] * len(moves)})
    before = mountain.copy(deep=True)
    floor = _secs(7)
    assert not _needs_mixed_deadline_rescue(mountain, floor, floor + work)
    assert _needs_mixed_deadline_rescue(mountain, floor, floor + work - 1)
    pd.testing.assert_frame_equal(mountain, before)


def test_toyotetsu_and_orihata_finish_on_time_without_floor_warning(caplog):
    shipments, master = _case()
    _, _, _, groups, _, mixed = _run(shipments, master)
    details = build_all_mountain_details(groups, mixed)
    with caplog.at_level(logging.WARNING):
        assignments = assign_processes_by_arrival_time(compute_proc_details(details), master)
    assigned = details.merge(assignments, on="山通番", validate="many_to_one")
    _assert_split(assigned, "豊鉄広久手")
    assert not assigned["締切超過"].any()
    for vendor, order, floor, deadline, work in [
        ("豊鉄広久手", "02", _secs(6, 50), _secs(11, 30), 253),
        ("織機", "05", _secs(11, 50), _secs(12, 20), 549),
    ]:
        sub = assigned.loc[assigned["納入先"] == vendor]
        assert sub["NONYUHIBIN"].astype(str).str.endswith(order).all()
        assert sub["山通番"].nunique() == 1
        assert sub["実開始時間"].nunique() == 1
        start = _time_to_seconds(sub.iloc[0]["実開始時間"])
        assert start >= floor
        if vendor == "織機":
            assert start == floor
        end = _calc_work_end_with_breaks(start, work)
        assert end <= deadline
        assert _time_to_seconds(sub.iloc[0]["実終了時間"]) == end // 60 * 60
    assert not any(
        "分割救済の開始" in record.getMessage() and "補正しました" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize("vendor", ["豊鉄広久手", "日野"])
def test_separated_vendor_floor_matches_current_assignment_rules(vendor):
    shipments, master = _case(vendor)
    _, _, _, groups, _, mixed = _run(shipments, master)
    details = build_all_mountain_details(groups, mixed)
    assignments = assign_processes_by_arrival_time(compute_proc_details(details), master)
    assigned = details.merge(assignments, on="山通番", validate="many_to_one")
    _assert_split(assigned, vendor)
    urgent = assigned.loc[assigned["納入先"] == vendor].iloc[0]
    # 日野12の工程床は同レーンの10便09:25由来。山組みのN-1床とは区別する。
    floor = _secs(9, 35) if vendor == "日野" else _secs(6, 50)
    deadline = _secs(11, 55) if vendor == "日野" else _secs(11, 30)
    start = _time_to_seconds(urgent["実開始時間"])
    assert start >= floor
    assert _calc_work_end_with_breaks(start, 253) <= deadline
    assert not assigned["締切超過"].any()


@pytest.mark.parametrize("mode", ["ample-time", "no-deadline", "single-vendor"])
def test_rescue_does_not_make_unnecessary_or_empty_mountains(mode):
    shipments, master = _case()
    if mode == "ample-time":
        master.loc[
            (master["OData_納入先"] == "豊鉄広久手") & (master["NONYUHIBIN"] == "02"),
            "入車時間",
        ] = "12:40"
    elif mode == "no-deadline":
        master = master.iloc[0:0].copy()
    else:
        shipments[["納入先", "SYUKKASAKI"]] = "織機"
        shipments["NONYUHIBIN"] = "2026101605"
        shipments["UKEIRE"] = "28"
        master.loc[master["NONYUHIBIN"] == "05", "入車時間"] = "11:40"
    before = shipments.copy(deep=True)
    _, _, _, _, summary, details = _run(shipments, master)
    assert len(details) == 3
    assert details["山通番"].nunique() == 1
    assert summary["パレット数"].tolist() == [3]
    assert summary["引取工数"].tolist() == [604]
    pd.testing.assert_frame_equal(shipments, before)


def test_rescue_applies_to_size21_and_already_expanded_rows():
    shipments, master = _case()
    shipments.loc[shipments["納入先"] == "豊鉄広久手", "サイズ種類"] = "21"
    shipments = shipments.iloc[:2].copy()
    shipments.loc[shipments["納入先"] == "織機", "PLANKANBANSU"] = 2
    _, _, _, _, summary, details = _run(shipments, master)
    _assert_split(details, "豊鉄広久手")
    assert sorted(summary["引取工数"]) == [253, 549]


def test_r7_fallback_keeps_break_aware_rescue(monkeypatch, caplog):
    shipments, master = _case()
    extra = []
    for i in range(3):
        row = shipments.iloc[0].copy()
        row["HINBAN"] = f"FILLER{i}"
        row["納入先"] = row["SYUKKASAKI"] = f"拠点{i}"
        row["NONYUHIBIN"] = "2026101601"
        row["移動工数"] = 50.0
        extra.append(row)
        master.loc[len(master)] = [f"拠点{i}", "01", f"12:{31 + i:02d}", ""]
    shipments = pd.concat([shipments, pd.DataFrame(extra)], ignore_index=True)
    # 探索自体は変えず、通常経路だけ全ユニットを別山としてR7の戻しを強制する。
    monkeypatch.setattr(
        sorter, "_match_units_staged", lambda units, cap: {},
    )
    with caplog.at_level(logging.INFO, logger="src.services.sorter"):
        _, expanded, _, _, summary, details = _run(shipments, master)
    assert any(
        "[R7]" in record.getMessage() and "従来の結果を使います" in record.getMessage()
        for record in caplog.records
    )
    legacy_summary, legacy_details = _build_size1_mixed(
        expanded, DEFAULT_HEIGHT_CAP, "UKEIRE", master_df=master, _legacy=True,
    )
    pd.testing.assert_frame_equal(summary, legacy_summary)
    pd.testing.assert_frame_equal(details, legacy_details)
    urgent_yamas = set(details.loc[details["納入先"] == "豊鉄広久手", "山通番"])
    orihata_yamas = set(details.loc[details["納入先"] == "織機", "山通番"])
    assert urgent_yamas.isdisjoint(orihata_yamas)
    assert len(details) == 6
    assert summary["パレット数"].sum() == 6
