# -*- coding: utf-8 -*-
"""実証モード(案2): 旧エンジン vs 最終出力のあふれ/遅延比較。

本スクリプトは本番srcを変更せず、テスト由来の再現ケースで
以下を数値比較する。
- ユニーク遅延山数
- メイン遅延数
- リリーフ遅延数
- リリーフ山数

補助指標:
- フォールバック発生件数 (最終出力が旧エンジンと同一)
- 同便分断ペナルティ (_cluster_split_penalty)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.constants import PROC_MAIN, PROC_OVERFLOW, PROC_RELIEF
from src.services.process_assigner import (
    _calc_work_end_with_breaks,
    _legacy_assign_processes_by_arrival_time,
    _time_to_seconds,
    compute_proc_details,
)
from src.services.scheduler import (
    _cluster_split_penalty,
    _mountain_context,
    assign_processes_by_arrival_time_edf_greedy,
)
from src.utils.normalizer import _ZEN2HAN_DIGIT_COLON, _normalize_dest_name


Metric = Dict[str, int]


def _build_case_a_tight_deadline() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_assign_with_tight_deadline
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 1, 2, 2],
            "移動工数": [100, 100, 100, 100],
            "納入先": ["武部", "武部", "武部", "武部"],
            "NONYUHIBIN": ["01", "01", "02", "02"],
            "高さ": [500, 500, 500, 500],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["武部", "武部"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["08:35", "08:36"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_b_overflow_fixed() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_relief_start_respects_prev_bin_floor
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2],
            "移動工数": [0.0, 0.0],
            "納入先": ["日野", "日野"],
            "NONYUHIBIN": ["01", "02"],
            "高さ": [300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["日野", "日野"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["12:00", "12:04"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_c_prefetch_complex() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_dynamic_prefetch_keeps_primary_deadline
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "A"],
            "NONYUHIBIN": ["01", "01", "02"],
            "高さ": [300, 300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["A", "A", "B"],
            "NONYUHIBIN": ["01", "02", "01"],
            "入車時間": ["09:20", "14:00", "10:00"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_d_prevents_late_main() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_assign_prevents_late_main_mountains_after_finalization
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "高さ": [300, 300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["A", "B", "C"],
            "NONYUHIBIN": ["01", "01", "01"],
            "入車時間": ["11:12", "11:12", "11:12"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_e_mixed_lanes_deadline() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_assign_main_deadline_rule_is_enforced_in_mixed_lanes
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3, 4],
            "移動工数": [120, 60, 30, 30],
            "納入先": ["D", "D", "A", "C"],
            "NONYUHIBIN": ["03", "02", "02", "02"],
            "高さ": [400, 400, 400, 400],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["D", "D", "A", "C"],
            "NONYUHIBIN": ["03", "02", "02", "02"],
            "入車時間": ["09:00", "11:40", "09:20", "08:50"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_f_deadline_reorder_feasible() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_assign_keeps_all_main_when_deadline_reorder_is_feasible
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3, 4],
            "移動工数": [223, 313, 16, 183],
            "納入先": ["A", "B", "B", "C"],
            "NONYUHIBIN": ["2026052701", "2026052801", "2026052801", "2026052701"],
            "高さ": [300, 300, 300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["A", "C", "B"],
            "NONYUHIBIN": ["01", "01", "01"],
            "入車時間": ["07:10", "07:31", "08:16"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_g_relief_promoted() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_relief_rows_can_be_promoted_back_to_main_when_feasible
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3],
            "移動工数": [0, 0, 0],
            "納入先": ["KVC", "A", "A"],
            "NONYUHIBIN": ["2026052701", "2026052701", "2026052702"],
            "高さ": [300, 300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["KVC", "A", "A"],
            "NONYUHIBIN": ["01", "01", "02"],
            "入車時間": ["08:20", "08:40", "09:30"],
            "セットありフラグ": ["0", "0", "0"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _build_case_h_multiple_relief() -> Tuple[pd.DataFrame, pd.DataFrame]:
    # tests/unit/test_sorter.py: test_relief_first_row_starts_earliest_when_multiple_relief_rows_exist
    raw_df = pd.DataFrame(
        {
            "山通番": [1, 2, 3, 4],
            "移動工数": [0, 0, 0, 0],
            "納入先": ["A", "A", "A", "A"],
            "NONYUHIBIN": ["2026052702", "2026052702", "2026052702", "2026052702"],
            "高さ": [300, 300, 300, 300],
        }
    )
    master_df = pd.DataFrame(
        {
            "OData_納入先": ["A", "A"],
            "NONYUHIBIN": ["01", "02"],
            "入車時間": ["09:26", "09:52"],
            "セットありフラグ": ["0", "0"],
        }
    )
    return compute_proc_details(raw_df), master_df


def _collect_late_yamas(
    rows: List[dict],
    proc_label: str,
    deadline_map: Dict[int, Optional[int]],
    work_map: Dict[int, int],
) -> List[int]:
    out: List[int] = []
    for r in rows:
        if str(r.get("山工程")) != proc_label:
            continue
        y = int(r["山通番"])
        ddl = deadline_map.get(y)
        if ddl is None:
            continue
        st = _time_to_seconds(str(r.get("実開始時間", "")))
        if st is None:
            continue
        en = _calc_work_end_with_breaks(int(st), int(work_map.get(y, 0)))
        if en > int(ddl):
            out.append(y)
    return out


def _metrics(df: pd.DataFrame, ddl_map: Dict[int, Optional[int]], work_map: Dict[int, int]) -> Metric:
    rows = df.to_dict(orient="records") if df is not None else []
    late_main = _collect_late_yamas(rows, PROC_MAIN, ddl_map, work_map)
    late_relief = _collect_late_yamas(rows, PROC_RELIEF, ddl_map, work_map)
    overflow = int((df["山工程"].astype(str) == PROC_OVERFLOW).sum()) if df is not None and not df.empty else 0
    return {
        "あふれ山数": overflow,
        "ユニーク遅延山数": len(set(late_main + late_relief)),
        "メイン遅延数": len(late_main),
        "リリーフ遅延数": len(late_relief),
        "リリーフ山数": int((df["山工程"].astype(str) == PROC_RELIEF).sum()) if df is not None and not df.empty else 0,
    }


def _score_tuple(metric: Metric) -> Tuple[int, int, int, int]:
    # 4指標版 _state_score と同じ優先順
    return (
        int(metric["ユニーク遅延山数"]),
        int(metric["メイン遅延数"]),
        int(metric["リリーフ遅延数"]),
        int(metric["リリーフ山数"]),
    )


def _build_yama_cluster_key_map(
    proc_details: pd.DataFrame,
    master_df: pd.DataFrame,
) -> Dict[int, Tuple[str, str]]:
    # _cluster_split_penalty 用の map。scheduler と同様に vendor + order2 の主便キーを採用。
    key_map: Dict[int, Tuple[str, str]] = {}

    master = master_df.copy() if master_df is not None else pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])
    if not master.empty:
        master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip().apply(_normalize_dest_name)
        master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
        master["入車時間"] = master["入車時間"].astype(str).str.strip()

    master_secs_map: Dict[Tuple[str, str], int] = {}
    for _, r in master.iterrows():
        pickup = _time_to_seconds(str(r.get("入車時間", "")))
        if pickup is None:
            continue
        master_secs_map[(str(r.get("OData_納入先", "")), str(r.get("NONYUHIBIN", "")))] = int(pickup)

    detail_df = proc_details.copy() if proc_details is not None else pd.DataFrame()
    if detail_df.empty:
        return key_map

    for yama in sorted(detail_df["山通番"].unique()):
        y = int(yama)
        sub = detail_df[detail_df["山通番"] == y]
        candidates = []
        for _, row in sub.iterrows():
            vendor_raw = (
                str(row.get("納入先", "")).strip()
                or str(row.get("OData_納入先", "")).strip()
                or str(row.get("SYUKKASAKI", "")).strip()
            )
            vendor = _normalize_dest_name(vendor_raw)
            nony = str(row.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue
            pickup = master_secs_map.get((vendor, order2))
            candidates.append((pickup is None, pickup or float("inf"), vendor, order2))

        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            _, _, vendor, order2 = candidates[0]
            key_map[y] = (vendor, order2)
        else:
            key_map[y] = (f"__YAMA__{y}", f"{y:02d}")

    return key_map


def _canonical_for_compare(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["山通番", "山工程", "実開始時間", "照合追加180秒"]
    out = df.copy() if df is not None else pd.DataFrame(columns=cols)
    for c in cols:
        if c not in out.columns:
            out[c] = "" if c != "照合追加180秒" else False
    out = out[cols].copy()
    out["山通番"] = pd.to_numeric(out["山通番"], errors="coerce").fillna(-1).astype(int)
    out["山工程"] = out["山工程"].astype(str)
    out["実開始時間"] = out["実開始時間"].astype(str)
    out["照合追加180秒"] = out["照合追加180秒"].astype(bool)
    return out.sort_values(["山通番", "山工程", "実開始時間", "照合追加180秒"]).reset_index(drop=True)


def _is_fallback(legacy_df: pd.DataFrame, final_df: pd.DataFrame) -> bool:
    return _canonical_for_compare(legacy_df).equals(_canonical_for_compare(final_df))


def _format_case_report(
    name: str,
    legacy_metric: Metric,
    final_metric: Metric,
    legacy_split: int,
    final_split: int,
    fallback: bool,
) -> str:
    lines: List[str] = []
    lines.append(f"\n=== {name} ===")
    lines.append("| 指標 | ①旧 | ③最終 | 削減 |")
    lines.append("|------|-----:|------:|----:|")
    for k in ["あふれ山数", "ユニーク遅延山数", "メイン遅延数", "リリーフ遅延数", "リリーフ山数"]:
        old_v = int(legacy_metric[k])
        new_v = int(final_metric[k])
        reduction = old_v - new_v
        lines.append(f"| {k} | {old_v} | {new_v} | {reduction:+d} |")

    legacy_score = _score_tuple(legacy_metric)
    final_score = _score_tuple(final_metric)
    lines.append(f"辞書順スコア ①旧={legacy_score} / ③最終={final_score}")
    if final_score < legacy_score:
        lines.append("判定: ③最終が改善")
    elif final_score == legacy_score:
        lines.append("判定: 同等")
    else:
        lines.append("判定: ③最終が悪化")

    lines.append(f"同便分断ペナルティ ①旧={legacy_split} / ③最終={final_split} / 改善量={(legacy_split - final_split):+d}")
    lines.append(f"フォールバック: {'発生' if fallback else '未発生'}")
    return "\n".join(lines)


def main() -> int:
    builders = [
        ("ケースA: タイト締切", _build_case_a_tight_deadline),
        ("ケースB: あふれ確定", _build_case_b_overflow_fixed),
        ("ケースC: 締切厳格維持", _build_case_d_prevents_late_main),
        ("ケースD: 混在レーン締切", _build_case_e_mixed_lanes_deadline),
        ("ケースE: 締切再並び成立", _build_case_f_deadline_reorder_feasible),
        ("ケースF: リリーフ再昇格", _build_case_g_relief_promoted),
        ("ケースG: 複数リリーフ", _build_case_h_multiple_relief),
    ]

    reports: List[str] = []
    fallback_count = 0
    improve_count = 0
    equal_count = 0
    worse_count = 0
    legacy_overflow_case_count = 0
    overflow_reduced_case_count = 0
    overflow_equal_case_count = 0
    overflow_worse_case_count = 0

    total_reduction = {
        "あふれ山数": 0,
        "ユニーク遅延山数": 0,
        "メイン遅延数": 0,
        "リリーフ遅延数": 0,
        "リリーフ山数": 0,
        "同便分断": 0,
    }

    for name, build in builders:
        proc_details, master_df = build()

        legacy_df = _legacy_assign_processes_by_arrival_time(proc_details, master_df)
        final_df = assign_processes_by_arrival_time_edf_greedy(proc_details, master_df)

        _, _, work_map, ddl_map = _mountain_context(proc_details, master_df)
        legacy_metric = _metrics(legacy_df, ddl_map, work_map)
        final_metric = _metrics(final_df, ddl_map, work_map)

        yama_cluster_map = _build_yama_cluster_key_map(proc_details, master_df)
        legacy_split = int(_cluster_split_penalty(legacy_df, yama_cluster_map))
        final_split = int(_cluster_split_penalty(final_df, yama_cluster_map))

        fallback = _is_fallback(legacy_df, final_df)
        fallback_count += int(fallback)

        legacy_score = _score_tuple(legacy_metric)
        final_score = _score_tuple(final_metric)
        if final_score < legacy_score:
            improve_count += 1
        elif final_score == legacy_score:
            equal_count += 1
        else:
            worse_count += 1

        overflow_diff = int(legacy_metric["あふれ山数"]) - int(final_metric["あふれ山数"])
        if int(legacy_metric["あふれ山数"]) > 0:
            legacy_overflow_case_count += 1
            if overflow_diff > 0:
                overflow_reduced_case_count += 1
            elif overflow_diff == 0:
                overflow_equal_case_count += 1
            else:
                overflow_worse_case_count += 1

        for k in ["あふれ山数", "ユニーク遅延山数", "メイン遅延数", "リリーフ遅延数", "リリーフ山数"]:
            total_reduction[k] += int(legacy_metric[k]) - int(final_metric[k])
        total_reduction["同便分断"] += int(legacy_split) - int(final_split)

        reports.append(
            _format_case_report(
                name=name,
                legacy_metric=legacy_metric,
                final_metric=final_metric,
                legacy_split=legacy_split,
                final_split=final_split,
                fallback=fallback,
            )
        )

    print("実証モード(案2): ①旧エンジン vs ③最終出力")
    print("対象ケース数:", len(builders))
    for block in reports:
        print(block)

    print("\n=== 集計 ===")
    print(f"フォールバック発生件数: {fallback_count}/{len(builders)}")
    print(f"辞書順判定 件数: 改善={improve_count} / 同等={equal_count} / 悪化={worse_count}")
    print(
        f"旧であふれ発生ケース: {legacy_overflow_case_count}/{len(builders)} "
        f"(削減={overflow_reduced_case_count}, 同等={overflow_equal_case_count}, 悪化={overflow_worse_case_count})"
    )
    print(
        "総削減量: "
        f"あふれ山数={total_reduction['あふれ山数']:+d}, "
        f"ユニーク遅延山数={total_reduction['ユニーク遅延山数']:+d}, "
        f"メイン遅延数={total_reduction['メイン遅延数']:+d}, "
        f"リリーフ遅延数={total_reduction['リリーフ遅延数']:+d}, "
        f"リリーフ山数={total_reduction['リリーフ山数']:+d}, "
        f"同便分断={total_reduction['同便分断']:+d}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
