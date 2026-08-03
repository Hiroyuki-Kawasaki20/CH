# -*- coding: utf-8 -*-
"""Issue #52 t133b: A/B比較による締切違反再現テスト

目的:
  _serialize_lanes_final の「後ろ倒し後の締切再チェック欠如」バグを
  パターンA(no-op)/パターンB(現状実装)の比較で検証する。

成功条件:
  - パターンBで締切違反が1件以上再現される
  - パターンAでは同じ山が違反しない（または違反が減る）
  - 直列化前後で変化した山が1件以上存在すること
"""

import sys
import copy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

import src.services.process_assigner as pa
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
from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW, BASE_ONE_TIME, BASE_PER_PAL, MIDDLE_WORK

# ─────────────────────────────────────────────────────────────────────────────
# 実データ (test_hino13_normal_regression.py と同一)
# ─────────────────────────────────────────────────────────────────────────────
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

# 日野13便を含む山 (NONYUHIBIN 2026072013)
HINO13_YAMAS = (2, 9, 10, 11, 12)

# 日野13便の締切 = 入車12:45 - 20min = 12:25 = 44700秒
HINO13_DEADLINE_SECS = (12 * 3600 + 45 * 60) - PICKUP_DEADLINE_BUFFER_SECS  # 44700


def _work_secs(move_cost: float, pals: int) -> int:
    return int(round(move_cost + BASE_ONE_TIME + (pals - 1) * MIDDLE_WORK + pals * BASE_PER_PAL, 0))


def _hhmm_to_secs(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def _simulate_serialize_lanes(rows: list, work_map: dict) -> list:
    """_serialize_lanes_final と同じロジックをテスト用に再実装。
    戻り値: 直列化後の rows (deep copy) """
    rows = copy.deepcopy(rows)
    lane_labels: list = []
    for rr in rows:
        lb = rr.get("山工程")
        if lb not in lane_labels:
            lane_labels.append(lb)

    for proc_label in lane_labels:
        lane_rows = [rr for rr in rows if rr.get("山工程") == proc_label]
        # 開始時刻順ソート（昇順、同時刻は山通番順）
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
                end_secs = int(_calc_work_end_with_breaks(new_start, work_dur))
                rr["実終了時間"] = _seconds_to_hhmm(end_secs % 86400)
                prev_end = end_secs
            else:
                new_start = int(current_start)
                end_secs = int(_calc_work_end_with_breaks(new_start, work_dur))
                rr["実終了時間"] = _seconds_to_hhmm(end_secs % 86400)
                prev_end = end_secs

    return rows


def _build_comparison_table(
    rows_a: list, rows_b: list, work_map: dict, deadline_map: dict
) -> list:
    """A/B 比較テーブルを構築 (山番号 / A開始 / B開始 / 締切 / A超過分 / B超過分)"""
    yamas_a = {int(r["山通番"]): r for r in rows_a}
    yamas_b = {int(r["山通番"]): r for r in rows_b}

    table = []
    for yno in sorted(set(yamas_a) | set(yamas_b)):
        ra = yamas_a.get(yno)
        rb = yamas_b.get(yno)
        ddl = deadline_map.get(yno)
        wk = work_map.get(yno, 0)

        a_start_str = ra.get("実開始時間", "") if ra else ""
        b_start_str = rb.get("実開始時間", "") if rb else ""
        a_start = _time_to_seconds(a_start_str) if a_start_str else None
        b_start = _time_to_seconds(b_start_str) if b_start_str else None

        a_end = int(_calc_work_end_with_breaks(a_start, wk)) if a_start is not None else None
        b_end = int(_calc_work_end_with_breaks(b_start, wk)) if b_start is not None else None

        a_over = (a_end - ddl) if (a_end is not None and ddl is not None and a_end > ddl) else 0
        b_over = (b_end - ddl) if (b_end is not None and ddl is not None and b_end > ddl) else 0

        table.append({
            "山通番": yno,
            "A開始": a_start_str,
            "B開始": b_start_str,
            "変化": a_start_str != b_start_str,
            "締切": _seconds_to_hhmm(ddl) if ddl else "なし",
            "A超過秒": a_over,
            "B超過秒": b_over,
        })
    return table


def _format_table(table: list) -> str:
    lines = ["山通番  A開始   B開始   変化  締切   A超過秒  B超過秒"]
    lines.append("-" * 62)
    for row in table:
        marker = " ← " if row["変化"] else "    "
        lines.append(
            f'{row["山通番"]:5d}  {row["A開始"]:6}  {row["B開始"]:6}{marker}'
            f' {row["締切"]:6}  {row["A超過秒"]:7d}  {row["B超過秒"]:7d}'
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# テスト1: 実データ A/B 比較（日野13便2026073113便）
# ─────────────────────────────────────────────────────────────────────────────
def test_issue52b_real_data_ab_comparison(monkeypatch):
    """実データ(15山・日野13便)でA/B比較。
    直列化前後で変化した山 / 締切違反の有無を t133b_issue52_repro.txt に出力する。
    変化ゼロの場合は「このデータでは再現条件を満たしていない」と明記する。
    """
    details = pd.DataFrame(HINO13_DETAIL_ROWS)
    proc_details = compute_proc_details(details)
    master_df = pd.DataFrame(HINO13_MASTER_ROWS)

    # ── Pattern A: 直列化 skip ──
    monkeypatch.setattr(pa, "_SKIP_SERIALIZE_FINAL_FOR_TEST", True)
    result_a = _legacy_assign_processes_by_arrival_time(proc_details, master_df)

    # ── Pattern B: 現状実装（直列化あり）──
    monkeypatch.setattr(pa, "_SKIP_SERIALIZE_FINAL_FOR_TEST", False)
    result_b = _legacy_assign_processes_by_arrival_time(proc_details, master_df)

    rows_a = result_a.to_dict("records")
    rows_b = result_b.to_dict("records")

    # 山ごとの工数 / 締切マップを外部計算
    work_map = {}
    deadline_map = {}
    for yama, sub in pd.DataFrame(HINO13_DETAIL_ROWS).groupby("山通番"):
        yno = int(yama)
        pals = len(sub)
        max_cost = float(sub["移動工数"].max())
        work_map[yno] = _work_secs(max_cost, pals)

    # 日野13便(NONYUHIBIN 2026072013) → deadline 44700
    for yno in HINO13_YAMAS:
        deadline_map[yno] = HINO13_DEADLINE_SECS

    table = _build_comparison_table(rows_a, rows_b, work_map, deadline_map)
    changed = [r for r in table if r["変化"]]
    b_violations = [r for r in table if r["B超過秒"] > 0]
    a_violations = [r for r in table if r["A超過秒"] > 0]

    report_lines = [
        "=" * 70,
        "Issue #52 t133b: 実データ A/B 比較（日野2026073113便 / 15山）",
        "=" * 70,
        "",
        "【テスト条件】",
        "  日野13便 入車時刻: 12:45 / 締切: 12:25 (44700秒)",
        f"  山数: 15 / 日野13便山: {HINO13_YAMAS}",
        "",
        "【A/B 比較テーブル (日野13便山のみ)】",
        _format_table([r for r in table if r["山通番"] in HINO13_YAMAS]),
        "",
        "【全山 A/B 比較テーブル】",
        _format_table(table),
        "",
    ]

    if not changed:
        report_lines += [
            "【判定】直列化前後で開始時刻が変化した山: 0件",
            "  → このデータでは _serialize_lanes_final が no-op になっています。",
            "  → このテストは再現条件を満たしていません。",
            "  → 理由: 現状の割当では同一レーン内に時間帯重複がないため直列化が不要。",
        ]
    else:
        report_lines += [
            f"【判定】直列化前後で開始時刻が変化した山: {len(changed)}件",
            f"  変化した山番号: {[r['山通番'] for r in changed]}",
        ]

    if b_violations:
        report_lines += [
            "",
            f"【パターンB 締切違反】{len(b_violations)}件",
        ]
        for r in b_violations:
            report_lines.append(
                f"  山{r['山通番']}: 締切{r['締切']} を {r['B超過秒']}秒超過"
            )
    else:
        report_lines.append("\n【パターンB 締切違反】0件（違反なし）")

    if a_violations:
        report_lines += [
            f"【パターンA 締切違反】{len(a_violations)}件",
        ]
        for r in a_violations:
            report_lines.append(
                f"  山{r['山通番']}: 締切{r['締切']} を {r['A超過秒']}秒超過"
            )
    else:
        report_lines.append("【パターンA 締切違反】0件（違反なし）")

    report = "\n".join(report_lines)
    print("\n" + report)

    with open("t133b_issue52_real_data.txt", "w", encoding="utf-8") as f:
        f.write(report)

    # テスト通過条件: パターンA/Bどちらも必ず実行できること（クラッシュなし）
    assert result_a is not None and result_b is not None


# ─────────────────────────────────────────────────────────────────────────────
# テスト2: 合成データ — 意図的重複による _serialize_lanes_final 締切違反再現
# ─────────────────────────────────────────────────────────────────────────────
def test_issue52b_synthetic_overlap_deadline_violation():
    """合成データで「後ろ倒し後の締切再チェック欠如」を直接実証する。

    Issue #52 の山9〜12（日野13便）に基づいた実工数値を使い、
    意図的に同一レーン内で時間帯が重複する事前状態を作成。
    _serialize_lanes_final 相当ロジックを適用すると締切違反が発生することを示す。
    """
    # 日野13便の実工数（HINO13_DETAIL_ROWS より計算）
    # 山9: 2pal, move=72.916 → work≈368秒
    # 山10: 3pal, move=72.911 → work≈423秒
    # 山11: 2pal, move=72.904 → work≈368秒
    # 山12: 1pal, move=72.917 → work≈313秒
    work_map = {
        9:  _work_secs(72.916, 2),   # ≈ 368s
        10: _work_secs(72.911, 3),   # ≈ 423s
        11: _work_secs(72.904, 2),   # ≈ 368s
        12: _work_secs(72.917, 1),   # ≈ 313s
    }
    deadline_map = {yno: HINO13_DEADLINE_SECS for yno in (9, 10, 11, 12)}

    # 意図的重複: 山9〜12 を全て同一開始時刻 12:10 (= 43800秒) に設定
    # ← これが「前の山と時間帯が重複する」状態
    # 実際の運用では発生してはいけない状態だが、
    # バグが発火する条件を最小限に再現するために意図的に作成
    START_OVERLAP = "12:10"  # 全山を同一開始に設定 (重複状態)

    # 実際の出力では山10・山12に照合追加180秒=True (t119_dump_hino13.py 結果より)
    rows_a = [
        {"山通番": 9,  "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": False},
        {"山通番": 10, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": True},
        {"山通番": 11, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": False},
        {"山通番": 12, "山工程": PROC_MAIN, "実開始時間": START_OVERLAP, "照合追加180秒": True},
    ]

    # パターンB = 直列化を適用
    rows_b = _simulate_serialize_lanes(rows_a, work_map)

    table = _build_comparison_table(rows_a, rows_b, work_map, deadline_map)
    changed = [r for r in table if r["変化"]]
    b_violations = [r for r in table if r["B超過秒"] > 0]
    a_violations = [r for r in table if r["A超過秒"] > 0]

    report_lines = [
        "=" * 70,
        "Issue #52 t133b: 合成データ A/B 比較",
        "（意図的重複 → _serialize_lanes_final 相当ロジック適用）",
        "=" * 70,
        "",
        "【テスト条件】",
        "  日野13便 締切: 12:25 (44700秒)",
        f"  山9〜12 を全て {START_OVERLAP} 開始に設定（意図的重複）",
        "",
        "【実工数 (秒)】",
    ]
    for yno in (9, 10, 11, 12):
        flag = rows_a[[r for r in range(4) if rows_a[r]["山通番"] == yno][0]]["照合追加180秒"]
        report_lines.append(f"  山{yno}: {work_map[yno]}秒  照合追加180秒={flag}")

    report_lines += [
        "",
        "【A/B 比較テーブル】",
        _format_table(table),
        "",
    ]

    if not changed:
        report_lines += [
            "【判定】直列化前後で変化した山: 0件 — 再現条件未達",
        ]
    else:
        report_lines += [
            f"【判定】直列化前後で変化した山: {len(changed)}件",
            f"  変化した山: {[r['山通番'] for r in changed]}",
        ]

    if b_violations:
        report_lines += [
            "",
            f"【パターンB 締切違反】★ {len(b_violations)}件 ← これが Issue #52 の再現",
        ]
        for r in b_violations:
            mins = r["B超過秒"] // 60
            secs = r["B超過秒"] % 60
            report_lines.append(
                f"  山{r['山通番']}: {r['A開始']}→{r['B開始']}  締切{r['締切']} を "
                f"+{mins}分{secs}秒超過 ({r['B超過秒']}秒)"
            )

    if a_violations:
        report_lines.append(f"\n【パターンA 締切違反】{len(a_violations)}件")
    else:
        report_lines.append("\n【パターンA 締切違反】0件 — 直列化なし時は全山締切内")

    report_lines += [
        "",
        "【結論】",
        "  _serialize_lanes_final は「後ろ倒し後の締切再チェック」を行わないため、",
        "  直列化で押し出された山が締切超過しても検出されない。",
        "  これが Issue #52 の根本原因である。",
    ]

    report = "\n".join(report_lines)
    print("\n" + report)

    with open("t133b_issue52_repro.txt", "w", encoding="utf-8") as f:
        f.write(report)

    # ─── 成功条件の検証 ───
    assert len(changed) >= 1, (
        f"直列化前後で変化した山が0件 — 再現条件未達\n試みた条件: {START_OVERLAP} 全山同時開始"
    )
    assert len(b_violations) >= 1, (
        f"パターンBで締切違反が0件 — 以下の条件を試して再現しなかった:\n"
        f"  入車時刻12:45, 締切12:25, 山9〜12 全て {START_OVERLAP} 開始\n"
        f"  工数: {work_map}"
    )
    assert len(a_violations) == 0 or len(b_violations) > len(a_violations), (
        f"パターンAでも違反が発生しており、直列化による悪化を示せていない\n"
        f"A違反: {a_violations}\nB違反: {b_violations}"
    )
