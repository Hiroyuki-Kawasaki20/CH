# -*- coding: utf-8 -*-  
# Issue #110 CA: 出荷場一覧.csv の実体採取（読み取り専用・判定自動化）  
# 本スクリプトは書き込みを一切行わない（open(w) / to_csv / mkdir を使わない）。  
SCRIPT_VERSION = "CA-AUTO-1"  
  
import datetime  
import hashlib  
import importlib  
import json  
import pathlib  
import sys  
import traceback  
  
import pandas as pd  
  
BOM = b"\xef\xbb\xbf"  
CRLF = b"\r\n"  
KEYS = ["便名", "受入", "仕入先工区", "納入先コード", "納入先工区"]  
COLS4 = ["受入", "仕入先工区", "納入先コード", "納入先工区"]  
ISSUE_TUPLES = [("28", "01N", "7371", "4"), ("61", "01N", "7371", "4")]  
ROUTE_EXCLUDE = {"日野EH", "武部"}  
  
REPORT = {}  
FLAGS = []  
  
  
def sec(title):  
    print("")  
    print("=" * 74)  
    print(title)  
    print("=" * 74)  
  
  
def flag(level, msg):  
    FLAGS.append((level, msg))  
    print("  [" + level + "] " + msg)  
  
  
def uniq_repr(series):  
    return str(sorted(set(repr(v) for v in series.unique())))  
  
  
def main():  
    root = pathlib.Path(__file__).resolve().parents[2]  
    sys.path.insert(0, str(root))  
  
    sec("[0] 実行環境")  
    print("  SCRIPT_VERSION : " + SCRIPT_VERSION)  
    print("  python         : " + sys.version.replace("\n", " "))  
    print("  pandas         : " + pd.__version__)  
    print("  repo root      : " + str(root))  
    print("  cwd            : " + str(pathlib.Path.cwd()))  
  
    # ---------- [1] base_dir ----------  
    sec("[1] base_dir の解決（config/*.json を直接読む。GUI は呼ばない）")  
    cfg_dir = root / "config"  
    picked_file = None  
    picked = None  
    if not cfg_dir.exists():  
        flag("STOP", "config ディレクトリがありません: " + str(cfg_dir))  
        return  
    for f in sorted(cfg_dir.glob("*.json")):  
        try:  
            d = json.loads(f.read_text(encoding="utf-8"))  
        except Exception as e:  
            print("  読込失敗 : " + f.name + " -> " + type(e).__name__ + ": " + str(e))  
            continue  
        keys = list(d.keys()) if isinstance(d, dict) else "(dict以外)"  
        print("  候補     : " + f.name + "  keys=" + str(keys))  
        if isinstance(d, dict) and d.get("base_dir"):  
            picked_file = f  
            picked = d  
    if picked is None:  
        flag("STOP", "base_dir を持つ config/*.json が見つかりません")  
        return  
    print("  採用ファイル : " + str(picked_file))  
    print("  base_dir     : " + repr(picked["base_dir"]))  
    REPORT["config ファイル"] = picked_file.name  
    REPORT["base_dir"] = repr(picked["base_dir"])  
  
    # ---------- [2] ファイル実体 ----------  
    base = pathlib.Path(picked["base_dir"])  
    p = base / "出荷場一覧.csv"  
    sec("[2] 出荷場一覧.csv の実体")  
    print("  path            : " + str(p))  
    print("  base_dir exists : " + str(base.exists()))  
    print("  file exists     : " + str(p.exists()))  
    if not p.exists():  
        flag("STOP", "出荷場一覧.csv が存在しません（base_dir 誤り or 未同期）")  
        return  
    raw = p.read_bytes()  
    st = p.stat()  
    sha = hashlib.sha256(raw).hexdigest()  
    mt = datetime.datetime.fromtimestamp(st.st_mtime).isoformat()  
    print("  size            : " + str(st.st_size) + " bytes")  
    print("  mtime           : " + mt)  
    print("  SHA256          : " + sha)  
    print("  head 32 bytes   : " + repr(raw[:32]))  
    print("  BOM(utf-8)      : " + str(raw[:3] == BOM))  
    print("  CRLF 含む       : " + str(CRLF in raw))  
    REPORT["絶対パス"] = str(p)  
    REPORT["SHA256"] = sha  
    REPORT["サイズ/更新"] = str(st.st_size) + " bytes / " + mt  
  
    # ---------- [3] read_csv_ja ----------  
    sec("[3] アプリ本体と同じ read_csv_ja() で読む")  
    df_app = None  
    for mod_name in ("src.utils.csv_utils", "src.utils.io_utils", "src.services.data_loader"):  
        try:  
            m = importlib.import_module(mod_name)  
        except Exception as e:  
            print("  import NG : " + mod_name + " -> " + type(e).__name__ + ": " + str(e))  
            continue  
        fn = getattr(m, "read_csv_ja", None)  
        if fn is None:  
            print("  関数なし  : " + mod_name + ".read_csv_ja")  
            continue  
        try:  
            df_app = fn(p)  
            print("  採用      : " + mod_name + ".read_csv_ja -> OK")  
            REPORT["read_csv_ja"] = mod_name  
            break  
        except Exception as e:  
            print("  実行NG    : " + mod_name + " -> " + type(e).__name__ + ": " + str(e))  
    if df_app is None:  
        flag("WARN", "read_csv_ja を再現できず。pd.read_csv(型推論) で代替 → アプリ再現：不可")  
        df_app = pd.read_csv(p)  
        REPORT["read_csv_ja"] = "再現不可（代替: pd.read_csv）"  
    df_app.columns = df_app.columns.str.strip()  
    print("  --- dtypes ---")  
    print(df_app.dtypes.to_string())  
    print("  総行数 : " + str(len(df_app)))  
    print("  --- 列名（順序付き・repr）---")  
    for i, c in enumerate(df_app.columns, start=1):  
        print("    " + str(i).rjust(2) + ": " + repr(c))  
    REPORT["列名"] = str(list(df_app.columns))  
    REPORT["総行数"] = str(len(df_app))  
  
    # ---------- [4] dtype=str ----------  
    sec("[4] dtype=str での読込（＝変質していない真値の基準）")  
    df_str = None  
    ok_encs = []  
    for enc in ("utf-8-sig", "cp932", "utf-8"):  
        try:  
            tmp = pd.read_csv(p, encoding=enc, dtype=str, keep_default_na=False)  
            ok_encs.append(enc)  
            if df_str is None:  
                df_str = tmp  
                REPORT["文字コード"] = enc  
        except Exception as e:  
            print("  NG : " + enc + " -> " + type(e).__name__)  
    print("  読めた encoding : " + str(ok_encs))  
    if df_str is None:  
        flag("STOP", "dtype=str でどの encoding でも読めません")  
        return  
    df_str.columns = df_str.columns.str.strip()  
    print("  採用 encoding   : " + str(REPORT.get("文字コード")))  
    print("")  
    print("  --- 全行ダンプ（dtype=str・真値）---")  
    print(df_str.to_string(index=True))  
  
    # ---------- [5] 型変質 ----------  
    sec("[5] ★型推論による値の変質（load_data() の astype(str) 再現）")  
    changed_cols = []  
    for c in KEYS:  
        if c not in df_app.columns:  
            print("  ※列が存在しません : " + repr(c))  
            continue  
        a = df_app[c].astype(str)  
        print("  --- " + c + " (dtype=" + str(df_app[c].dtype) + ") ---")  
        print("    astype(str) 一意 : " + uniq_repr(a))  
        if c in df_str.columns:  
            b = df_str[c]  
            print("    dtype=str  一意 : " + uniq_repr(b))  
            diff = sorted(set(  
                (repr(x), repr(y)) for x, y in zip(a.tolist(), b.tolist()) if x != y  
            ))  
            if diff:  
                changed_cols.append(c)  
                print("    ★変質(app, 真値) : " + str(diff))  
            else:  
                print("    ★変質 : なし")  
        bad = sorted(set(  
            repr(v) for v in a.unique()  
            if v.endswith(".0") or v in ("nan", "None", "")  
        ))  
        print("    危険値(.0/nan/空) : " + (str(bad) if bad else "なし"))  
    if changed_cols:  
        flag("FOUND", "型推論で値が変質した列 " + str(changed_cols)  
             + " → strict 突合が恒久的に失敗し得る（重大）")  
    else:  
        flag("OK", "型推論による値の変質は検出されず")  
    REPORT["★変質列"] = str(changed_cols) if changed_cols else "なし"  
  
    # ---------- [6] 便名正規化 ----------  
    sec("[6] 便名ユニーク（正規化 前 → 後）")  
    s_norm = None  
    if "便名" in df_app.columns:  
        s_raw = df_app["便名"].astype(str)  
        for v in sorted(s_raw.unique()):  
            print("    前 " + repr(v) + " (行数=" + str(int((s_raw == v).sum())) + ")")  
        norm_fn = None  
        for mod_name in ("src.utils.normalizer", "src.services.data_loader", "src.utils.normalize"):  
            try:  
                m = importlib.import_module(mod_name)  
            except Exception:  
                continue  
            for fname in ("_normalize_route_name", "normalize_route_name"):  
                cand = getattr(m, fname, None)  
                if callable(cand):  
                    norm_fn = cand  
                    print("  採用正規化関数 : " + mod_name + "." + fname)  
                    break  
            if norm_fn is not None:  
                break  
        if norm_fn is None:  
            flag("WARN", "便名の正規化関数が見つからず（正規化前の値で以降を算出）")  
            s_norm = s_raw  
        else:  
            s_norm = s_raw.map(norm_fn)  
        for v in sorted(s_norm.unique()):  
            print("    後 " + repr(v) + " (行数=" + str(int((s_norm == v).sum())) + ")")  
        ch = sorted(set(  
            (repr(x), repr(y)) for x, y in zip(s_raw.tolist(), s_norm.tolist()) if x != y  
        ))  
        print("  ★正規化で変わった値 : " + (str(ch) if ch else "なし"))  
        REPORT["便名(正規化前)"] = str(sorted(s_raw.unique()))  
        REPORT["便名(正規化後)"] = str(sorted(s_norm.unique()))  
    else:  
        flag("WARN", "便名 列が存在しません")  
  
    # ---------- [7] 組合せ ----------  
    sec("[7] (便名, 受入) の全組合せと重複")  
    if "便名" in df_app.columns and "受入" in df_app.columns:  
        d = df_app.copy()  
        for c in ("便名", "受入"):  
            d[c] = d[c].astype(str)  
        g = d.groupby(["便名", "受入"], dropna=False).size().reset_index(name="行数")  
        print(g.to_string(index=False))  
        print("  組合せ総数 : " + str(len(g)))  
        dup = g[g["行数"] > 1]  
        print("  重複組合せ : " + str(len(dup)) + " 件")  
        if len(dup):  
            print(dup.to_string(index=False))  
        REPORT["(便名,受入)組合せ/重複"] = str(len(g)) + " 組 / 重複 " + str(len(dup)) + " 件"  
    else:  
        flag("WARN", "便名 or 受入 列が無いため組合せを算出できません")  
  
    # ---------- [8] get_routes 相当 ----------  
    sec("[8] get_routes() 相当（ROUTE_EXCLUDE の除外を再現）")  
    print("  ※除外条件は " + str(sorted(ROUTE_EXCLUDE)) + " を前提とした再現値（実装との一致は要確認）")  
    if s_norm is not None:  
        rt = [str(x).strip() for x in s_norm.unique().tolist()]  
        kept = sorted([r for r in rt if r and r not in ROUTE_EXCLUDE])  
        excl = sorted([r for r in rt if (not r) or (r in ROUTE_EXCLUDE)])  
        print("  get_routes 相当 : " + str(kept))  
        print("  除外された便名  : " + str(excl))  
        REPORT["get_routes 相当"] = str(kept)  
        REPORT["除外便名"] = str(excl)  
  
    # ---------- [9] Issue #110 照合 ----------  
    sec("[9] Issue #110 記載との照合（PLACE 4値タプル）")  
    have = [c for c in COLS4 if c in df_str.columns]  
    if len(have) != 4:  
        flag("WARN", "4値照合に必要な列が揃いません。存在した列: " + str(have))  
    else:  
        print("  --- 全行の (受入, 仕入先工区, 納入先コード, 納入先工区) ---")  
        allt = set()  
        for i in range(len(df_str)):  
            r = df_str.iloc[i]  
            t = tuple(str(r[c]) for c in COLS4)  
            allt.add(t)  
            bname = repr(str(r["便名"])) if "便名" in df_str.columns else "?"  
            print("    row" + str(i).rjust(3) + "  便名=" + bname + "  " + repr(t))  
        print("")  
        for t in ISSUE_TUPLES:  
            hit = t in allt  
            verdict = "一致（現物に存在）" if hit else "不一致（現物に存在せず）"  
            print("  Issue記載 " + repr(t) + " -> " + verdict)  
            REPORT["Issue " + t[0] + " 照合"] = verdict  
  
    # ---------- [10] REPORT ----------  
    sec("[10] REPORT（この表をそのまま貼る）")  
    order = [  
        "config ファイル", "base_dir", "絶対パス", "SHA256", "サイズ/更新",  
        "文字コード", "read_csv_ja", "列名", "総行数",  
        "便名(正規化前)", "便名(正規化後)", "(便名,受入)組合せ/重複",  
        "get_routes 相当", "除外便名", "★変質列",  
        "Issue 28 照合", "Issue 61 照合",  
    ]  
    print("| 項目 | 実測値 |")  
    print("|---|---|")  
    for k in order:  
        v = str(REPORT.get(k, "-")).replace("|", "/")  
        print("| " + k + " | " + v + " |")  
  
    print("")  
    print("  --- FLAGS ---")  
    if FLAGS:  
        for lv, msg in FLAGS:  
            print("  " + lv + " : " + msg)  
    else:  
        print("  なし")  
    n_stop = len([1 for lv, _ in FLAGS if lv == "STOP"])  
    n_found = len([1 for lv, _ in FLAGS if lv == "FOUND"])  
    print("")  
    print("  総合判定 : STOP=" + str(n_stop) + " / FOUND=" + str(n_found))  
    if n_stop:  
        print("  → STOP があるため CB へ進んではならない。")  
    else:  
        print("  → STOP なし。CB へ進むかは河崎の判断を待つ。")  
  
  
if __name__ == "__main__":  
    try:  
        main()  
    except Exception:  
        print("")  
        print("!!! 例外で中断 !!!")  
        traceback.print_exc()  
        sys.exit(1)  
