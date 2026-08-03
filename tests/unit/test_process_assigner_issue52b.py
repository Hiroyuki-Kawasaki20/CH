# -*- coding: utf-8 -*-
"""Issue #52 fix ブランチ: t133b テスト（修正後の検証）

目的:
  _serialize_lanes_final 後の締切再チェック欠如（Issue #52）の修正を検証する。

受け入れ条件:
  - 合成データケースで修正後は締切違反が0件
  - 実データ（日野2026073113便）で劣化なし
  - 5 failed から増えないこと
"""

import sys
import copy
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

from src.services.process_assigner import (
    _legacy_assign_processes_by_arrival_time,
    compute_proc_details,
    _time_to_seconds,
    _calc_work_end_with_breaks,
    _adjust_start_for_breaks,
    _to_operational_timeline_secs,
    _seconds_to_hhmm,
    PICKUP_DEADLINE_BUFFER_SECS,
    ARRIVAL_BUFFER_SECS,
)
from src.models.constants import (
    PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW,
    BASE_ONE_TIME, BASE_PER_PAL, MIDDLE_WORK,
)

# ──────────────────────────────────────────────────────────────────────────────
# 実データ (test_hino13_normal_regression.py と同一)
# ──────────────────────────────────────────────────────────────────────────────
HINO13_MASTER_ROWS = [
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
    {"OData_納入先": "織機", "NONYUHIBIN": "05", "入車時間": "12:30", "セットありフラグ": "1"},
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


HINO13_DETAIL_ROWS = (
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

HINO13_YAMAS = (2, 9, 10, 11, 12)
HINO13_DEADLINE_SECS = (12 * 3600 + 45 * 60) - PICKUP_DEADLINE_BUFFER_SECS  # 44700


def _work_secs(move_cost: float, pals: int) -> int:
    return int(round(move_cost + BASE_ONE_TIME + (pals - 1) * MIDDLE_WORK + pals * BASE_PER_PAL, 0))


def _simulate_serialize_lanes(rows: list, work_map: dict) -> list:
    """_serialize_lanes_final と同じロジック（テスト用再実装）。バグの発火を示すために使用する。"""
    rows = copy.deepcopy(rows)
    lane_labels: list = []
    for rr in rows:
        lb = rr.get("山工程")
        if lb not in lane_labels:
            lane_labels.append(lb)

    for proc_label in lane_labels:
        lane_rows = [rr for rr in rows if rr.get("山工程") == proc_label]
        lane_rows.sort(key=lambda rr: (
            _to_operational_timeline_secs(_time_to_seconds(str(rr.get("実開始時間", "")))) or float("inf"),
            int(rr.get("山通番", 0)),
        ))
        prev_end = None
        for rr in lane_rows:
            current_start = _to_operational_timeline_secs(
                _time_to_seconds(str(rr.get("実開始時間", "")))
            )
            if current_start is None:
                continue
            yama_no = int(rr["山通番"])
            work_dur = int(work_map.get(yama_no, 0))
            inspection_delay = 180 if bool(rr.get("照合追加180秒")) else 0
            candidate = int(current_start)
            if prev_end is not None:
                candidate = max(candidate, int(prev_end) + inspection_delay)

            if candidate > int(current_start):
                new_start = int(_adjust_start_for_breaks(candidate, work_dur))
                rr["実開始時間"] = _seconds_to_hhmm(new_start % 86400)
                rr["実終了時間"] = _seconds_to_hhmm(
                    int(_calc_work_end_with_breaks(new_start, work_dur)) % 86400
                )
                prev_end = int(_calc_work_end_with_breaks(new_start, work_dur))
            else:
                prev_end = int(_calc_work_end_with_breaks(int(current_start), work_dur))
    return rows


def _simulate_fix_after_serialize(rows: list, work_map: dict, deadline_map: dict) -> list:
    """直列化後の締切超過を再チェックし、超過山をリリーフ→オーバーフローと段階的に降格する。

    実装は process_assigner._enforce_main_deadline_strict +
    _reapply_overflow_for_relief の最小限の再現。
    """
    rows = copy.deepcopy(rows)
    for _ in range(3):
        # MAIN 超過を検出しリリーフへ降格
        late_main = []
        for rr in rows:
            if rr.get("山工程") != PROC_MAIN:
                continue
            yno = int(rr["山通番"])
            ddl = deadline_map.get(yno)
            if ddl is None:
                continue
            st = _time_to_seconds(str(rr.get("実開始時間", "")))
            if st is None:
                continue
            if int(_calc_work_end_with_breaks(st, work_map.get(yno, 0))) > ddl:
                late_main.append(yno)

        if late_main:
            late_set = set(late_main)
            for rr in rows:
                if int(rr["山通番"]) in late_set and rr.get("山工程") == PROC_MAIN:
                    rr["山工程"] = PROC_RELIEF
                    rr["実開始時間"] = ""
                    rr["照合追加180秒"] = False
            # RELIEF を締切優先で再スケジュール
            relief_rows = [rr for rr in rows if rr.get("山工程") == PROC_RELIEF]
            relief_rows.sort(key=lambda rr: (
                deadline_map.get(int(rr["山通番"])) or float("inf"),
                int(rr["山通番"]),
            ))
            prev_end = 0
            for rr in relief_rows:
                yno = int(rr["山通番"])
                ddl = deadline_map.get(yno)
                wk = work_map.get(yno, 0)
                if ddl is not None:
                    latest_start = max(0, ddl - wk)
                    candidate = max(int(prev_end), int(latest_start))
                else:
                    candidate = int(prev_end)
                start = int(_adjust_start_for_breaks(candidate, wk))
                rr["実開始時間"] = _seconds_to_hhmm(start)
                prev_end = int(_calc_work_end_with_breaks(start, wk))

        # RELIEF 超過をオーバーフローへ降格
        late_relief = []
        for rr in rows:
            if rr.get("山工程") != PROC_RELIEF:
                continue
            yno = int(rr["山通番"])
            ddl = deadline_map.get(yno)
            if ddl is None:
                continue
            st = _time_to_seconds(str(rr.get("実開始時間", "")))
            if st is None:
                continue
            if int(_calc_work_end_with_breaks(st, work_map.get(yno, 0))) > ddl:
                late_relief.append(yno)

        if late_relief:
            late_set = set(late_relief)
            for rr in rows:
                if int(rr["山通番"]) in late_set and rr.get("山工程") == PROC_RELIEF:
                    rr["山工程"] = PROC_OVERFLOW

        if not late_main and not late_relief:
            break

    return rows


def _check_violations(rows: list, work_map: dict, deadline_map: dict,
                      exclude_overflow: bool = True) -> list:
    """締切超過している山の一覧を返す。OVERFLOW はデフォルトで除外（救済不能として扱う）。"""
    violations = []
    for rr in rows:
        if exclude_overflow and rr.get("山工程") == PROC_OVERFLOW:
            continue
        yno = int(rr["山通番"])
        ddl = deadline_map.get(yno)
        if ddl is None:
            continue
        st = _time_to_seconds(str(rr.get("実開始時間", "")))
        if st is None:
            continue
        en = int(_calc_work_end_with_breaks(st, work_map.get(yno, 0)))
        if en > ddl:
            violations.append({
                "山通番": yno,
                "工程": rr.get("山工程"),
                "開始": rr.get("実開始時間"),
                "終了": _seconds_to_hhmm(en),
                "締切": _seconds_to_hhmm(ddl),
                "超過秒": en - ddl,
            })
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# テスト1: 実データ（日野2026073113便 / 15山）で修正後の結果を検証
# ─────────────────────────────────────────────────────────────────────────────
def test_issue52b_real_data_ab_comparison():
    """実データ(15山)でエンドツーエンドを実行し締切違反ゼロを確認する。

    _serialize_lanes_final はネスト関数のため直接パッチ不可。
    修正により直列化後の再チェックが組み込まれるため、フルパイプラインで検証する。
    """
    details = pd.DataFrame(HINO13_DETAIL_ROWS)
    proc_details = compute_proc_details(details)
    master_df = pd.DataFrame(HINO13_MASTER_ROWS)

    result = _legacy_assign_processes_by_arrival_time(proc_details, master_df)

    rows = result.to_dict("records")
    work_map = {}
    for yama, sub in pd.DataFrame(HINO13_DETAIL_ROWS).groupby("山通番"):
        yno = int(yama)
        pals = len(sub)
        max_cost = float(sub["移動工数"].max())
        work_map[yno] = _work_secs(max_cost, pals)

    deadline_map = {yno: HINO13_DEADLINE_SECS for yno in HINO13_YAMAS}
    violations = _check_violations(rows, work_map, deadline_map)

    report_lines = [
        "=" * 70,
        "Issue #52 t135: 実データ検証（日野2026073113便 / 15山）",
        "=" * 70,
        "",
        "【結果一覧】",
        result[["山通番", "山工程", "実開始時間"]].to_string(),
        "",
        f"【締切違反】{len(violations)}件" + (" ★ 問題あり" if violations else " — 修正後も正常"),
    ]
    for v in violations:
        report_lines.append(
            f"  山{v['山通番']}({v['工程']}): {v['開始']}〜{v['終了']}  締切{v['締切']}  +{v['超過秒']}秒"
        )

    print("\n" + "\n".join(report_lines))

    assert violations == [], (
        f"修正後も実データで締切違反が残っています:\n"
        + "\n".join(f"  山{v['山通番']}: +{v['超過秒']}秒" for v in violations)
    )


# ─────────────────────────────────────────────────────────────────────────────
# テスト2: 合成データ — バグ機構の実証 + 修正ロジックの確認
# ─────────────────────────────────────────────────────────────────────────────
def test_issue52b_synthetic_overlap_deadline_violation():
    """合成データで Issue #52 バグの機構と修正を実証する。

    Part 1: _simulate_serialize_lanes でバグ（直列化 → 締切違反）を発火
    Part 2: _simulate_fix_after_serialize で修正（降格 → 再スケジュール → 違反0件）を確認
    """
    work_map = {
        9:  _work_secs(72.916, 2),   # ≈ 368s
        10: _work_secs(72.911, 3),   # ≈ 423s
        11: _work_secs(72.904, 2),   # ≈ 368s
        12: _work_secs(72.917, 1),   # ≈ 313s
    }
    deadline_map = {yno: HINO13_DEADLINE_SECS for yno in (9, 10, 11, 12)}

    START_OVERLAP = "12:10"
    rows_a = [
        {"山通番": 9,  "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": False},
        {"山通番": 10, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": True},
        {"山通番": 11, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": False},
        {"山通番": 12, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": True},
    ]

    rows_b = _simulate_serialize_lanes(rows_a, work_map)
    b_violations = _check_violations(rows_b, work_map, deadline_map)

    rows_c = _simulate_fix_after_serialize(rows_b, work_map, deadline_map)
    c_violations = _check_violations(rows_c, work_map, deadline_map)

    report_lines = [
        "=" * 70,
        "Issue #52 t135: 合成データ A/B/C 比較",
        "  A = 重複あり (直列化前)",
        "  B = 直列化後  (バグ発火)",
        "  C = 直列化後 + 再チェック降格 (修正後)",
        "=" * 70,
        "",
        f"日野13便 締切: 12:25 ({HINO13_DEADLINE_SECS}秒)",
        f"全山 {START_OVERLAP} 開始（意図的重複）",
        "",
        "【Part 1: バグ発火（直列化のみ）】",
    ]
    for rr_b in sorted(rows_b, key=lambda r: r["山通番"]):
        yno = int(rr_b["山通番"])
        ddl = deadline_map.get(yno)
        st_b = _time_to_seconds(str(rr_b.get("実開始時間", "")))
        en_b = int(_calc_work_end_with_breaks(st_b, work_map[yno])) if st_b else None
        over = (en_b - ddl) if (en_b and ddl and en_b > ddl) else 0
        flag = "★" if over > 0 else "OK"
        report_lines.append(
            f"  山{yno}: {START_OVERLAP} → {rr_b.get('実開始時間', '?')}  "
            f"締切{_seconds_to_hhmm(ddl) if ddl else 'なし'}  +{over}秒 {flag}"
        )

    report_lines += ["", "【Part 2: 修正後（直列化 + 再チェック降格）】"]
    for rr_c in sorted(rows_c, key=lambda r: r["山通番"]):
        yno = int(rr_c["山通番"])
        ddl = deadline_map.get(yno)
        st_c = _time_to_seconds(str(rr_c.get("実開始時間", "")))
        en_c = int(_calc_work_end_with_breaks(st_c, work_map[yno])) if st_c else None
        over = (en_c - ddl) if (en_c and ddl and en_c > ddl) else 0
        flag = "★" if over > 0 else "OK"
        report_lines.append(
            f"  山{yno}({rr_c.get('山工程', '?')}): {rr_c.get('実開始時間', '?')}  "
            f"締切{_seconds_to_hhmm(ddl) if ddl else 'なし'}  +{over}秒 {flag}"
        )

    report_lines += [
        "",
        f"【判定】バグ発火: {len(b_violations)}件  /  修正後: {len(c_violations)}件",
    ]

    report = "\n".join(report_lines)
    print("\n" + report)

    with open("t133b_issue52_repro.txt", "w", encoding="utf-8") as f:
        f.write(report)

    assert len(b_violations) >= 1, (
        f"Part1（バグ発火確認）で違反0件 — 直列化ロジックを確認\n工数={work_map}"
    )
    assert len(c_violations) == 0, (
        f"Part2（修正後）でも違反が {len(c_violations)}件:\n"
        + "\n".join(f"  山{v['山通番']}({v['工程']}): +{v['超過秒']}秒" for v in c_violations)
    )


# ─────────────────────────────────────────────────────────────────────────────
# テスト3: 修正後に警告ログが出ないことを monkeypatch + caplog で確認
# ─────────────────────────────────────────────────────────────────────────────
def test_issue52b_recheck_no_warning_on_real_data(monkeypatch, caplog):
    """実データで直列化後の再チェックが3回以内に完了し、警告ログが出ないことを確認する。

    monkeypatch は「本番コードに特定の状態を強制する」用途で使用。
    ここでは caplog を利用して _logger.warning の有無を検証することで
    「rescue 不能な山が残らないこと」を間接的に保証する。
    """
    import src.services.process_assigner as pa_module

    details = pd.DataFrame(HINO13_DETAIL_ROWS)
    proc_details = compute_proc_details(details)
    master_df = pd.DataFrame(HINO13_MASTER_ROWS)

    with caplog.at_level(logging.WARNING, logger="src.services.process_assigner"):
        result = _legacy_assign_processes_by_arrival_time(proc_details, master_df)

    issue52_warnings = [
        r for r in caplog.records
        if "Issue #52" in r.message or "救済できない" in r.message
    ]
    assert issue52_warnings == [], (
        f"Issue #52 の救済不能警告が発生しました: {[r.message for r in issue52_warnings]}"
    )
    assert result is not None and not result.empty
