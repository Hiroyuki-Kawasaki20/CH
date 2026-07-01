# -*- coding: utf-8 -*-
"""
STEP1-3 本番フロー統合調査スクリプト（本物データ版）
======================================================
目的: GUI本番フロー（run_pipeline → cluster_by_store → compute_proc_details
      → assign_processes_by_arrival_time）を実データで通し、
      「07便がリリーフに落ちること」を確認する（バグ再現）。

入力:
  - 出荷情報_CH_最新版.csv（base_dir）
  - 出荷場一覧.csv（base_dir）
  - 入車時間マスタ.xlsx（プロジェクトルート）

実行方法:
  conda run -n DIG_new python analysis_full_pipeline_live.py

出力:
  - コンソール: 山通番・NONYUHIBIN末尾・締切・工程割当
  - 比較表CSV: analysis_pipeline_compare_<timestamp>.csv
"""

import sys
import os
import copy
import traceback
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# プロジェクトルートをsys.pathに追加
PROJ_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ_ROOT))

# ===== インポート =====
from src.services.data_loader import load_data, DataManager, load_pickup_time_master_xlsx, get_master_path
from src.services.sorter import run_pipeline
from src.services.scheduler import cluster_by_store
from src.services.process_assigner import (
    compute_proc_details,
    assign_processes_by_arrival_time,
    _pick_next_main_mountain,
    _legacy_assign_processes_by_arrival_time,
    DAY_SECS,
    PROC_MAIN,
    PROC_RELIEF,
    PROC_OVERFLOW,
)
from src.models.constants import DEFAULT_HEIGHT_CAP, DEFAULT_MIXING_KEY

# ===== 設定 =====
HEIGHT_CAP = DEFAULT_HEIGHT_CAP   # 2450
MIXING_KEY = DEFAULT_MIXING_KEY   # "UKEIRE"（DEFAULT_MIXING_KEY確認済み）

# 対象日（最新データから自動選択）
TARGET_DATE_PREFIX = None  # None なら自動選択（最新日付）

# ===== モンキーパッチ用グローバル変数 =====
_selection_log_raw = []
_selection_log_eval = []
_current_log_target = None  # "raw" or "eval"


def _build_pipeline_selections(df_ship: pd.DataFrame, df_places: pd.DataFrame, date_prefix: str) -> list:
    """
    指定日付プレフィックスの全便に対するselections（{"便名","受入","オーダー"}）を自動生成する。
    
    Returns:
        list[dict]: 便ごとのselections
    """
    # 出荷場一覧から有効な便名・受入の組み合わせを取得
    dm = DataManager(df_ship, df_places)
    
    # 日付プレフィックスで絞った NONYUHIBIN の一覧
    matching_orders = df_ship[
        df_ship["NONYUHIBIN"].astype(str).str.startswith(date_prefix)
    ]["NONYUHIBIN"].astype(str).unique().tolist()
    
    if not matching_orders:
        print(f"[警告] date_prefix={date_prefix} に一致するNONYUHIBINがありません")
        return []
    
    # 便名 × 受入 × オーダーの組み合わせを列挙
    selections = []
    routes = dm.get_routes()
    
    for route in routes:
        for receipt in dm.get_receipts_for_route(route):
            orders_for_rr = []
            for order in matching_orders:
                orders_cand = dm.get_orders_for_route_receipt(route, receipt)
                if order in orders_cand:
                    orders_for_rr.append(order)
            for order in orders_for_rr:
                sel = {"便名": route, "受入": receipt, "オーダー": order}
                # 重複除去
                if sel not in selections:
                    selections.append(sel)
    
    return selections


def _make_kvc_selections_all_date(df_ship: pd.DataFrame, df_places: pd.DataFrame, date_prefix: str) -> list:
    """
    KVC（九州・SYUKKASAKI=8482）に特化した selections を生成する。
    GUI では KVC-B7 などの表示名を内部名「九州」に変換してから渡すので、
    ここでは「九州」をそのまま使う。
    
    Returns: list[dict]
    """
    dm = DataManager(df_ship, df_places)
    
    # 九州便の受入一覧
    kvc_receipts = []
    for receipt in dm.get_receipts_for_route("九州"):
        kvc_receipts.append(receipt)
    
    # 対象日の九州便オーダー
    kvc_orders = sorted(
        df_ship[
            (df_ship["SYUKKASAKI"].astype(str) == "8482") &
            (df_ship["NONYUHIBIN"].astype(str).str.startswith(date_prefix))
        ]["NONYUHIBIN"].astype(str).unique().tolist()
    )
    
    selections = []
    for receipt in kvc_receipts:
        for order in kvc_orders:
            orders_cand = dm.get_orders_for_route_receipt("九州", receipt)
            if order in orders_cand:
                sel = {"便名": "九州", "受入": receipt, "オーダー": order}
                if sel not in selections:
                    selections.append(sel)
    
    # ukeire付き（便名の補足）
    # 出荷場一覧の受入コード → UKEIRE対応を探す
    kvc_places = df_places[df_places["便名"] == "九州"]
    for sel in selections:
        # 対応するUKEIREを探す（参考情報として付与）
        row = kvc_places[kvc_places["受入"] == sel["受入"]]
        if not row.empty:
            # 出荷情報から実際のUKEIREを拾う
            ukeire_vals = df_ship[
                (df_ship["NONYUHIBIN"].astype(str) == sel["オーダー"]) &
                (df_ship["SYUKKASAKI"].astype(str) == "8482")
            ]["UKEIRE"].unique().tolist()
            if ukeire_vals:
                sel["ukeire"] = str(ukeire_vals[0]).strip()
    
    return selections


def _run_full_pipeline(df_ship, df_places, master_df, selections, use_eval_deadline: bool):
    """
    GUI本番フローをまるごと実行する。
    
    use_eval_deadline=False: 現状（raw締切）
    use_eval_deadline=True:  改修案（eval締切に補正）
    
    Returns:
        (mountain_proc_df, proc_details_df, selection_log)
    """
    import src.services.process_assigner as pa
    
    selection_log = []
    
    if use_eval_deadline:
        # ===== eval締切版: _pick_next_main_mountain をモンキーパッチ =====
        _original_pick = pa._pick_next_main_mountain
        
        def _patched_eval(unscheduled, main_end_time, main_mountain_count):
            """
            eval締切（24時間軸補正後）でソートする改修案のシミュレーション。
            _deadline_for_eval と同等の補正を reproduce する。
            """
            from src.services.process_assigner import DAY_SECS
            
            def _eval_ddl(mountain_info_dict, current_end_secs):
                raw_ddl = mountain_info_dict.get("締め切り_秒")
                if raw_ddl is None:
                    return None
                ddl = int(raw_ddl)
                if current_end_secs is not None and int(current_end_secs) >= DAY_SECS and ddl < DAY_SECS:
                    return ddl + DAY_SECS
                return ddl
            
            with_deadline = [(m, idx) for idx, m in enumerate(unscheduled) if m.get("締め切り_秒") is not None]
            no_deadline = [(m, idx) for idx, m in enumerate(unscheduled) if m.get("締め切り_秒") is None]
            
            if with_deadline:
                primary = sorted(
                    with_deadline,
                    key=lambda x: (_eval_ddl(x[0], main_end_time), x[0]["山通番"])
                )[0][0]
            else:
                primary = no_deadline[0][0]
            
            # 前倒し候補
            safe_prefetch = []
            if with_deadline:
                primary_ddl = _eval_ddl(primary, main_end_time)
                for m, _ in (with_deadline + no_deadline):
                    m_ddl = _eval_ddl(m, main_end_time)
                    if m_ddl is None or (primary_ddl is not None and m_ddl <= primary_ddl):
                        safe_prefetch.append((m_ddl, -int(m.get("引取工数_秒", 0)), int(m.get("山通番", 0)), m))
                safe_prefetch.sort(key=lambda x: (x[0] is None, x[0] or float("inf"), x[1], x[2]))
                if safe_prefetch:
                    chosen = safe_prefetch[0][3]
                    is_prefetch = (chosen["山通番"] != primary["山通番"])
                    selection_log.append({
                        "選択順": main_mountain_count + 1,
                        "山通番": chosen["山通番"],
                        "前倒し": is_prefetch,
                        "締め切り_秒_raw": chosen.get("締め切り_秒"),
                        "eval締め切り_秒": _eval_ddl(chosen, main_end_time),
                    })
                    return chosen, is_prefetch
            
            # フォールバック
            selection_log.append({
                "選択順": main_mountain_count + 1,
                "山通番": primary["山通番"],
                "前倒し": False,
                "締め切り_秒_raw": primary.get("締め切り_秒"),
                "eval締め切り_秒": _eval_ddl(primary, main_end_time),
            })
            return primary, False
        
        pa._pick_next_main_mountain = _patched_eval
    else:
        # ===== raw締切版: ログ収集のみ（本体ロジックはそのまま）=====
        _original_pick = pa._pick_next_main_mountain
        
        def _patched_raw(unscheduled, main_end_time, main_mountain_count):
            result = _original_pick(unscheduled, main_end_time, main_mountain_count)
            chosen, is_prefetch = result
            selection_log.append({
                "選択順": main_mountain_count + 1,
                "山通番": chosen["山通番"],
                "前倒し": is_prefetch,
                "締め切り_秒_raw": chosen.get("締め切り_秒"),
                "eval締め切り_秒": None,  # raw版では補正なし
            })
            return result
        
        pa._pick_next_main_mountain = _patched_raw
    
    try:
        # Step1: run_pipeline
        filtered, expanded, group_results, group_details, s1_summary, s1_details, _lane_end_times = run_pipeline(
            DataManager(df_ship, df_places),
            selections,
            HEIGHT_CAP,
            MIXING_KEY,
            master_df=master_df,
            return_lane_end_times=True,
        )
        
        if filtered.empty:
            print("[警告] フィルタ結果が空です。selectionsを確認してください。")
            return None, None, selection_log
        
        print(f"  filter結果: {len(filtered)}行, expanded: {len(expanded)}行")
        
        # Step2: build_all_mountain_details
        from src.services.sorter import build_all_mountain_details
        all_mountain_details = build_all_mountain_details(group_details, s1_details)
        print(f"  all_mountain_details: {len(all_mountain_details)}行")
        
        if all_mountain_details.empty:
            print("[警告] all_mountain_detailsが空です。")
            return None, None, selection_log
        
        # Step3: cluster_by_store
        rows = all_mountain_details.to_dict(orient="records")
        rows = cluster_by_store(rows)
        
        # カラム順序を維持（gui.py準拠）
        ordered_cols = ["山通番", "便名", "受入", "オーダー", "HINBAN", "移動工数", "高さ", "サイズ種類", "ストア", "納入先", "入車時間"]
        extra_cols = [c for c in all_mountain_details.columns if c not in ordered_cols]
        clustered_df = pd.DataFrame(rows)
        available_ordered = [c for c in ordered_cols if c in clustered_df.columns]
        available_extra = [c for c in extra_cols if c in clustered_df.columns]
        all_mountain_details_clustered = clustered_df[available_ordered + available_extra]
        print(f"  cluster_by_store後: {len(all_mountain_details_clustered)}行")
        
        # Step4: compute_proc_details
        proc_details = compute_proc_details(all_mountain_details_clustered)
        print(f"  proc_details: {len(proc_details)}行")
        
        # Step5: assign_processes_by_arrival_time
        mountain_proc, lane_end_times = assign_processes_by_arrival_time(
            proc_details, master_df, return_lane_end_times=True
        )
        print(f"  mountain_proc: {len(mountain_proc)}行")
        
        return mountain_proc, proc_details, selection_log
    
    finally:
        # モンキーパッチを元に戻す
        pa._pick_next_main_mountain = _original_pick


def _seconds_to_hhmm(secs):
    if secs is None or pd.isna(secs):
        return "---"
    try:
        secs = int(secs)
        if secs >= DAY_SECS:
            secs -= DAY_SECS
        hh = secs // 3600
        mm = (secs % 3600) // 60
        return f"{hh:02d}:{mm:02d}"
    except Exception:
        return str(secs)


def main():
    print("=" * 70)
    print("  STEP1-3 本番フロー統合調査（本物データ版）")
    print("=" * 70)
    print()
    
    # ===== データ読み込み =====
    print("[1] データ読み込み中...")
    try:
        df_ship, df_places = load_data()
        print(f"  出荷情報: {len(df_ship)}行")
        print(f"  出荷場一覧: {len(df_places)}行")
    except Exception as e:
        print(f"[エラー] データ読み込み失敗: {e}")
        traceback.print_exc()
        return
    
    master_path = get_master_path()
    master_df = load_pickup_time_master_xlsx(master_path)
    print(f"  入車時間マスタ: {len(master_df)}行")
    
    # ===== 対象日付を決定 =====
    all_nonyuhibin = df_ship["NONYUHIBIN"].astype(str).unique()
    # 末尾2桁 = 07 のものを探す（07便が含まれる日付）
    dates_with_07 = set()
    for n in all_nonyuhibin:
        if len(n) >= 10 and n[-2:] == "07":
            date_part = n[:8]  # YYYYMMDD
            dates_with_07.add(date_part)
    
    if dates_with_07:
        target_date = sorted(dates_with_07)[-1]  # 最新の日付
        print(f"\n[2] 07便が存在する最新日付: {target_date}")
    else:
        # フォールバック: 最新日付
        all_dates = sorted({n[:8] for n in all_nonyuhibin if len(n) >= 8})
        target_date = all_dates[-1] if all_dates else None
        print(f"\n[2] 07便が見つからないため最新日付を使用: {target_date}")
    
    if not target_date:
        print("[エラー] 有効な日付が見つかりません")
        return
    
    date_prefix = target_date  # e.g. "20260630"
    
    # ===== 07便データの確認 =====
    order_07 = date_prefix + "07"  # e.g. "2026063007"
    df_07 = df_ship[df_ship["NONYUHIBIN"].astype(str) == order_07]
    print(f"\n[3] {order_07}（07便）のデータ:")
    print(f"  行数: {len(df_07)}")
    if not df_07.empty:
        print(f"  便名候補: {sorted(df_07['SYUKKASAKI'].unique())}")
        print(f"  UKEIRE: {sorted(df_07['UKEIRE'].unique())}")
        print(f"  サイズ種類: {sorted(df_07['サイズ種類'].astype(str).unique())}")
    
    # ===== 対象selectionsを生成 =====
    print(f"\n[4] {date_prefix} の全便 selections を生成中...")
    
    # 全便を対象（07便を含む同日の全オーダー）
    all_orders_today = sorted(
        df_ship[df_ship["NONYUHIBIN"].astype(str).str.startswith(date_prefix)]["NONYUHIBIN"].astype(str).unique()
    )
    print(f"  対象オーダー数: {len(all_orders_today)} ({all_orders_today[0]}〜{all_orders_today[-1]})")
    
    dm = DataManager(df_ship, df_places)
    selections_all = []
    routes = dm.get_routes()
    print(f"  便名候補: {routes}")
    
    for route in routes:
        if route == "KVC":
            # GUIではmaster_dataから"KVC-B3","KVC-B7"を取り出し、ukeireを付与する
            # GUIのsummary_modeと同様に get_receipts_for_route_order を使う
            if master_df is not None and not master_df.empty:
                kvc_display_names = sorted(
                    master_df[master_df["OData_納入先"].str.startswith("KVC-")]["OData_納入先"].unique().tolist()
                )
            else:
                kvc_display_names = []
            
            if kvc_display_names:
                # KVC-B3, KVC-B7 それぞれ処理（GUIのsummaryモードのadd_selectionと同一ロジック）
                for display_name in kvc_display_names:
                    ukeire = display_name.replace("KVC-", "").strip() if "-" in display_name else None
                    for order in all_orders_today:
                        receipts = dm.get_receipts_for_route_order("KVC", order, ukeire=ukeire)
                        for rc in receipts:
                            sel = {"便名": "KVC", "受入": rc, "オーダー": order, "ukeire": ukeire}
                            if sel not in selections_all:
                                selections_all.append(sel)
            else:
                # master_dataがない場合は通常通り（fallback）
                for order in all_orders_today:
                    receipts = dm.get_receipts_for_route_order(route, order)
                    for rc in receipts:
                        sel = {"便名": route, "受入": rc, "オーダー": order}
                        if sel not in selections_all:
                            selections_all.append(sel)
        else:
            for order in all_orders_today:
                receipts = dm.get_receipts_for_route_order(route, order)
                for rc in receipts:
                    sel = {"便名": route, "受入": rc, "オーダー": order}
                    if sel not in selections_all:
                        selections_all.append(sel)
    
    print(f"  生成されたselections: {len(selections_all)}件")
    
    # 07便のselections確認
    sels_07 = [s for s in selections_all if s["オーダー"] == order_07]
    print(f"\n  07便({order_07})のselections:")
    for s in sels_07:
        print(f"    {s}")
    
    if not selections_all:
        print("[エラー] selectionsが空です。出荷場一覧.csvのマッピングを確認してください。")
        return
    
    # ===== RAW版（現状）実行 =====
    print("\n" + "=" * 50)
    print("  [RAW版] 現状（raw締切でソート）を実行")
    print("=" * 50)
    
    mountain_proc_raw, proc_details_raw, log_raw = _run_full_pipeline(
        df_ship, df_places, master_df, selections_all, use_eval_deadline=False
    )
    
    # ===== EVAL版（改修案）実行 =====
    print("\n" + "=" * 50)
    print("  [EVAL版] 改修案（eval締切補正でソート）を実行")
    print("=" * 50)
    
    mountain_proc_eval, proc_details_eval, log_eval = _run_full_pipeline(
        df_ship, df_places, master_df, selections_all, use_eval_deadline=True
    )
    
    # ===== 結果比較 =====
    print("\n" + "=" * 70)
    print("  結果比較")
    print("=" * 70)
    
    if mountain_proc_raw is None or mountain_proc_eval is None:
        print("[エラー] パイプライン実行に失敗しました。")
        return
    
    # 山通番ベースで工程割当を比較
    raw_proc_map = {}
    eval_proc_map = {}
    
    if "山通番" in mountain_proc_raw.columns and "工程" in mountain_proc_raw.columns:
        for _, row in mountain_proc_raw.iterrows():
            raw_proc_map[int(row["山通番"])] = str(row.get("工程", ""))
    
    if "山通番" in mountain_proc_eval.columns and "工程" in mountain_proc_eval.columns:
        for _, row in mountain_proc_eval.iterrows():
            eval_proc_map[int(row["山通番"])] = str(row.get("工程", ""))
    
    print("\n全山の工程割当:")
    print(f"{'山通番':>6} {'便名':>8} {'オーダー末尾':>6} {'raw工程':>12} {'eval工程':>12} {'変化':>5}")
    print("-" * 60)
    
    # proc_detailsから山通番↔便名の対応を取得
    yama_info = {}
    if proc_details_raw is not None and not proc_details_raw.empty:
        for _, row in proc_details_raw.iterrows():
            yama_no = int(row.get("山通番", -1))
            if yama_no >= 0:
                yama_info[yama_no] = {
                    "便名": str(row.get("便名", "")),
                    "オーダー": str(row.get("オーダー", "")),
                    "締め切り_秒": row.get("締め切り_秒"),
                    "入車時間_秒": row.get("入車時間_秒"),
                }
    
    all_yama_nos = sorted(set(list(raw_proc_map.keys()) + list(eval_proc_map.keys())))
    changed_rows = []
    
    for yama_no in all_yama_nos:
        raw_proc = raw_proc_map.get(yama_no, "---")
        eval_proc = eval_proc_map.get(yama_no, "---")
        changed = "★変化" if raw_proc != eval_proc else ""
        info = yama_info.get(yama_no, {})
        order_str = info.get("オーダー", "")[-2:] if info.get("オーダー") else "??"
        route_str = info.get("便名", "??")[:6]
        ddl_secs = info.get("締め切り_秒")
        ddl_str = _seconds_to_hhmm(ddl_secs)
        print(f"  {yama_no:4d}  {route_str:>8} {order_str:>6}便  {raw_proc:>12} {eval_proc:>12} {changed}")
        if changed:
            changed_rows.append({
                "山通番": yama_no,
                "便名": route_str,
                "オーダー末尾2桁": order_str,
                "締め切り_hhmm": ddl_str,
                "raw工程": raw_proc,
                "eval工程": eval_proc,
            })
    
    print(f"\n工程変化した山: {len(changed_rows)}件")
    for r in changed_rows:
        print(f"  山{r['山通番']}: {r['便名']}_{r['オーダー末尾2桁']}便 締切={r['締め切り_hhmm']} "
              f"{r['raw工程']} → {r['eval工程']}")
    
    # 07便の結果を強調表示
    print(f"\n★ {order_07}（07便）の結果:")
    order_07_suffix = order_07[-2:]  # "07"
    for yama_no, info in yama_info.items():
        if info.get("オーダー", "")[-2:] == order_07_suffix:
            raw_p = raw_proc_map.get(yama_no, "---")
            eval_p = eval_proc_map.get(yama_no, "---")
            ddl = _seconds_to_hhmm(info.get("締め切り_秒"))
            print(f"  山{yama_no}: raw={raw_p}, eval={eval_p}, 締切={ddl}")
    
    # ===== 選択順ログ =====
    print("\n" + "=" * 50)
    print("  選択順ログ（RAW版）")
    print("=" * 50)
    print(f"{'選択順':>5} {'山通番':>6} {'前倒し':>6} {'raw締切':>8}")
    for entry in log_raw[:30]:  # 最初の30件
        ddl = _seconds_to_hhmm(entry.get("締め切り_秒_raw"))
        print(f"  {entry['選択順']:3d}   山{entry['山通番']:3d}  {str(entry['前倒し']):>5}  {ddl}")
    if len(log_raw) > 30:
        print(f"  ... 残り{len(log_raw)-30}件省略")
    
    # ===== CSV出力 =====
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 比較表
    compare_rows = []
    for yama_no in all_yama_nos:
        info = yama_info.get(yama_no, {})
        compare_rows.append({
            "山通番": yama_no,
            "便名": info.get("便名", ""),
            "オーダー": info.get("オーダー", ""),
            "オーダー末尾2桁": info.get("オーダー", "")[-2:] if info.get("オーダー") else "",
            "締め切り_秒_raw": info.get("締め切り_秒"),
            "締め切り_hhmm": _seconds_to_hhmm(info.get("締め切り_秒")),
            "raw工程": raw_proc_map.get(yama_no, "---"),
            "eval工程": eval_proc_map.get(yama_no, "---"),
            "工程変化": raw_proc_map.get(yama_no) != eval_proc_map.get(yama_no),
        })
    
    compare_df = pd.DataFrame(compare_rows)
    compare_path = PROJ_ROOT / f"analysis_pipeline_compare_{ts}.csv"
    compare_df.to_csv(compare_path, index=False, encoding="utf-8-sig")
    print(f"\n[出力] 比較表CSV: {compare_path}")
    
    # 選択順ログ
    log_raw_df = pd.DataFrame(log_raw)
    log_eval_df = pd.DataFrame(log_eval)
    if not log_raw_df.empty:
        log_path = PROJ_ROOT / f"analysis_selection_log_{ts}.csv"
        log_raw_merged = log_raw_df.copy()
        log_raw_merged["版"] = "raw"
        log_eval_merged = log_eval_df.copy() if not log_eval_df.empty else pd.DataFrame()
        if not log_eval_merged.empty:
            log_eval_merged["版"] = "eval"
        combined = pd.concat([log_raw_merged, log_eval_merged], ignore_index=True)
        combined.to_csv(log_path, index=False, encoding="utf-8-sig")
        print(f"[出力] 選択順ログCSV: {log_path}")
    
    # ===== 07便リリーフ確認サマリ =====
    print("\n" + "=" * 70)
    print("  ★★★ 07便リリーフ確認サマリ ★★★")
    print("=" * 70)
    
    found_07 = False
    for yama_no, info in yama_info.items():
        if info.get("オーダー", "")[-2:] == "07":
            raw_p = raw_proc_map.get(yama_no, "---")
            eval_p = eval_proc_map.get(yama_no, "---")
            ddl = _seconds_to_hhmm(info.get("締め切り_秒"))
            found_07 = True
            if PROC_RELIEF in raw_p:
                print(f"  ✅ 【再現OK】山{yama_no}（07便）: raw={raw_p} ← バグ再現")
            else:
                print(f"  ❌ 【再現NG】山{yama_no}（07便）: raw={raw_p} ← リリーフに落ちていない")
            if PROC_MAIN in eval_p:
                print(f"  ✅ 【修正OK】山{yama_no}（07便）: eval={eval_p} ← 案Aでメインに昇格")
            else:
                print(f"  ❌ 【修正NG】山{yama_no}（07便）: eval={eval_p} ← 案Aでもメインにならない")
    
    if not found_07:
        print(f"  ❌ 07便（オーダー末尾07）が山通番に存在しません。")
        print(f"     selectionsにオーダー={order_07}が含まれているか確認してください。")
        print(f"     07便sels: {sels_07}")
    
    print("\n完了")


if __name__ == "__main__":
    main()
