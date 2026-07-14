# -*- coding: utf-8 -*-
"""CHかんばんセット — EDF + アイドル時間部分充填 貪欲スケジューラ。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..models.constants import (
    BASE_ONE_TIME,
    BASE_PER_PAL,
    MIDDLE_WORK,
    PROC_MAIN,
    PROC_OVERFLOW,
    PROC_RELIEF,
)
from ..utils.normalizer import _ZEN2HAN_DIGIT_COLON, _normalize_dest_name
from .process_assigner import (
    _adjust_start_for_breaks,
    _calc_work_end_with_breaks,
    _get_lane_count,
    _get_prev_bin_for_vendor,
    _is_hino_2lane_target,
    _is_truthy_flag,
    _legacy_assign_processes_by_arrival_time,
    _seconds_to_hhmm,
    _set_flag_main_limit_secs,
    _shift_index_for_secs,
    _shift_start_secs,
    _time_to_seconds,
    _to_operational_timeline_secs,
)

# process_assigner.py の既存値と一致
_SHIFT_START_SECS = [6 * 3600 + 25 * 60, 16 * 3600 + 40 * 60]
_ARRIVAL_BUFFER_SECS = 10 * 60


def cluster_by_store(rows: List[dict]) -> List[dict]:
    """同一STOREに異なるHINBANが同梱されるケースを1パレットに束ねる前処理。

    束ねルール:
    - 同一STORE内でHINBANの種類が複数 → 全行を1行に束ねる（同梱）
    - 同一STORE内でHINBANが全て同一  → 束ねない（別行のまま維持）

    束ね時の代表値:
    - 締切・解禁・移動工数は先頭行の値をそのまま採用
    - 移動工数は1パレット=1回のみ計上（種類数ぶん二重計上しない）
    - 同梱したHINBANの一覧は _merged_hinban（list）に保持し、
      出力時に元の表現へ復元できるようにする

    Parameters
    ----------
    rows : list[dict]
        仕分けエンジンに渡す前の生行データ（list of dict）。

    Returns
    -------
    list[dict]
        クラスター化後の行データ。列名・データ型は変更しない。
    """
    if not rows:
        return list(rows)

    def _get_store(row: dict) -> str:
        return str(row.get("ストア", row.get("SYUKKASAKI", ""))).strip()

    def _get_hinban(row: dict) -> str:
        return str(row.get("HINBAN", "")).strip()

    # STORE別にインデックスをグループ化（出現順を保持）
    store_indices: Dict[str, List[int]] = {}
    for i, row in enumerate(rows):
        store = _get_store(row)
        if store not in store_indices:
            store_indices[store] = []
        store_indices[store].append(i)

    consumed: set = set()
    result: List[dict] = []

    for i, row in enumerate(rows):
        if i in consumed:
            continue

        store = _get_store(row)
        group_idxs = store_indices[store]

        # このSTOREグループ内のHINBAN種類数を判定（出現順を保持した重複除去）
        hinbans_in_group = [_get_hinban(rows[j]) for j in group_idxs]
        seen_h: Dict[str, bool] = {}
        unique_hinbans: List[str] = []
        for h in hinbans_in_group:
            if h not in seen_h:
                seen_h[h] = True
                unique_hinbans.append(h)

        if len(unique_hinbans) <= 1:
            # 同一HINBAN（または空）のみ → 束ねずそのまま出力
            result.append(row)
        else:
            # 複数種のHINBAN → 先頭行（group_idxs[0]）を代表行として束ねる
            # 先頭行に到達したときだけ処理する
            if i != group_idxs[0]:
                continue
            merged = dict(rows[group_idxs[0]])  # 先頭行をコピー（移動工数は1回分のまま）
            merged["_merged_hinban"] = unique_hinbans
            # 出力時にSEBANGO等の同梱明細を復元できるよう、元行を保持する。
            merged["_merged_rows"] = [dict(rows[j]) for j in group_idxs]
            consumed.update(group_idxs)
            result.append(merged)

    return result


def _state_score(rows: List[dict], deadline_map: Dict[int, Optional[int]], work_map: Dict[int, int]) -> Tuple[int, int, int]:
    """目的関数: (ユニーク遅延山数, リリーフ遅延数, メイン遅延数)。"""
    late_main = _collect_late_yamas(rows, PROC_MAIN, deadline_map, work_map)
    late_relief = _collect_late_yamas(rows, PROC_RELIEF, deadline_map, work_map)
    return (len(set(late_main + late_relief)), len(late_relief), len(late_main))


def _lane_schedule_once(
    lane_end: int,
    lane_count: int,
    work_secs: int,
    start_floor: int,
) -> Tuple[int, int, int]:
    """単一レーンの次山開始/終了を返す（照合180秒 + 休憩補正込み）。"""
    next_idx = lane_count + 1
    inspection_delay = 180 if (next_idx >= 3 and next_idx % 2 == 1) else 0
    candidate = max(int(lane_end) + inspection_delay, int(start_floor or 0))
    start = _adjust_start_for_breaks(candidate, int(work_secs))
    end = _calc_work_end_with_breaks(start, int(work_secs))
    return start, end, inspection_delay


def _build_lane_schedule_rows(
    lane_rows: List[dict],
    work_map: Dict[int, int],
    start_floor_map: Dict[int, int],
    lane_start_secs: Optional[int] = None,
) -> List[dict]:
    """レーン順序から開始/終了時刻のシミュレーション結果を作る。"""
    start_secs = int(lane_start_secs if lane_start_secs is not None else min(_SHIFT_START_SECS))
    lane_end = start_secs
    lane_count = 0
    schedule_rows: List[dict] = []

    for idx, row in enumerate(lane_rows):
        yama_no = int(row.get("山通番", 0))
        work_secs = int(work_map.get(yama_no, row.get("引取工数_秒", 0) or 0))
        start_floor = int(start_floor_map.get(yama_no, row.get("開始時間_秒", 0) or 0))

        # 仮想山(-1)は「照合台数カウント」から除外する。
        # これにより通常山の照合判定(next_idx>=3 and 奇数)はOFF時と同じ並びになる。
        inspection_count = 0 if yama_no == -1 else lane_count
        start, end, inspection_delay = _lane_schedule_once(lane_end, inspection_count, work_secs, start_floor)
        schedule_rows.append(
            {
                "index": idx,
                "山通番": yama_no,
                "start_secs": int(start),
                "end_secs": int(end),
                "inspection_delay": int(inspection_delay),
                "row": row,
            }
        )
        lane_end = int(end)
        if yama_no != -1:
            lane_count += 1

    return schedule_rows


def _find_insertable_gaps(
    schedule_rows: List[dict],
    min_gap_secs: int,
    lane_start_secs: Optional[int] = None,
) -> List[dict]:
    """隙間探索: レーン内の空き時間から指定秒数以上の隙間を列挙する。"""
    gaps: List[dict] = []
    cursor = int(lane_start_secs if lane_start_secs is not None else min(_SHIFT_START_SECS))

    for item in schedule_rows:
        gap_start = int(cursor)
        gap_end = int(item["start_secs"])
        gap_secs = int(gap_end - gap_start)
        if gap_secs >= int(min_gap_secs):
            gaps.append(
                {
                    "insert_index": int(item["index"]),
                    "gap_start_secs": gap_start,
                    "gap_end_secs": gap_end,
                    "gap_secs": gap_secs,
                }
            )
        cursor = int(item["end_secs"])

    return gaps


def _select_first_gap_insertion(
    gaps: List[dict],
    virtual_work_secs: int,
    virtual_start_floor_secs: int,
    virtual_time_window: Optional[Tuple[int, int]] = None,
) -> Optional[dict]:
    """隙間探索: 最初に入る隙間へ仮想山を差し込む位置を返す。"""
    for gap in gaps:
        # 休憩補正と開始下限を考慮して、実際に作業開始できる時刻を決める。
        candidate_start = max(int(gap["gap_start_secs"]), int(virtual_start_floor_secs or 0))
        if virtual_time_window is not None:
            window_start, window_end = int(virtual_time_window[0]), int(virtual_time_window[1])
            candidate_start = max(candidate_start, window_start)
            if candidate_start >= window_end:
                continue

        start_secs = _adjust_start_for_breaks(candidate_start, int(virtual_work_secs))
        end_secs = _calc_work_end_with_breaks(start_secs, int(virtual_work_secs))

        if virtual_time_window is not None and end_secs > int(virtual_time_window[1]):
            continue
        if end_secs <= int(gap["gap_end_secs"]):
            return {
                "insert_index": int(gap["insert_index"]),
                "start_secs": int(start_secs),
                "end_secs": int(end_secs),
                "mode": "gap",
            }

    return None


def _select_push_insertion_by_deadline_margin(
    main_lane_rows: List[dict],
    virtual_row: dict,
    virtual_yama_no: int,
    work_map: Dict[int, int],
    start_floor_map: Dict[int, int],
    deadline_map: Dict[int, Optional[int]],
    lane_start_secs: Optional[int] = None,
) -> dict:
    """押し込み: 締切余裕が最も悪化しにくい位置を選ぶ。"""
    # 締切を持つ既存山が1つも無い場合は、後回しにせず先頭へ入れる。
    has_deadline = False
    for r in main_lane_rows:
        y = int(r.get("山通番", 0))
        if y == int(virtual_yama_no):
            continue
        if deadline_map.get(y) is not None:
            has_deadline = True
            break

    if not has_deadline:
        return {"insert_index": 0, "mode": "push_no_deadline"}

    best_idx = 0
    best_score: Optional[Tuple[int, int, int, int]] = None

    for idx in range(len(main_lane_rows) + 1):
        candidate_rows = list(main_lane_rows)
        candidate_rows.insert(idx, dict(virtual_row))
        schedule_rows = _build_lane_schedule_rows(candidate_rows, work_map, start_floor_map, lane_start_secs)

        margins: List[int] = []
        late_count = 0
        for item in schedule_rows:
            yama_no = int(item["山通番"])
            if yama_no == int(virtual_yama_no):
                continue
            ddl = deadline_map.get(yama_no)
            if ddl is None:
                continue
            margin = int(ddl) - int(item["end_secs"])
            margins.append(margin)
            if margin < 0:
                late_count += 1

        min_margin = min(margins) if margins else 10**9
        total_margin = int(sum(margins)) if margins else 10**9
        score = (int(late_count), -int(min_margin), -int(total_margin), int(idx))

        if best_score is None or score < best_score:
            best_score = score
            best_idx = idx

    return {"insert_index": int(best_idx), "mode": "push_deadline_margin"}


def _evacuate_existing_mountains_to_relief(
    main_lane_rows: List[dict],
    relief_lane_rows: List[dict],
    virtual_yama_no: int,
    work_map: Dict[int, int],
    start_floor_map: Dict[int, int],
    main_limit_end_secs: Optional[int],
    lane_start_secs: Optional[int] = None,
) -> dict:
    """リリーフ退避: メイン上限超過分を既存山だけ後ろから移す。"""
    current_main = list(main_lane_rows)
    current_relief = list(relief_lane_rows)
    evacuated_rows: List[dict] = []

    if main_limit_end_secs is None:
        return {
            "main_lane_rows": current_main,
            "relief_lane_rows": current_relief,
            "evacuated_rows": evacuated_rows,
            "main_schedule_rows": _build_lane_schedule_rows(current_main, work_map, start_floor_map, lane_start_secs),
            "relief_schedule_rows": _build_lane_schedule_rows(current_relief, work_map, start_floor_map, lane_start_secs),
            "main_over_limit": False,
        }

    while True:
        main_schedule_rows = _build_lane_schedule_rows(current_main, work_map, start_floor_map, lane_start_secs)
        current_end = int(main_schedule_rows[-1]["end_secs"]) if main_schedule_rows else int(
            lane_start_secs if lane_start_secs is not None else min(_SHIFT_START_SECS)
        )
        if current_end <= int(main_limit_end_secs):
            break

        # 退避対象は「既存山のみ」。仮想山はメインに残す。
        pop_idx = None
        for i in range(len(current_main) - 1, -1, -1):
            if int(current_main[i].get("山通番", 0)) != int(virtual_yama_no):
                pop_idx = i
                break
        if pop_idx is None:
            break

        moved_row = current_main.pop(pop_idx)
        evacuated_rows.append(moved_row)
        # 後ろから抜いた順を元の時系列へ戻すため、先頭へ積む。
        current_relief.insert(0, moved_row)

    main_schedule_rows = _build_lane_schedule_rows(current_main, work_map, start_floor_map, lane_start_secs)
    relief_schedule_rows = _build_lane_schedule_rows(current_relief, work_map, start_floor_map, lane_start_secs)
    final_end = int(main_schedule_rows[-1]["end_secs"]) if main_schedule_rows else int(
        lane_start_secs if lane_start_secs is not None else min(_SHIFT_START_SECS)
    )
    over_limit = final_end > int(main_limit_end_secs)

    return {
        "main_lane_rows": current_main,
        "relief_lane_rows": current_relief,
        "evacuated_rows": evacuated_rows,
        "main_schedule_rows": main_schedule_rows,
        "relief_schedule_rows": relief_schedule_rows,
        "main_over_limit": bool(over_limit),
    }


def _revalidate_relief_deadlines(
    relief_schedule_rows: List[dict],
    deadline_map: Dict[int, Optional[int]],
) -> List[dict]:
    """リリーフ再検証: 退避した山がリリーフ工程でも締切に間に合うか確認する。"""
    checks: List[dict] = []
    for item in relief_schedule_rows:
        yama_no = int(item.get("山通番", 0))
        end_secs = int(item.get("end_secs", 0))
        ddl_secs = deadline_map.get(yama_no)
        is_on_time = True if ddl_secs is None else (end_secs <= int(ddl_secs))
        checks.append(
            {
                "山通番": yama_no,
                "実開始時間": _seconds_to_hhmm(int(item.get("start_secs", 0))),
                "実終了時間": _seconds_to_hhmm(end_secs),
                "締切時間": "" if ddl_secs is None else _seconds_to_hhmm(int(ddl_secs)),
                "締切内": bool(is_on_time),
            }
        )
    return checks


def insert_virtual_mountain_into_lane(
    main_lane_rows: List[dict],
    relief_lane_rows: Optional[List[dict]],
    virtual_row: dict,
    work_map: Dict[int, int],
    start_floor_map: Dict[int, int],
    deadline_map: Dict[int, Optional[int]],
    main_limit_end_secs: Optional[int],
    min_gap_secs: int = 10 * 60,
    virtual_time_window: Optional[Tuple[int, int]] = None,
    lane_start_secs: Optional[int] = None,
) -> dict:
    """共通部品: 独立1山をメイン工程へ差し込み、必要ならリリーフ退避まで行う。"""
    # ===== 前準備（入力データの複製と仮想山パラメータ確定） =====
    current_main = [dict(r) for r in main_lane_rows]
    current_relief = [dict(r) for r in (relief_lane_rows or [])]
    virtual = dict(virtual_row)
    virtual_yama_no = int(virtual.get("山通番", -1))

    local_work_map = dict(work_map)
    local_start_floor_map = dict(start_floor_map)
    local_deadline_map = dict(deadline_map)

    if virtual_yama_no not in local_work_map:
        local_work_map[virtual_yama_no] = int(virtual.get("引取工数_秒", 0) or 0)
    if virtual_yama_no not in local_start_floor_map:
        local_start_floor_map[virtual_yama_no] = int(virtual.get("開始時間_秒", 0) or 0)
    if virtual_yama_no not in local_deadline_map:
        local_deadline_map[virtual_yama_no] = virtual.get("締め切り_秒", None)

    virtual_work_secs = int(local_work_map.get(virtual_yama_no, 0))
    virtual_floor_secs = int(local_start_floor_map.get(virtual_yama_no, 0))

    # ===== 隙間探索（10分以上の空きへ先に差し込む） =====
    current_schedule = _build_lane_schedule_rows(current_main, local_work_map, local_start_floor_map, lane_start_secs)

    # 仮想山は「始業前の準備時間」ではなく、既存山の実作業開始以降にのみ入れる。
    # そのため、現在スケジュール済みの既存山のうち最も早い実開始時刻を
    # 仮想山の開始下限として採用する。
    # current_schedule が空なら既存下限をそのまま使い、安全側に倒す。
    earliest_main_start_secs = min(
        (int(item.get("start_secs", 0)) for item in current_schedule),
        default=None,
    )
    if earliest_main_start_secs is not None:
        virtual_floor_secs = max(int(virtual_floor_secs), int(earliest_main_start_secs))
        # gap/push の両経路で同じ下限を使うため、start_floor_map 側にも反映する。
        local_start_floor_map[virtual_yama_no] = int(virtual_floor_secs)

    gaps = _find_insertable_gaps(current_schedule, int(min_gap_secs), lane_start_secs)
    gap_plan = _select_first_gap_insertion(
        gaps=gaps,
        virtual_work_secs=virtual_work_secs,
        virtual_start_floor_secs=virtual_floor_secs,
        virtual_time_window=virtual_time_window,
    )

    if gap_plan is not None:
        insert_index = int(gap_plan["insert_index"])
        insert_mode = str(gap_plan.get("mode", "gap"))
    else:
        # ===== 押し込み（締切余裕が最大の位置を選ぶ） =====
        push_plan = _select_push_insertion_by_deadline_margin(
            main_lane_rows=current_main,
            virtual_row=virtual,
            virtual_yama_no=virtual_yama_no,
            work_map=local_work_map,
            start_floor_map=local_start_floor_map,
            deadline_map=local_deadline_map,
            lane_start_secs=lane_start_secs,
        )
        insert_index = int(push_plan["insert_index"])
        insert_mode = str(push_plan.get("mode", "push"))

    current_main.insert(insert_index, virtual)

    # ===== リリーフ退避（メイン上限超過なら既存山のみ移動） =====
    evac = _evacuate_existing_mountains_to_relief(
        main_lane_rows=current_main,
        relief_lane_rows=current_relief,
        virtual_yama_no=virtual_yama_no,
        work_map=local_work_map,
        start_floor_map=local_start_floor_map,
        main_limit_end_secs=main_limit_end_secs,
        lane_start_secs=lane_start_secs,
    )

    # ===== リリーフ再検証（移した山の締切達成可否を確認） =====
    relief_checks = _revalidate_relief_deadlines(
        relief_schedule_rows=evac["relief_schedule_rows"],
        deadline_map=local_deadline_map,
    )

    return {
        "inserted": True,
        "insert_mode": insert_mode,
        "insert_index": int(insert_index),
        "virtual_yama_no": int(virtual_yama_no),
        "main_lane_rows": evac["main_lane_rows"],
        "relief_lane_rows": evac["relief_lane_rows"],
        "main_schedule_rows": evac["main_schedule_rows"],
        "relief_schedule_rows": evac["relief_schedule_rows"],
        "evacuated_existing_rows": evac["evacuated_rows"],
        "main_over_limit": bool(evac["main_over_limit"]),
        "relief_deadline_checks": relief_checks,
    }


def aggregate_proc_details_to_mountains(
    proc_details: pd.DataFrame,
    yama_set: set,
    start_time_map: Optional[Dict[int, str]] = None,
) -> List[dict]:
    """
    【案2実装】明細行を山ごとに集約し、各山の最初の1行を代表行として抽出。
    
    背景：
      - 入力proc_detailsには複数の明細行がある（山1が2行、山2が2行など）
      - スケジューラが明細行のまま処理すると、同じ山が複数回schedule_rowsに登場し、
        後勝ち上書きで時刻がずれる問題が発生していた
      - この関数で「山7行」に集約することで、各山が1行のみになり、
        後勝ちなしで正しい時刻が選ばれる
    
        入力：
      - proc_details: 明細行のDataFrame（山1が複数行あるなど）
      - yama_set: 対象とする山通番のセット（main_yamas | relief_yamas）
            - start_time_map: OFF時に確定した山ごとの実開始時間（HH:MM）
                ※ OFF時内部順（実開始時間順＋同時刻は山通番）を再現するために使用
    
    出力：
      - 山ごとに1行ずつの辞書リスト（合計N行、重複なし）
      - 実際の工数計算（work_map）は別途 _mountain_context() で集約済みなので、
        ここでは「コンテキスト」を保持するだけでよい
      - 最初の1行を代表とすることで、全ての必要な情報が保持される
    
    使用箇所：
      - gui.py Step 5-2: ON時のみ
      - OFF時は assign_processes_by_arrival_time に任せ、この関数は使わない
    """
    if proc_details is None or proc_details.empty:
        return []

    representative_rows: List[dict] = []
    safe_start_time_map = start_time_map or {}

    # ① 各山の代表行（最初の1行）を取得
    for yama_no in yama_set:
        # 各山の明細行をフィルタリング
        sub = proc_details[proc_details["山通番"] == int(yama_no)]

        if not sub.empty:
            # 最初の1行を代表行として抽出
            # （全ての必要な列が揃っているため、この1行でスケジューラに十分）
            rep = sub.iloc[0].to_dict()

            # OFF時で確定した実開始時間があれば、同じ列名「実開始時間」に反映して
            # OFF時内部計算の並びキー（実開始時間）をそのまま再現する。
            if int(yama_no) in safe_start_time_map:
                rep["実開始時間"] = str(safe_start_time_map.get(int(yama_no), ""))

            representative_rows.append(rep)

    # ② OFF時と同じキーでソート: 実開始時間（秒）昇順
    # ③ 同時刻は山通番昇順でタイブレーク
    representative_rows.sort(
        key=lambda r: (
            _time_to_seconds(str(r.get("実開始時間", ""))) is None,
            _time_to_seconds(str(r.get("実開始時間", ""))) or float("inf"),
            int(r.get("山通番", 0)),
        )
    )

    return representative_rows


def _mountain_context(proc_details: pd.DataFrame, master_df: pd.DataFrame) -> Tuple[List[dict], Dict[int, int], Dict[int, int], Dict[int, Optional[int]]]:
    """既存式で山ごとの工数/締切/開始下限を構築する。"""
    if proc_details is None or proc_details.empty:
        return [], {}, {}, {}

    df = proc_details.copy()
    df["移動工数"] = pd.to_numeric(df.get("移動工数", np.nan), errors="coerce")

    if master_df is None or master_df.empty:
        info = []
        prev_floor = {}
        for yama, sub in df.groupby("山通番", sort=True):
            pal = int(sub.shape[0])
            max_cost = float(sub["移動工数"].max()) if sub["移動工数"].notna().any() else 0.0
            work = int(np.round(max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0))
            y = int(yama)
            info.append({"山通番": y, "引取工数_秒": work, "締め切り_秒": None, "開始時間_秒": 0})
            prev_floor[y] = 0
        work_map = {m["山通番"]: int(m["引取工数_秒"]) for m in info}
        ddl_map = {m["山通番"]: m.get("締め切り_秒") for m in info}
        return info, prev_floor, work_map, ddl_map

    master = master_df.copy()
    master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip().apply(_normalize_dest_name)
    master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
    master["入車時間"] = master["入車時間"].astype(str).str.strip()
    master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in master.iterrows()}
    has_set_flag_col = "セットありフラグ" in master.columns
    set_flag_map = {
        (r["OData_納入先"], r["NONYUHIBIN"]): _is_truthy_flag(r.get("セットありフラグ", ""))
        for _, r in master.iterrows()
    }

    vendor_shift_first_bin: Dict[Tuple[str, int], str] = {}
    vendor_shift_first_offset: Dict[Tuple[str, int], int] = {}
    for (v, bin_no), pickup_time in master_map.items():
        ts = _to_operational_timeline_secs(_time_to_seconds(pickup_time))
        if ts is None:
            continue
        shift_idx = _shift_index_for_secs(ts)
        shift_start = _shift_start_secs(shift_idx)
        offset = (ts - shift_start) % (24 * 3600)
        key = (v, shift_idx)
        if key not in vendor_shift_first_offset or offset < vendor_shift_first_offset[key]:
            vendor_shift_first_offset[key] = offset
            vendor_shift_first_bin[key] = str(bin_no).strip()

    vendor_time_groups: Dict[str, Dict[int, List[str]]] = {}
    for (v, bin_no), pickup_time in master_map.items():
        vendor_time_groups.setdefault(v, {})
        ts = _to_operational_timeline_secs(_time_to_seconds(pickup_time))
        if ts is None:
            continue
        mins = int(ts) // 60
        vendor_time_groups[v].setdefault(mins, []).append(bin_no)

    vendor_sorted_groups: Dict[str, List[Tuple[int, List[str]]]] = {}
    for v, time_dict in vendor_time_groups.items():
        sorted_times = sorted(time_dict.keys())
        vendor_sorted_groups[v] = [(t, time_dict[t]) for t in sorted_times]

    vendor_bin_numbers: Dict[str, List[int]] = {}
    for (v, bin_no), _ in master_map.items():
        try:
            bn = int(str(bin_no).strip())
        except Exception:
            continue
        vendor_bin_numbers.setdefault(v, set()).add(bn)
    vendor_bin_numbers = {v: sorted(list(bset)) for v, bset in vendor_bin_numbers.items()}

    def _get_prev_group_time(vendor: str, current_mins: int) -> Optional[int]:
        if vendor not in vendor_sorted_groups:
            return None
        groups = vendor_sorted_groups[vendor]
        prev_time = None
        for time_mins, _ in groups:
            if time_mins >= current_mins:
                break
            prev_time = time_mins
        return prev_time

    info: List[dict] = []
    prev_arrival_floor_map: Dict[int, int] = {}

    for yama, sub in df.groupby("山通番", sort=True):
        yama_int = int(yama)
        pal = int(sub.shape[0])
        max_cost = float(sub["移動工数"].max()) if sub["移動工数"].notna().any() else 0.0
        pick_cost_secs = int(np.round(max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0))

        deadline_secs = None
        start_time_secs = None
        prev_arrival_floor_secs = None

        for _, row in sub.iterrows():
            _dest_raw = str(row.get("納入先", "")).strip()
            if not _dest_raw:
                _dest_raw = str(row.get("OData_納入先", "")).strip()
            if not _dest_raw:
                _dest_raw = str(row.get("SYUKKASAKI", "")).strip()
            vendor = _normalize_dest_name(_dest_raw)
            nony = str(row.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue

            pickup = master_map.get((vendor, order2), "")
            if not pickup:
                continue
            pickup_secs = _to_operational_timeline_secs(_time_to_seconds(pickup))
            if pickup_secs is None:
                continue

            set_flag = bool(set_flag_map.get((vendor, order2), False))
            shift_idx = _shift_index_for_secs(pickup_secs)
            strict_deadline = max(0, int(pickup_secs) - _ARRIVAL_BUFFER_SECS)
            is_first_trip_in_shift = (vendor_shift_first_bin.get((vendor, shift_idx), "") == order2)

            if not has_set_flag_col:
                if vendor == "武部":
                    mins = pickup_secs // 60
                    prev_group_time = _get_prev_group_time(vendor, mins)
                    if prev_group_time is not None:
                        st = (prev_group_time + 10) * 60
                        st_prev = st
                    else:
                        st = 0
                        st_prev = 0
                else:
                    try:
                        current_bin = int(order2)
                        lane_count = _get_lane_count(vendor)
                        prev_bin = _get_prev_bin_for_vendor(
                            vendor,
                            current_bin,
                            vendor_bin_numbers,
                            allow_wrap=False,
                            offset=lane_count if _is_hino_2lane_target(vendor) else 1,
                            lane_parity=(current_bin % 2) if _is_hino_2lane_target(vendor) and lane_count == 2 else None,
                        )
                        if prev_bin is not None:
                            prev_pickup = master_map.get((vendor, prev_bin), "")
                            prev_secs = _to_operational_timeline_secs(_time_to_seconds(prev_pickup)) if prev_pickup else None
                            if prev_secs is not None:
                                st = prev_secs + 10 * 60
                                st_prev = st
                            else:
                                st = 0
                                st_prev = 0
                        else:
                            st = 0
                            st_prev = 0
                    except (ValueError, TypeError):
                        st = 0
                        st_prev = 0
            elif set_flag:
                if vendor == "武部":
                    mins = pickup_secs // 60
                    prev_group_time = _get_prev_group_time(vendor, mins)
                    if prev_group_time is not None:
                        st = (prev_group_time + 10) * 60
                        st_prev = st
                    else:
                        st = pickup_secs + 10 * 60
                        st_prev = st
                else:
                    try:
                        current_bin = int(order2)
                        lane_count = _get_lane_count(vendor)
                        prev_bin = _get_prev_bin_for_vendor(
                            vendor,
                            current_bin,
                            vendor_bin_numbers,
                            allow_wrap=True,
                            offset=lane_count if _is_hino_2lane_target(vendor) else 1,
                            lane_parity=(current_bin % 2) if _is_hino_2lane_target(vendor) and lane_count == 2 else None,
                        )
                        if prev_bin is not None:
                            prev_pickup = master_map.get((vendor, prev_bin), "")
                            prev_secs = _to_operational_timeline_secs(_time_to_seconds(prev_pickup)) if prev_pickup else None
                            if prev_secs is not None:
                                st = prev_secs + 10 * 60
                                st_prev = st
                            else:
                                st = 0
                                st_prev = 0
                        else:
                            st = 0
                            st_prev = 0
                    except (ValueError, TypeError):
                        st = 0
                        st_prev = 0
            elif is_first_trip_in_shift:
                st = _shift_start_secs(shift_idx) + 15 * 60
                try:
                    current_bin = int(order2)
                    prev_bin = _get_prev_bin_for_vendor(
                        vendor,
                        current_bin,
                        vendor_bin_numbers,
                        allow_wrap=False,
                        offset=1,
                    )
                    if prev_bin is not None:
                        prev_pickup = master_map.get((vendor, prev_bin), "")
                        prev_secs = _to_operational_timeline_secs(_time_to_seconds(prev_pickup)) if prev_pickup else None
                        st_prev = (prev_secs + 10 * 60) if prev_secs is not None else 0
                    else:
                        st_prev = 0
                except (ValueError, TypeError):
                    st_prev = 0
            elif vendor == "武部":
                mins = pickup_secs // 60
                prev_group_time = _get_prev_group_time(vendor, mins)
                if prev_group_time is not None:
                    st = (prev_group_time + 10) * 60
                    st_prev = st
                else:
                    st = pickup_secs + 10 * 60
                    st_prev = st
            else:
                try:
                    current_bin = int(order2)
                    lane_count = _get_lane_count(vendor)
                    prev_bin = _get_prev_bin_for_vendor(
                        vendor,
                        current_bin,
                        vendor_bin_numbers,
                        allow_wrap=True,
                        offset=lane_count if _is_hino_2lane_target(vendor) else 1,
                        lane_parity=(current_bin % 2) if _is_hino_2lane_target(vendor) and lane_count == 2 else None,
                    )
                    if prev_bin is not None:
                        prev_pickup = master_map.get((vendor, prev_bin), "")
                        prev_secs = _to_operational_timeline_secs(_time_to_seconds(prev_pickup)) if prev_pickup else None
                        if prev_secs is not None:
                            st = prev_secs + 10 * 60
                            st_prev = st
                        else:
                            st = 0
                            st_prev = 0
                    else:
                        st = 0
                        st_prev = 0
                except (ValueError, TypeError):
                    st = 0
                    st_prev = 0

            effective_deadline = strict_deadline
            if has_set_flag_col and set_flag:
                limit_from_st = _set_flag_main_limit_secs(_shift_index_for_secs(int(st))) if (st is not None and st > 0) else 0
                limit_from_pickup = _set_flag_main_limit_secs(shift_idx)
                effective_deadline = max(effective_deadline, limit_from_st, limit_from_pickup)

            if deadline_secs is None or effective_deadline < deadline_secs:
                deadline_secs = effective_deadline
            if start_time_secs is None or st > start_time_secs:
                start_time_secs = st
            if prev_arrival_floor_secs is None or st_prev > prev_arrival_floor_secs:
                prev_arrival_floor_secs = st_prev

        info.append(
            {
                "山通番": yama_int,
                "引取工数_秒": pick_cost_secs,
                "締め切り_秒": deadline_secs,
                "開始時間_秒": int(start_time_secs or 0),
            }
        )
        prev_arrival_floor_map[yama_int] = int(prev_arrival_floor_secs or 0)

    work_map = {m["山通番"]: int(m["引取工数_秒"]) for m in info}
    ddl_map = {m["山通番"]: m.get("締め切り_秒") for m in info}
    return info, prev_arrival_floor_map, work_map, ddl_map


def _build_bin_clusters(
    rows: List[dict],
    master_map: Dict[Tuple[str, str], int],
) -> Dict[Tuple[str, str], List[dict]]:
    """同便 (vendor, order2) ごとに山をグルーピングする。"""
    clusters: Dict[Tuple[str, str], List[dict]] = {}
    for r in rows:
        y = int(r["山通番"])
        key = r.get("cluster_key")
        if not key:
            key = (f"__YAMA__{y}", f"{y:02d}")
        clusters.setdefault(key, []).append(r)

    for key in list(clusters.keys()):
        clusters[key].sort(
            key=lambda x: (
                x.get("締め切り_秒") is None,
                x.get("締め切り_秒") or float("inf"),
                int(x.get("pickup_秒") or 0),
                int(x.get("山通番", 0)),
            )
        )
    return clusters


def _cluster_release_time(
    cluster_key: Tuple[str, str],
    master_map: Dict[Tuple[str, str], int],
    is_first_bin: bool,
) -> int:
    """クラスターの解禁時刻を返す（前便+10分 / 1便目+15分）。"""
    vendor, order2 = cluster_key
    pickup = master_map.get((vendor, order2))
    if pickup is None:
        return 0

    if is_first_bin:
        return int(pickup) + 15 * 60

    try:
        cur = int(str(order2).strip())
    except Exception:
        return int(pickup) + 10 * 60

    bins = sorted(
        int(str(k[1]).strip())
        for k in master_map.keys()
        if str(k[0]) == str(vendor) and str(k[1]).strip().isdigit()
    )
    if not bins:
        return int(pickup) + 10 * 60

    lowers = [b for b in bins if b < cur]
    prev = max(lowers) if lowers else max(bins)
    prev_pickup = master_map.get((vendor, f"{prev:02d}"))
    if prev_pickup is None:
        return int(pickup) + 10 * 60
    return int(prev_pickup) + 10 * 60


def _fill_idle(
    idle_start: int,
    idle_end: int,
    available_yamas: List[dict],
    work_map: Dict[int, int],
) -> List[dict]:
    """アイドル区間内に完全終了可能な山を入車順で詰める。"""
    t = int(idle_start)
    selected: List[dict] = []
    candidates = sorted(
        available_yamas,
        key=lambda m: (
            m.get("pickup_秒") is None,
            m.get("pickup_秒") or float("inf"),
            int(m.get("山通番", 0)),
        ),
    )

    for m in candidates:
        y = int(m["山通番"])
        release = int(m.get("開始時間_秒") or 0)
        if t < release:
            continue
        start = _adjust_start_for_breaks(max(t, release), int(work_map.get(y, 0)))
        end = _calc_work_end_with_breaks(start, int(work_map.get(y, 0)))
        if end <= int(idle_end):
            mm = dict(m)
            mm["_idle_start"] = start
            mm["_idle_end"] = end
            selected.append(mm)
            t = end

    return selected


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


def _assign_with_fallback(
    yama: dict,
    main_end: int,
    main_count: int,
    relief_end: int,
    relief_count: int,
    prev_floor_map: Dict[int, int],
) -> Tuple[dict, int, int, int, int]:
    """メイン→リリーフ→あふれの順で割当し、レーン状態を更新する。"""
    y = int(yama["山通番"])
    work = int(yama["引取工数_秒"])
    floor = int(yama.get("開始時間_秒") or 0)
    ddl = yama.get("締め切り_秒")

    m_start, m_end, m_ins = _lane_schedule_once(main_end, main_count, work, floor)
    if ddl is None or m_end <= int(ddl):
        row = {
            "山通番": y,
            "山工程": PROC_MAIN,
            "実開始時間": _seconds_to_hhmm(m_start),
            "前倒し": False,
            "照合追加180秒": bool(m_ins),
        }
        return row, m_end, main_count + 1, relief_end, relief_count

    r_start, r_end, r_ins = _lane_schedule_once(relief_end, relief_count, work, floor)
    if ddl is None or r_end <= int(ddl):
        row = {
            "山通番": y,
            "山工程": PROC_RELIEF,
            "実開始時間": _seconds_to_hhmm(r_start),
            "前倒し": False,
            "照合追加180秒": bool(r_ins),
        }
        return row, main_end, main_count, r_end, relief_count + 1

    overflow_floor = int(prev_floor_map.get(y) or floor)
    o_start = _adjust_start_for_breaks(overflow_floor, work)
    row = {
        "山通番": y,
        "山工程": PROC_OVERFLOW,
        "実開始時間": _seconds_to_hhmm(o_start),
        "前倒し": False,
        "照合追加180秒": False,
    }
    return row, main_end, main_count, relief_end, relief_count


def _edf_greedy_assign(
    clusters: Dict[Tuple[str, str], List[dict]],
    deadline_map: Dict[int, Optional[int]],
    work_map: Dict[int, int],
    release_map: Dict[Tuple[str, str], int],
    prev_floor_map: Dict[int, int],
) -> List[dict]:
    """EDF順クラスター処理 + アイドル充填 + 同便連続維持。"""
    main_end = min(_SHIFT_START_SECS)
    main_count = 0
    relief_end = min(_SHIFT_START_SECS)
    relief_count = 0
    results: List[dict] = []

    remaining: Dict[Tuple[str, str], List[dict]] = {k: list(v) for k, v in clusters.items() if v}

    def cluster_deadline(key: Tuple[str, str]) -> float:
        rows = remaining.get(key, [])
        if not rows:
            return float("inf")
        ddls = [r.get("締め切り_秒") for r in rows if r.get("締め切り_秒") is not None]
        return float(min(ddls)) if ddls else float("inf")

    while remaining:
        target_key = sorted(
            remaining.keys(),
            key=lambda k: (cluster_deadline(k), release_map.get(k, 0), str(k), int(remaining[k][0].get("山通番", 0))),
        )[0]
        target_release = int(release_map.get(target_key, 0))

        if main_end < target_release:
            # アイドル区間は他クラスターの先頭山のみを候補化（同便連続を維持）
            candidate_heads = []
            for k, rows in remaining.items():
                if k == target_key or not rows:
                    continue
                if int(release_map.get(k, 0)) > int(main_end):
                    continue
                candidate_heads.append(dict(rows[0]))

            fill_items = _fill_idle(main_end, target_release, candidate_heads, work_map)
            if not fill_items:
                main_end = target_release
            else:
                for fi in fill_items:
                    y = int(fi["山通番"])
                    row, main_end, main_count, relief_end, relief_count = _assign_with_fallback(
                        fi, main_end, main_count, relief_end, relief_count, prev_floor_map
                    )
                    row["前倒し"] = True
                    results.append(row)
                    key = fi.get("cluster_key")
                    if key in remaining:
                        remaining[key] = [r for r in remaining[key] if int(r["山通番"]) != y]
                        if not remaining[key]:
                            remaining.pop(key, None)
                if target_key not in remaining:
                    continue

        # 同便クラスター連続: target_key を空になるまで処理
        for yama in list(remaining.get(target_key, [])):
            row, main_end, main_count, relief_end, relief_count = _assign_with_fallback(
                yama, main_end, main_count, relief_end, relief_count, prev_floor_map
            )
            results.append(row)
        remaining.pop(target_key, None)

    return results


def _cluster_split_penalty(rows_df: pd.DataFrame, yama_cluster_map: Dict[int, Tuple[str, str]]) -> int:
    if rows_df is None or rows_df.empty:
        return 0
    main_rows = rows_df[rows_df["山工程"].astype(str) == PROC_MAIN].copy()
    if main_rows.empty:
        return 0
    main_rows["_start"] = main_rows["実開始時間"].astype(str).map(_time_to_seconds)
    main_rows = main_rows.sort_values(["_start", "山通番"], na_position="last")
    seq = [yama_cluster_map.get(int(y), ("", "")) for y in main_rows["山通番"].tolist()]
    if not seq:
        return 0

    segments: Dict[Tuple[str, str], int] = {}
    prev = None
    for k in seq:
        if k != prev:
            segments[k] = segments.get(k, 0) + 1
        prev = k
    return sum(max(0, c - 1) for c in segments.values())


def assign_processes_by_arrival_time_edf_greedy(proc_details: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """EDF + 同便クラスター連続 + アイドル部分充填で工程割付を行う。"""
    if proc_details is None or proc_details.empty:
        return pd.DataFrame(columns=["山通番", "山工程", "実開始時間", "照合追加180秒"])

    legacy_df = _legacy_assign_processes_by_arrival_time(proc_details, master_df)
    mountain_info, prev_floor_map, work_map, ddl_map = _mountain_context(proc_details, master_df)
    if not mountain_info:
        return legacy_df

    # 山ごとの主便キーを構築（vendor + order2）
    key_map: Dict[int, Tuple[str, str]] = {}
    pickup_map: Dict[int, Optional[int]] = {}

    detail_df = proc_details.copy()
    master = master_df.copy() if master_df is not None else pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])
    if not master.empty:
        master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip().apply(_normalize_dest_name)
        master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
        master["入車時間"] = master["入車時間"].astype(str).str.strip()
    master_secs_map: Dict[Tuple[str, str], int] = {}
    for _, r in master.iterrows():
        p = _to_operational_timeline_secs(_time_to_seconds(str(r.get("入車時間", ""))))
        if p is None:
            continue
        master_secs_map[(str(r.get("OData_納入先", "")), str(r.get("NONYUHIBIN", "")))] = int(p)

    for m in mountain_info:
        y = int(m["山通番"])
        sub = detail_df[detail_df["山通番"] == y]
        candidates = []
        for _, row in sub.iterrows():
            vendor_raw = str(row.get("納入先", "")).strip() or str(row.get("OData_納入先", "")).strip() or str(row.get("SYUKKASAKI", "")).strip()
            vendor = _normalize_dest_name(vendor_raw)
            nony = str(row.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue
            pickup = master_secs_map.get((vendor, order2))
            candidates.append((pickup is None, pickup or float("inf"), vendor, order2))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            _, psec, vendor, order2 = candidates[0]
            key_map[y] = (vendor, order2)
            pickup_map[y] = None if psec == float("inf") else int(psec)
        else:
            key_map[y] = (f"__YAMA__{y}", f"{y:02d}")
            pickup_map[y] = None

    rows = []
    for m in mountain_info:
        y = int(m["山通番"])
        mm = dict(m)
        mm["cluster_key"] = key_map.get(y)
        mm["pickup_秒"] = pickup_map.get(y)
        rows.append(mm)

    clusters = _build_bin_clusters(rows, master_secs_map)
    release_map: Dict[Tuple[str, str], int] = {}
    for k, rs in clusters.items():
        floors = [int(r.get("開始時間_秒") or 0) for r in rs]
        release_map[k] = max(floors) if floors else 0

    new_rows = _edf_greedy_assign(clusters, ddl_map, work_map, release_map, prev_floor_map)
    new_df = pd.DataFrame(new_rows).sort_values("山通番").reset_index(drop=True)

    # 新旧比較（目的関数同等以上 + 同便分断ペナルティでタイブレーク）
    new_score = _state_score(new_rows, ddl_map, work_map)
    legacy_rows = legacy_df.to_dict(orient="records") if legacy_df is not None else []
    legacy_score = _state_score(legacy_rows, ddl_map, work_map)

    new_split = _cluster_split_penalty(new_df, key_map)
    legacy_split = _cluster_split_penalty(legacy_df, key_map)

    if new_score < legacy_score:
        return new_df
    if new_score == legacy_score and new_split < legacy_split:
        return new_df
    return legacy_df


def compare_scheduler_vs_legacy(proc_details: pd.DataFrame, master_df: pd.DataFrame) -> dict:
    """新旧スコアと結果を返す比較ユーティリティ。"""
    legacy_df = _legacy_assign_processes_by_arrival_time(proc_details, master_df)
    new_df = assign_processes_by_arrival_time_edf_greedy(proc_details, master_df)
    mountain_info, _, work_map, ddl_map = _mountain_context(proc_details, master_df)
    _ = mountain_info

    return {
        "new_score": _state_score(new_df.to_dict(orient="records"), ddl_map, work_map),
        "legacy_score": _state_score(legacy_df.to_dict(orient="records"), ddl_map, work_map),
        "new_result": new_df,
        "legacy_result": legacy_df,
    }
