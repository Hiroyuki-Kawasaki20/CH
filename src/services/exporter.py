# -*- coding: utf-8 -*-
"""CHかんばんセット — Excel出力サービス"""

import os
import json
import html
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Set

import pandas as pd
import numpy as np

from ..models.constants import (
    BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL,
    PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW, PROC_MAIN_LABEL, PROC_RELIEF_LABEL, PROC_OVERFLOW_LABEL,
    is_virtual_yama,
)
from ..utils.excel_utils import (
    _ensure_columns, _protect_excel_injection, _add_table_exact,
    index_to_letters,
)
from ..utils.normalizer import _normalize_hhmm, _ZEN2HAN_DIGIT_COLON
from .spo_export import export_to_spo


def export_setboard_html(
        proc_details: pd.DataFrame,
        mountain_proc_map: dict,
        mountain_start_times: dict,
        out_dir: str,
        base_name: str = "セットボード",
) -> str:
        """現在の工程割当をセットボードHTMLとして出力する。"""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base_name}.html")

        if proc_details is None or proc_details.empty:
                html_doc = """<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\"><title>セットボード</title></head><body><h1>セットボード</h1><p>データがありません。</p></body></html>"""
                with open(out_path, "w", encoding="utf-8") as f:
                        f.write(html_doc)
                return out_path

        df = proc_details.copy()
        df["山通番"] = pd.to_numeric(df.get("山通番", 0), errors="coerce").fillna(0).astype(int)
        df["移動工数"] = pd.to_numeric(df.get("移動工数", 0), errors="coerce").fillna(0)
        df["高さ"] = pd.to_numeric(df.get("高さ", 0), errors="coerce").fillna(0)

        rows_main = []
        rows_relief = []
        details_html_parts = []

        for yama in sorted(df["山通番"].unique()):
                sub = df[df["山通番"] == yama].copy()
                is_virtual = is_virtual_yama(yama)
                pal = int(sub.shape[0])
                hsum = int(sub["高さ"].sum()) if "高さ" in sub.columns else 0
                max_cost = float(sub["移動工数"].max()) if sub["移動工数"].notna().any() else 0.0
                # HTMLは仮想山の引取工数を固定10分(600秒)で表示する。
                pick_cost = 600 if is_virtual else int(round(
                    max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL)
                ))
                # HTML要件: 仮想山のパレット数は"-"表示にする。
                pal_display = "-" if is_virtual else str(pal)

                dest_col = "納入先" if "納入先" in sub.columns else "OData_納入先"
                dests = sorted([str(x).strip() for x in sub.get(dest_col, pd.Series(dtype=str)).tolist() if str(x).strip()])
                dest_text = "/".join(sorted(set(dests))) if dests else "-"
                start_time = str(mountain_start_times.get(int(yama), "")).strip() or "-"

                card = f"""
                    <tr>
                        <td>{int(yama)}</td>
                        <td>{pal_display}</td>
                        <td>{pick_cost}</td>
                        <td>{hsum}</td>
                        <td>{html.escape(dest_text)}</td>
                        <td>{html.escape(start_time)}</td>
                    </tr>
                """
                proc = str(mountain_proc_map.get(int(yama), PROC_MAIN))
                if proc == PROC_MAIN:
                        rows_main.append(card)
                else:
                        rows_relief.append(card)

                detail_rows = []
                sub = sub.sort_values(by=["工程内No", "移動工数"], ascending=[True, False], na_position="last")
                for _, r in sub.iterrows():
                        detail_rows.append(
                                "<tr>"
                                f"<td>{int(r.get('山通番', 0))}</td>"
                                f"<td>{html.escape(str(r.get('HINBAN', '')))}</td>"
                                f"<td>{int(r.get('PLANKANBANSU', 1)) if pd.notna(r.get('PLANKANBANSU', 1)) else ''}</td>"
                                f"<td>{html.escape(str(r.get('UKEIRE', '')))}</td>"
                                f"<td>{html.escape(str(r.get('ストア', r.get('SYUKKASAKI', ''))))}</td>"
                                f"<td>{html.escape(str(r.get('納入先', r.get('OData_納入先', ''))))}</td>"
                                f"<td>{int(r.get('工程内No', 0)) if pd.notna(r.get('工程内No', 0)) else ''}</td>"
                                f"<td>{int(round(float(r.get('移動工数', 0)))) if pd.notna(r.get('移動工数', 0)) else ''}</td>"
                                f"<td>{int(round(float(r.get('高さ', 0)))) if pd.notna(r.get('高さ', 0)) else ''}</td>"
                                "</tr>"
                        )
                details_html_parts.append(
                        f"""
                        <section class=\"detail-card\">
                            <h3>山{int(yama)} / {"メイン" if proc == PROC_MAIN else "リリーフ"} / 開始 {html.escape(start_time)}</h3>
                            <table>
                                <thead>
                                    <tr><th>山通番</th><th>品番</th><th>数量</th><th>受入</th><th>ストア</th><th>納入先</th><th>工程内No</th><th>移動工数</th><th>高さ</th></tr>
                                </thead>
                                <tbody>{''.join(detail_rows)}</tbody>
                            </table>
                        </section>
                        """
                )

        html_doc = f"""
<!doctype html>
<html lang=\"ja\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>CHかんばんセットボード</title>
    <style>
        body {{ font-family: "Meiryo UI", "Yu Gothic UI", sans-serif; margin: 0; background: #f3f4f6; color: #1f2937; }}
        header {{ background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; padding: 14px 18px; }}
        h1 {{ margin: 0; font-size: 20px; }}
        .meta {{ margin-top: 6px; font-size: 12px; opacity: .9; }}
        main {{ padding: 14px; display: grid; gap: 14px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        .panel {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,.08); overflow: hidden; }}
        .panel h2 {{ margin: 0; padding: 10px 12px; font-size: 16px; }}
        .main h2 {{ background: #dff0ff; color: #1e3a5f; }}
        .relief h2 {{ background: #fbe1ef; color: #831843; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
        th, td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: center; }}
        th {{ background: #f9fafb; font-weight: 700; }}
        td:nth-child(5) {{ text-align: left; }}
        .details {{ display: grid; gap: 10px; }}
        .detail-card {{ background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,.06); overflow: hidden; }}
        .detail-card h3 {{ margin: 0; padding: 10px 12px; font-size: 14px; background: #eef2ff; }}
        .detail-card table td:nth-child(2),
        .detail-card table td:nth-child(5),
        .detail-card table td:nth-child(6) {{ text-align: left; }}
        @media (max-width: 1024px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <header>
        <h1>CHかんばんセットボード（HTML出力）</h1>
        <div class=\"meta\">出力日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </header>
    <main>
        <section class=\"grid\">
            <article class=\"panel main\">
                <h2>メイン工程</h2>
                <table>
                    <thead><tr><th>山通番</th><th>パレット数</th><th>引取工数</th><th>高さ合計</th><th>納入先</th><th>開始時間</th></tr></thead>
                    <tbody>{''.join(rows_main)}</tbody>
                </table>
            </article>
            <article class=\"panel relief\">
                <h2>リリーフ工程</h2>
                <table>
                    <thead><tr><th>山通番</th><th>パレット数</th><th>引取工数</th><th>高さ合計</th><th>納入先</th><th>開始時間</th></tr></thead>
                    <tbody>{''.join(rows_relief)}</tbody>
                </table>
            </article>
        </section>
        <section class=\"details\">
            {''.join(details_html_parts)}
        </section>
    </main>
</body>
</html>
"""

        with open(out_path, "w", encoding="utf-8") as f:
                f.write(html_doc)
        return out_path


def add_group_label_by_koutei_yama(
    details_df: pd.DataFrame,
    label_col: str = "GroupLabel",
) -> pd.DataFrame:
    """工程ごとに山通番のユニーク昇順でA/B/C...を割り当てる"""
    df = details_df.copy()
    if df is None or df.empty:
        df[label_col] = ""
        return df
    if "工程" not in df.columns or "山通番" not in df.columns:
        df[label_col] = ""
        return df
    df["山通番"] = pd.to_numeric(df["山通番"], errors="coerce")
    df["_工程_key"] = df["工程"].astype(str).str.strip()
    for k, sub in df.groupby("_工程_key", sort=False):
        uniques = sorted(sub["山通番"].dropna().unique().tolist())
        idxmap = {y: index_to_letters(i + 1) for i, y in enumerate(uniques)}
        df.loc[df["_工程_key"] == k, label_col] = df.loc[df["_工程_key"] == k, "山通番"].map(idxmap)
    df.drop(columns=["_工程_key"], inplace=True)
    return df


def build_groupeddata_json_for_mountain(sub_rows: pd.DataFrame) -> str:
    """山の行からGroupedData JSON配列文字列を作る"""
    if sub_rows is None or sub_rows.empty:
        return "[]"
    df = sub_rows.copy()

    # xlsx出力は束ね代表行のみをgroupdata化する（_merged_rowsは展開しない）。

    if "OData__x30b9__x30c8__x30a2_" not in df.columns:
        df["OData__x30b9__x30c8__x30a2_"] = df.get("ストア", df.get("SYUKKASAKI", "")).astype(str)
    if "OData__x7d0d__x5165__x5148_" not in df.columns:
        df["OData__x7d0d__x5165__x5148_"] = df.get("納入先", "").astype(str)
    if "引取済" not in df.columns:
        df["引取済"] = ""

    # 移動工数を数値化（ソート前に実施）。列が存在しない場合は NaN で補完する。
    if "移動工数" in df.columns:
        df["移動工数"] = pd.to_numeric(df["移動工数"], errors="coerce")
    else:
        df["移動工数"] = float("nan")

    # 番号採番ルール: 移動工数の昇順を最優先キーとする。
    # 同値の場合は SEBANGO 昇順（存在すれば）、なければ 工程内No 昇順 で安定化。
    sort_by = ["移動工数"]
    sort_asc = [True]
    if "SEBANGO" in df.columns:
        sort_by.append("SEBANGO")
        sort_asc.append(True)
    elif "工程内No" in df.columns:
        sort_by.append("工程内No")
        sort_asc.append(True)

    df = df.sort_values(by=sort_by, ascending=sort_asc, na_position="last")
    df = df.reset_index(drop=True)
    df["番号"] = np.arange(1, len(df) + 1)
    cols = ["OData__x30b9__x30c8__x30a2_", "NONYUHIBIN", "UKEIRE",
            "OData__x7d0d__x5165__x5148_", "SEBANGO", "番号", "引取済"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    recs = df[cols].astype(object).where(pd.notna(df[cols]), "").to_dict(orient="records")
    return json.dumps(recs, ensure_ascii=False)


def build_spo_export_df(
    proc_details: pd.DataFrame,
    mountain_proc_map: dict,
    mountain_start_times: dict = None,
    overflow_yamas: Optional[Set[int]] = None,
    inspection_delay_map: Optional[Dict[int, bool]] = None,
) -> pd.DataFrame:
    """SPOアップロード用の1山=1行DataFrame"""
    if mountain_start_times is None:
        mountain_start_times = {}
    if overflow_yamas is None:
        overflow_yamas = set()
    if inspection_delay_map is None:
        inspection_delay_map = {}
    cols_out = [
        "タイトル", "工程", "groupdata", "GroupedData",
        "Max移動工数", "グループ番号", "パレット数", "引取工数",
        "引取開始時間", "id", "済", "実施者", "順番",
        "照合日", "照合済", "割込み作業名", "更新日時", "登録日時"
    ]
    if proc_details is None or proc_details.empty:
        return pd.DataFrame(columns=cols_out)
    df = proc_details.copy()
    df["移動工数"] = pd.to_numeric(df.get("移動工数", np.nan), errors="coerce")
    rows = []
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # 次山の開始時刻とリンクするよう、次山側に付く照合180秒を現在山へ反映する。
    delay_after_map: Dict[int, int] = {}
    all_yamas = sorted([int(y) for y in df["山通番"].unique()])
    for proc_label in (PROC_MAIN, PROC_RELIEF, PROC_OVERFLOW):
        proc_yamas = [y for y in all_yamas if str(mountain_proc_map.get(int(y), PROC_MAIN)) == proc_label]

        def _start_key(y: int):
            st = str(mountain_start_times.get(int(y), "")).strip()
            norm = _normalize_hhmm(st)
            if not norm:
                return (1, int(y))
            try:
                hh, mm = norm.split(":", 1)
                return (0, int(hh) * 60 + int(mm), int(y))
            except Exception:
                return (1, int(y))

        proc_yamas = sorted(proc_yamas, key=_start_key)
        for idx, y in enumerate(proc_yamas):
            delay_after = 0
            if idx + 1 < len(proc_yamas):
                next_y = int(proc_yamas[idx + 1])
                if bool(inspection_delay_map.get(next_y, False)):
                    delay_after = 180
            delay_after_map[int(y)] = delay_after

    proc_mountain_counter = {}
    main_export_label = "1工程"

    for yama, sub in df.groupby("山通番", sort=True):
        is_virtual = is_virtual_yama(yama)
        # SPO要件: 仮想山はパレット数0で出力する。
        pal = 0 if is_virtual else int(sub.shape[0])
        max_cost = float(sub["移動工数"].max()) if sub["移動工数"].notna().any() else 0.0
        # SPO要件: 仮想山の引取工数は固定10分(600秒)にする。
        pick_cost = 600 if is_virtual else float(np.round(
            max_cost + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0
        ))
        gd_json = build_groupeddata_json_for_mountain(sub)
        if int(yama) in overflow_yamas:
            y_proc_label = "あふれ"
        else:
            y_proc = str(mountain_proc_map.get(int(yama), PROC_MAIN))
            y_proc_label = main_export_label if y_proc == PROC_MAIN else PROC_RELIEF_LABEL

        if y_proc_label not in proc_mountain_counter:
            proc_mountain_counter[y_proc_label] = 0
        proc_mountain_counter[y_proc_label] += 1
        proc_mountain_num = proc_mountain_counter[y_proc_label]

        start_time = str(mountain_start_times.get(int(yama), "")).strip()
        rows.append({
            "タイトル": f"山{proc_mountain_num}",
            "工程": y_proc_label,
            "groupdata": gd_json,
            "GroupedData": gd_json,
            "Max移動工数": max_cost,
            "グループ番号": int(yama),
            "パレット数": pal,
            "引取工数": int(pick_cost if is_virtual else (pick_cost + delay_after_map.get(int(yama), 0))),
            "引取開始時間": start_time,
            "id": int(yama),
            "済": "", "実施者": "", "順番": 0,
            "照合日": "", "照合済": "", "割込み作業名": "",
            "更新日時": now_iso, "登録日時": now_iso,
        })
    out = pd.DataFrame(rows, columns=cols_out)
    for c in ("Max移動工数", "グループ番号", "パレット数", "引取工数", "id", "順番"):
        if c in out.columns:
            if c == "Max移動工数":
                out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0).astype(float)
            else:
                out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    text_cols = ["タイトル", "工程", "groupdata", "GroupedData", "引取開始時間",
                 "済", "実施者", "照合日", "照合済", "割込み作業名", "更新日時", "登録日時"]
    out = _protect_excel_injection(out, text_cols)
    return out


def export_spo_xlsx(spo_df: pd.DataFrame, out_dir: str, base_name: str = "SPOアップロード用") -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(out_dir, f"{base_name}.xlsx")
    export_to_spo(spo_df, output_path=path)
    return path


def export_kanban_xlsx(
    summary_df: pd.DataFrame,
    details_df: pd.DataFrame,
    out_dir: str,
    base_name: str = "工程別かんばん",
) -> dict:
    """工程別かんばん明細をXLSXで出力"""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    det_path = os.path.join(out_dir, f"{base_name}_山明細.xlsx")

    details_cols = ["山通番", "納入先", "工程", "工程内No", "ストア", "NONYUHIBIN", "UKEIRE",
                    "移動工数", "高さ", "サイズ種類", "GroupLabel"]
    text_cols_details = ["納入先", "ストア", "NONYUHIBIN", "UKEIRE", "サイズ種類", "GroupLabel"]

    details_df = add_group_label_by_koutei_yama(details_df, label_col="GroupLabel")
    d_out = _ensure_columns(details_df, details_cols)
    if "山通番" in d_out.columns:
        d_out["山通番"] = pd.to_numeric(d_out["山通番"], errors="coerce").fillna(0).astype(int)
    if "移動工数" in d_out.columns:
        d_out["移動工数"] = pd.to_numeric(d_out["移動工数"], errors="coerce").fillna(0)
    if "高さ" in d_out.columns:
        d_out["高さ"] = pd.to_numeric(d_out["高さ"], errors="coerce").fillna(0)
    d_out = _protect_excel_injection(d_out, text_cols_details)
    d_out.to_excel(det_path, index=False, engine="openpyxl")
    _add_table_exact(det_path, "KanbanTable")
    return {"details": det_path}


def append_to_spo_history(spo_df: pd.DataFrame, out_dir: str, history_name: str = "SPOアップロード用_履歴") -> str:
    """SPOアップロード用のデータを履歴ファイルに追記"""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    history_path = os.path.join(out_dir, f"{history_name}.xlsx")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    spo_with_time = spo_df.copy()
    spo_with_time.insert(0, "出力日時", timestamp)
    if os.path.exists(history_path):
        try:
            existing_df = pd.read_excel(history_path, engine="openpyxl")
            combined_df = pd.concat([existing_df, spo_with_time], ignore_index=True)
        except Exception:
            combined_df = spo_with_time
    else:
        combined_df = spo_with_time
    combined_df.to_excel(history_path, index=False, engine="openpyxl")
    _add_table_exact(history_path, "SPOHistory")
    return history_path


# ===== 入車時間付与 =====
def parse_groupeddata_json(cell_text) -> list:
    if isinstance(cell_text, list):
        return [x for x in cell_text if isinstance(x, dict)]
    if isinstance(cell_text, dict):
        return [cell_text]
    if cell_text is None:
        return []
    try:
        if pd.isna(cell_text):
            return []
    except Exception:
        pass
    raw = str(cell_text).strip()
    if not raw:
        return []
    candidates = [raw]
    if raw.startswith("\"") and raw.endswith("\"") and len(raw) >= 2:
        candidates.append(raw[1:-1])
    try:
        decoded_once = json.loads(raw)
        candidates.append(decoded_once)
    except Exception:
        pass
    for cand in candidates:
        obj = cand
        if isinstance(cand, str):
            try:
                obj = json.loads(cand)
            except Exception:
                continue
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except Exception:
                continue
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, dict)]
        if isinstance(obj, dict):
            return [obj]
    return []


def attach_pickup_start_time(
    spo_df: pd.DataFrame,
    master_df: pd.DataFrame,
    unmatched_csv_path: Optional[Path] = None,
) -> pd.DataFrame:
    """GroupedDataから入車時間マスタを参照して引取開始時間を付与"""
    if spo_df is None or spo_df.empty:
        return spo_df
    if master_df is None or master_df.empty:
        return spo_df
    for col in ("OData_納入先", "NONYUHIBIN", "入車時間"):
        if col not in master_df.columns:
            return spo_df
    master = master_df.copy()
    master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip()
    master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
    master["入車時間"] = master["入車時間"].astype(str).str.strip()
    master = master[(master["OData_納入先"] != "") & (master["NONYUHIBIN"] != "")]
    master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in master.iterrows()}

    # 武部等のグループ処理
    vendor_time_groups: Dict[str, Dict[int, list]] = {}
    for (v, bin_no), pickup_time in master_map.items():
        if v not in vendor_time_groups:
            vendor_time_groups[v] = {}
        normalized = _normalize_hhmm(pickup_time)
        if normalized:
            try:
                hh, mm = normalized.split(":", 1)
                mins = int(hh) * 60 + int(mm)
                if mins not in vendor_time_groups[v]:
                    vendor_time_groups[v][mins] = []
                vendor_time_groups[v][mins].append(bin_no)
            except Exception:
                pass
    vendor_sorted_groups: Dict[str, list] = {}
    for v, time_dict in vendor_time_groups.items():
        sorted_times = sorted(time_dict.keys())
        vendor_sorted_groups[v] = [(t, time_dict[t]) for t in sorted_times]

    def _to_minutes(hhmm: str) -> Optional[int]:
        s = _normalize_hhmm(hhmm)
        if not s:
            return None
        try:
            hh, mm = s.split(":", 1)
            return int(hh) * 66 + int(mm)
        except Exception:
            return None

    def _minutes_to_time(mins: int) -> str:
        if mins < 0:
            mins = 0
        return f"{mins // 60:02d}:{mins % 60:02d}"

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

    out = spo_df.copy()
    unmatched_rows = []
    for idx, row in out.iterrows():
        items = parse_groupeddata_json(row.get("GroupedData", ""))
        best_time = ""
        best_min: Optional[int] = None
        seen_keys = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            vendor = str(it.get("OData_納入先") or it.get("OData__x7d0d__x5165__x5148_", "")).strip()
            nony = str(it.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
            order2 = nony[-2:] if len(nony) >= 2 else ""
            if not vendor or not order2:
                continue
            key = (vendor, order2)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pickup = master_map.get(key, "")
            if pickup:
                mins = _to_minutes(pickup)
                if mins is None:
                    continue
                if best_min is None or mins > best_min:
                    best_min = mins
                    if vendor == "武部":
                        prev_group_time = _get_prev_group_time(vendor, mins)
                        if prev_group_time is not None:
                            best_time = _minutes_to_time(prev_group_time + 10)
                        else:
                            best_time = _minutes_to_time(mins + 10)
                    else:
                        try:
                            current_bin = int(order2)
                            if current_bin > 1:
                                prev_bin = f"{current_bin - 1:02d}"
                                prev_pickup = master_map.get((vendor, prev_bin), "")
                                if prev_pickup:
                                    prev_mins = _to_minutes(prev_pickup)
                                    if prev_mins is not None:
                                        best_time = _minutes_to_time(prev_mins + 10)
                                        continue
                        except (ValueError, TypeError):
                            pass
                        best_time = _minutes_to_time(mins + 10)
            else:
                if unmatched_csv_path is not None:
                    unmatched_rows.append({"index": idx, "vendor": vendor, "order2": order2})

        existing = str(out.at[idx, "引取開始時間"]) if "引取開始時間" in out.columns else ""
        if existing and existing.strip() and existing.strip() != "nan" and ":" in existing:
            continue
        if best_time and (not existing or pd.isna(existing) or existing.strip() in ("", "nan")):
            out.at[idx, "引取開始時間"] = best_time

    if unmatched_csv_path is not None and unmatched_rows:
        Path(unmatched_csv_path).parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(unmatched_rows, columns=["index", "vendor", "order2"]).to_csv(
            unmatched_csv_path, index=False, encoding="utf-8-sig"
        )
    return out
