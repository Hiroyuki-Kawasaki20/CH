# -*- coding: utf-8 -*-
"""
PR #58 検証スクリプト: スケジューラ出力における日野別便入れ込み測定

測定定義:
  日野便A の最初の山の実開始〜最後の山の実終了の区間内に、
  別便（便番号セットが交わらない）の日野便B の山が開始したら 1件。

使用法:
  python t120_scheduler_interleave_check.py [--date YYYYMMDD] [--session DATETIME]

出力:
  - 標準出力: サマリーテーブル
  - t120_interleave_result.txt: 詳細レポート
"""

import sys, json, argparse, io
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Windows UTF-8 出力
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np

from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    compute_proc_details,
    _time_to_seconds,
    _is_hino_2lane_target,
)
from src.models.constants import PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW

SPO_HISTORY_XLSX = Path(__file__).parent / "SPOアップロード用_履歴.xlsx"
MASTER_XLSX = Path(__file__).parent / "入車時間マスタ.xlsx"
REPORT_PATH = Path(__file__).parent / "t120_interleave_result.txt"


# ─── データ再構成ヘルパー ─────────────────────────────────────────────────────

def _parse_vendor_from_item(item: dict) -> str:
    """groupdata JSON の納入先キー（エンコード版とストレート版）を解決"""
    for key in ("OData__x7d0d__x5165__x5148_", "OData_納入先", "納入先"):
        v = str(item.get(key, "")).strip()
        if v:
            return v
    return ""


def _extract_bin_last2(nonyuhibin: str) -> str:
    """NONYUHIBIN 文字列から末尾2桁を返す"""
    s = str(nonyuhibin).strip()
    return s[-2:] if len(s) >= 2 else s


def reconstruct_proc_details(session_rows: list) -> pd.DataFrame:
    """
    SPO 履歴の 1セッション分 (リスト of Series/dict) から proc_details を再構築。

    各行 = 1山。groupdata JSON から order 行を展開し、
    山通番・移動工数・納入先・NONYUHIBIN・高さ を付与する。
    """
    rows = []
    for row in session_rows:
        # タイトル「山1」→ 1
        title = str(row.get("タイトル", "")).strip()
        try:
            yama_no = int(title.replace("山", "").strip())
        except ValueError:
            continue

        gd = row.get("groupdata", "")
        if not isinstance(gd, str):
            continue
        try:
            items = json.loads(gd)
        except json.JSONDecodeError:
            continue

        max_ido = float(row.get("Max移動工数", 0) or 0)

        for item in items:
            nonyuhibin = str(item.get("NONYUHIBIN", "")).strip()
            vendor = _parse_vendor_from_item(item)
            if not nonyuhibin or not vendor:
                continue
            rows.append({
                "山通番": yama_no,
                "移動工数": max_ido,
                "納入先": vendor,
                "NONYUHIBIN": nonyuhibin,
                "高さ": 0,  # 高さは履歴から復元不可のため0（あふれ判定は行わない）
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ─── 入れ込みカウント ──────────────────────────────────────────────────────────

def count_interleave_from_result(
    result_df: pd.DataFrame,
    proc_details: pd.DataFrame,
) -> tuple:
    """
    スケジューラ出力から日野別便入れ込み件数を計測。

    戻り値: (interleave_count, interleave_details_list)
      details_list = [{"便A": "02", "便B": "03", "山通番B": 5, "開始時間B": "09:10", ...}, ...]
    """
    # メイン工程山のみ対象
    main_df = result_df[result_df["山工程"] == PROC_MAIN].copy()
    if main_df.empty:
        return 0, []

    # 山通番 → 日野便番号セット のマップを proc_details から構築
    yama_bins: dict = {}
    for yama_no, sub in proc_details.groupby("山通番"):
        bin_set = set()
        for _, r in sub.iterrows():
            vendor = str(r.get("納入先", "")).strip()
            nony = str(r.get("NONYUHIBIN", "")).strip()
            if _is_hino_2lane_target(vendor) and len(nony) >= 2:
                bin_set.add(nony[-2:])
        if bin_set:
            yama_bins[int(yama_no)] = bin_set

    # メイン山の実開始・実終了を秒に変換
    def to_sec(s):
        t = _time_to_seconds(str(s))
        if t is None:
            return None
        # 24:xx/25:xx 対応: _time_to_seconds は整数秒を返すが24時超えを考慮
        # 時刻文字列が HH:MM 形式で H >= 24 の場合も _time_to_seconds が対応済み
        return t

    yama_start = {}
    yama_end = {}
    for _, r in main_df.iterrows():
        yn = int(r["山通番"])
        s = to_sec(r.get("実開始時間", ""))
        e = to_sec(r.get("実終了時間", ""))
        if s is not None:
            yama_start[yn] = s
        if e is not None:
            yama_end[yn] = e

    # 日野便ごとに時間窓を集計: [min(start), max(end)]
    bin_windows: dict = defaultdict(lambda: {"min_start": None, "max_end": None, "yamas": []})
    for yn, bins in yama_bins.items():
        if yn not in yama_start:
            continue
        s = yama_start[yn]
        e = yama_end.get(yn, s)
        for b in bins:
            w = bin_windows[b]
            w["yamas"].append(yn)
            if w["min_start"] is None or s < w["min_start"]:
                w["min_start"] = s
            if w["max_end"] is None or e > w["max_end"]:
                w["max_end"] = e

    # 入れ込み検出
    bins_list = sorted(bin_windows.keys())
    interleave_count = 0
    details = []

    for bin_a in bins_list:
        w_a = bin_windows[bin_a]
        if w_a["min_start"] is None:
            continue
        win_start = w_a["min_start"]
        win_end = w_a["max_end"] or win_start

        for bin_b in bins_list:
            if bin_b == bin_a:
                continue
            w_b = bin_windows[bin_b]
            # B の各山が A の窓内に開始するか
            for yn_b in w_b["yamas"]:
                if yn_b not in yama_start:
                    continue
                sb = yama_start[yn_b]
                if win_start <= sb <= win_end:
                    interleave_count += 1
                    details.append({
                        "便A": bin_a,
                        "便B": bin_b,
                        "山通番B": yn_b,
                        "開始時間B": _fmt_sec(sb),
                        "窓A開始": _fmt_sec(win_start),
                        "窓A終了": _fmt_sec(win_end),
                    })

    return interleave_count, details


def _fmt_sec(s: int) -> str:
    """秒 → HH:MM 文字列（24時超え対応）"""
    if s is None:
        return "?"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"


# ─── セッション選定 ────────────────────────────────────────────────────────────

def get_sessions_by_date(history_df: pd.DataFrame, target_date: str) -> dict:
    """
    指定日付のデータを含むセッション（出力日時 → リスト of row dict）を返す。
    target_date: "YYYYMMDD"
    """
    sessions = defaultdict(list)
    for _, row in history_df.iterrows():
        gd = row.get("groupdata", "")
        if not isinstance(gd, str):
            continue
        try:
            items = json.loads(gd)
            nony_dates = set()
            for item in items:
                nony = str(item.get("NONYUHIBIN", ""))
                if len(nony) >= 8:
                    nony_dates.add(nony[:8])
            if target_date in nony_dates:
                sess_key = str(row.get("出力日時", "unknown"))
                sessions[sess_key].append(row.to_dict())
        except:
            continue
    return sessions


def get_all_multi_bin_sessions(history_df: pd.DataFrame) -> list:
    """
    複数日野便が混在する全セッションの一覧を返す。
    戻り値: [(session_key, target_date, bin_set, rows_list), ...]
    """
    # セッション別に分類
    session_map = defaultdict(list)
    for _, row in history_df.iterrows():
        sess_key = str(row.get("出力日時", "unknown"))
        session_map[sess_key].append(row.to_dict())

    results = []
    for sess_key, rows in session_map.items():
        # このセッションに含まれる日野便を集計
        date_bins = defaultdict(set)
        for row in rows:
            gd = row.get("groupdata", "")
            if not isinstance(gd, str):
                continue
            try:
                items = json.loads(gd)
                for item in items:
                    nony = str(item.get("NONYUHIBIN", ""))
                    vendor = _parse_vendor_from_item(item)
                    if len(nony) >= 10 and _is_hino_2lane_target(vendor):
                        date_bins[nony[:8]].add(nony[-2:])
            except:
                continue

        for date, bins in date_bins.items():
            if len(bins) >= 2:
                results.append((sess_key, date, bins, rows))

    return results


# ─── メイン処理 ───────────────────────────────────────────────────────────────

def run_measurement(
    session_rows: list,
    master_df: pd.DataFrame,
    session_key: str = "",
    date: str = "",
    bins: set = None,
) -> dict:
    """1セッションの測定を実行して結果 dict を返す"""
    proc_details = reconstruct_proc_details(session_rows)
    if proc_details.empty:
        return {"error": "proc_details が空"}

    try:
        result_df = assign_processes_by_arrival_time(
            compute_proc_details(proc_details), master_df
        )
    except Exception as e:
        return {"error": str(e)}

    n_main = int((result_df["山工程"] == PROC_MAIN).sum())
    n_relief = int((result_df["山工程"] == PROC_RELIEF).sum())
    n_overflow = int((result_df["山工程"] == PROC_OVERFLOW).sum()) if PROC_OVERFLOW in result_df["山工程"].values else 0
    n_deadline = 0  # 締切違反カウント（実装省略: 高さ=0のため精度低）

    interleave_count, details = count_interleave_from_result(result_df, proc_details)

    return {
        "session": session_key,
        "date": date,
        "hino_bins": sorted(bins) if bins else [],
        "n_mountains": len(result_df),
        "n_main": n_main,
        "n_relief": n_relief,
        "n_overflow": n_overflow,
        "interleave_count": interleave_count,
        "interleave_details": details,
    }


def main():
    parser = argparse.ArgumentParser(description="スケジューラ出力の日野別便入れ込み測定")
    parser.add_argument("--date", help="対象日付 YYYYMMDD（未指定時は全日付）")
    parser.add_argument("--session", help="対象セッション（出力日時）")
    parser.add_argument("--all", action="store_true", help="複数便が混在する全セッションを対象")
    args = parser.parse_args()

    print("=" * 80)
    print("【PR #58 実データ Before/After 検証】スケジューラ出力の入れ込み測定")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"リポジトリ: {Path(__file__).parent.name}")
    print("=" * 80)

    master_df = pd.read_excel(MASTER_XLSX)
    print(f"マスタ読込: {len(master_df)} 行\n")

    history_df = pd.read_excel(SPO_HISTORY_XLSX)
    print(f"SPO履歴読込: {len(history_df)} 行\n")

    sessions = get_all_multi_bin_sessions(history_df)
    print(f"複数日野便セッション数: {len(sessions)}\n")

    report_lines = []
    tried_dates = set()
    interleave_found_count = 0

    for sess_key, date, bins, rows in sorted(sessions, key=lambda x: x[0]):
        tried_dates.add(date)
        result = run_measurement(rows, master_df, sess_key, date, bins)
        n_ic = result.get("interleave_count", -1)

        line = (
            f"日付={date} | セッション={sess_key} | "
            f"日野便={result.get('hino_bins')} | 山数={result.get('n_mountains')} | "
            f"メイン={result.get('n_main')} | リリーフ={result.get('n_relief')} | "
            f"あふれ={result.get('n_overflow')} | "
            f"入れ込み={n_ic if n_ic >= 0 else 'ERROR'}"
        )
        if "error" in result:
            line += f" [ERROR: {result['error']}]"
        print(line)
        report_lines.append(line)

        if n_ic > 0:
            interleave_found_count += 1
            for d in result["interleave_details"]:
                detail_line = (
                    f"  !! 入れ込み: 便{d['便A']}の窓[{d['窓A開始']}-{d['窓A終了']}]に "
                    f"便{d['便B']} 山{d['山通番B']}が{d['開始時間B']}に開始"
                )
                print(detail_line)
                report_lines.append(detail_line)

    print("\n" + "=" * 80)
    print(f"試行日付一覧: {sorted(tried_dates)}")
    print(f"入れ込みあり件数: {interleave_found_count} / {len(sessions)} セッション")
    print("=" * 80)

    # レポート書き出し
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"PR #58 入れ込み測定レポート\n")
        f.write(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"リポジトリ: {Path(__file__).parent.name}\n\n")
        f.write("\n".join(report_lines))
        f.write(f"\n\n試行日付一覧: {sorted(tried_dates)}\n")
        f.write(f"入れ込みあり: {interleave_found_count} / {len(sessions)} セッション\n")

    print(f"\nレポート: {REPORT_PATH}")


if __name__ == "__main__":
    main()
