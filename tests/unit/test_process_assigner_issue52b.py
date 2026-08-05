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
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.services.process_assigner import (
    _legacy_assign_processes_by_arrival_time,
    compute_proc_details,
    _time_to_seconds,
    _calc_work_end_with_breaks,
    _to_operational_timeline_secs,
    _seconds_to_hhmm,
    PICKUP_DEADLINE_BUFFER_SECS,
    DAY_SECS,
)
from src.models.constants import (
    PROC_MAIN, PROC_OVERFLOW,
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


def _deadline_for_eval_for_test(deadline_val: int, start_secs: int) -> int:
    ddl = int(deadline_val)
    st = int(start_secs)
    if st >= DAY_SECS and ddl < DAY_SECS:
        return ddl + DAY_SECS
    return ddl


def _overflow_col_name(df: pd.DataFrame) -> str:
    if "締切超過" in df.columns:
        return "締切超過"
    if "締 切超過" in df.columns:
        return "締 切超過"
    raise AssertionError(f"締切超過列が見つかりません: {list(df.columns)}")


def _work_map_from_details(detail_rows: list[dict]) -> dict[int, int]:
    work_map: dict[int, int] = {}
    for yama, sub in pd.DataFrame(detail_rows).groupby("山通番"):
        yno = int(yama)
        pals = len(sub)
        max_cost = float(sub["移動工数"].max())
        work_map[yno] = _work_secs(max_cost, pals)
    return work_map


def _build_issue52_synthetic_detail_rows() -> list[dict]:
    rows = []
    for yno in [201, 202, 203, 204, 205]:
        rows += _rows(yno, "日野", "2026072013", 240.0, 1)
    return rows


def _build_issue52_synthetic_master_rows_for_overlap_and_180() -> list[dict]:
    return [
        {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "23:59", "セットありフラグ": ""},
    ]


def _build_issue52_synthetic_master_rows_for_deadline_overflow() -> list[dict]:
    return [
        {"OData_納入先": "日野", "NONYUHIBIN": "13", "入車時間": "17:55", "セットありフラグ": ""},
    ]


def _run_e2e(detail_rows: list[dict], master_rows: list[dict]) -> pd.DataFrame:
    details = pd.DataFrame(detail_rows)
    proc_details = compute_proc_details(details)
    master_df = pd.DataFrame(master_rows)
    return _legacy_assign_processes_by_arrival_time(proc_details, master_df)


def _sorted_main_lane_rows(result: pd.DataFrame) -> list[dict]:
    main_rows = result[result["山工程"] == PROC_MAIN].copy()
    out_rows = main_rows.to_dict("records")
    out_rows.sort(key=lambda rr: (
        _to_operational_timeline_secs(_time_to_seconds(str(rr.get("実開始時間", "")))) is None,
        _to_operational_timeline_secs(_time_to_seconds(str(rr.get("実開始時間", "")))) or float("inf"),
        int(rr.get("山通番", 0)),
    ))
    return out_rows


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
    assert "締切超過" in result.columns

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
def test_issue52b_synthetic_lane_has_no_overlap_after_honest_serialize():
    detail_rows = _build_issue52_synthetic_detail_rows()
    master_rows = _build_issue52_synthetic_master_rows_for_overlap_and_180()
    result = _run_e2e(detail_rows, master_rows)
    work_map = _work_map_from_details(detail_rows)

    lane_rows = _sorted_main_lane_rows(result)
    assert len(lane_rows) >= 2

    prev_end = None
    for rr in lane_rows:
        yno = int(rr["山通番"])
        st = _to_operational_timeline_secs(_time_to_seconds(str(rr.get("実開始時間", ""))))
        assert st is not None, f"実開始時間が取得できません: 山{yno}, row={rr}"

        end_txt = rr.get("実終了時間")
        end_raw = _time_to_seconds(str(end_txt)) if pd.notna(end_txt) else None
        assert end_raw is not None, f"実終了時間が取得できません: 山{yno}, row={rr}"
        end_oper = _to_operational_timeline_secs(end_raw)
        assert end_oper is not None, f"実終了時間の運用秒化に失敗: 山{yno}, row={rr}"

        if prev_end is not None:
            assert int(st) >= int(prev_end), f"重複発生: 前山終了{prev_end} > 山{yno}開始{st}"
        prev_end = int(end_oper)


def test_issue52b_synthetic_3rd_and_5th_need_180sec_gap():
    detail_rows = _build_issue52_synthetic_detail_rows()
    master_rows = _build_issue52_synthetic_master_rows_for_overlap_and_180()
    result = _run_e2e(detail_rows, master_rows)

    lane_rows = _sorted_main_lane_rows(result)
    assert len(lane_rows) == 5, f"期待メイン山数5に対して {len(lane_rows)}"

    for idx, rr in enumerate(lane_rows):
        expected = bool(idx >= 2 and idx % 2 == 0)
        assert bool(rr.get("照合追加180秒", False)) is expected, (
            f"照合追加180秒不一致: idx={idx}, 山{rr.get('山通番')}, "
            f"actual={rr.get('照合追加180秒')}, expected={expected}"
        )

    for idx in (2, 4):
        prev_rr = lane_rows[idx - 1]
        curr_rr = lane_rows[idx]
        prev_end = _to_operational_timeline_secs(_time_to_seconds(str(prev_rr.get("実終了時間", ""))))
        curr_start = _to_operational_timeline_secs(_time_to_seconds(str(curr_rr.get("実開始時間", ""))))
        assert prev_end is not None, f"実終了時間が取得できません: 山{prev_rr.get('山通番')}, row={prev_rr}"
        assert curr_start is not None, f"実開始時間が取得できません: 山{curr_rr.get('山通番')}, row={curr_rr}"
        assert int(curr_start) >= int(prev_end) + 180, (
            f"180秒ギャップ不足: idx={idx}, 前山{prev_rr.get('山通番')}終了{prev_end}, "
            f"現山{curr_rr.get('山通番')}開始{curr_start}"
        )


def test_issue52b_synthetic_deadline_overflow_flag_true_false_is_consistent():
    detail_rows = _build_issue52_synthetic_detail_rows()
    master_rows = _build_issue52_synthetic_master_rows_for_deadline_overflow()
    result = _run_e2e(detail_rows, master_rows)
    overflow_col = _overflow_col_name(result)
    work_map = _work_map_from_details(detail_rows)

    lane_rows = _sorted_main_lane_rows(result)
    assert lane_rows, "メイン工程レーンの行がありません"

    deadline_raw = _time_to_seconds("17:55")
    assert deadline_raw is not None
    deadline_secs = int(deadline_raw) - int(PICKUP_DEADLINE_BUFFER_SECS)

    manual_flags = []
    actual_flags = []
    for rr in lane_rows:
        yno = int(rr["山通番"])
        start_secs = _to_operational_timeline_secs(_time_to_seconds(str(rr.get("実開始時間", ""))))
        assert start_secs is not None, f"実開始時間が取得できません: 山{yno}, row={rr}"
        end_secs = int(_calc_work_end_with_breaks(int(start_secs), int(work_map[yno])))
        manual = bool(end_secs > _deadline_for_eval_for_test(deadline_secs, int(start_secs)))
        actual = bool(rr.get(overflow_col, False))
        manual_flags.append(manual)
        actual_flags.append(actual)
        assert actual == manual, (
            f"締切超過フラグ不一致: 山{yno}, actual={actual}, manual={manual}, "
            f"start={start_secs}, end={end_secs}, deadline={deadline_secs}"
        )

    assert any(actual_flags), f"締切超過=True が存在しません: {actual_flags}"
    assert any(not x for x in actual_flags), f"締切超過=False が存在しません: {actual_flags}"


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
