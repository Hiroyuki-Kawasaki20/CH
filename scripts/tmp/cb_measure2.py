# -*- coding: utf-8 -*-  
# Issue #110 CB: strict 突合の失敗内訳と、案C(fallback一本化)の等価性measure  
# 読み取り専用。ファイルへの書き込みは一切行わない。  
# get_base_dir() は tkinter ダイアログを開くため、プロセス内でのみ差し替える。  
# 本ファイルは行継続記号を一切使用しない。  
SCRIPT_VERSION = "CB-AUTO-3"  
  
import hashlib  
import json  
import pathlib  
import sys  
import traceback  
  
import pandas as pd  
  
FLAGS = []  
REPORT = {}  
  
  
def sec(t):  
    print("")  
    print("=" * 74)  
    print(t)  
    print("=" * 74)  
  
  
def flag(lv, msg):  
    FLAGS.append((lv, msg))  
    print("  [" + lv + "] " + msg)  
  
  
def pal_series(df):  
    if "PLANKANBANSU" in df.columns:  
        return pd.to_numeric(df["PLANKANBANSU"], errors="coerce").fillna(0).astype(int)  
    return pd.Series([0] * len(df), index=df.index)  
  
  
def pal_sum(df):  
    if df is None:  
        return 0  
    if len(df) == 0:  
        return 0  
    if "PLANKANBANSU" not in df.columns:  
        return 0  
    return int(pal_series(df).sum())  
  
  
def main():  
    root = pathlib.Path(__file__).resolve().parents[2]  
    sys.path.insert(0, str(root))  
  
    sec("[0] 実行環境")  
    print("  SCRIPT_VERSION : " + SCRIPT_VERSION)  
    print("  python         : " + sys.version.replace("\n", " "))  
    print("  pandas         : " + pd.__version__)  
    print("  repo root      : " + str(root))  
  
    sec("[1] load_data() を GUI 抜きで再現（get_base_dir を差し替え）")  
    cfg_path = root / "config" / "ch_kanban_settings.json"  
    if not cfg_path.exists():  
        flag("STOP", "config/ch_kanban_settings.json がありません")  
        return  
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))  
    base = pathlib.Path(cfg.get("base_dir", ""))  
    print("  base_dir : " + str(base))  
    print("  exists   : " + str(base.exists()))  
    if not base.exists():  
        flag("STOP", "base_dir が存在しません")  
        return  
  
    try:  
        import src.services.data_loader as dl  
    except Exception as e:  
        flag("STOP", "data_loader の import 失敗: " + type(e).__name__ + ": " + str(e))  
        traceback.print_exc()  
        return  
  
    dl.get_base_dir = lambda: base  
    print("  monkeypatch : dl.get_base_dir -> base_dir（メモリ上のみ）")  
  
    try:  
        from src.utils.normalizer import _normalize_ukeire as nu  
        from src.utils.normalizer import _normalize_dest_name as nd  
    except Exception as e:  
        flag("STOP", "normalizer の import 失敗: " + type(e).__name__ + ": " + str(e))  
        return  
  
    try:  
        s_path = dl._resolve_shipments_path(base)  
    except Exception as e:  
        flag("STOP", "出荷情報CSVが見つかりません: " + str(e))  
        return  
    raw = s_path.read_bytes()  
    sha = hashlib.sha256(raw).hexdigest()  
    print("  入力CSV  : " + s_path.name)  
    print("  size     : " + str(s_path.stat().st_size) + " bytes")  
    print("  SHA256   : " + sha)  
    REPORT["入力CSV"] = s_path.name  
    REPORT["入力CSV SHA256"] = sha  
    REPORT["入力CSV size"] = str(s_path.stat().st_size) + " bytes"  
  
    try:  
        df_s, df_p = dl.load_data()  
    except Exception as e:  
        flag("STOP", "load_data() 失敗: " + type(e).__name__ + ": " + str(e))  
        traceback.print_exc()  
        return  
    print("  load_data : OK")  
    print("  shipments : " + str(len(df_s)) + "行 / " + str(pal_sum(df_s)) + "pal")  
    print("  places    : " + str(len(df_p)) + "行")  
    print("  shipments columns : " + str(list(df_s.columns)))  
    REPORT["入力 行数/パレット"] = str(len(df_s)) + "行 / " + str(pal_sum(df_s)) + "pal"  
  
    dm = dl.DataManager(df_s, df_p)  
  
    sec("[2] strict 4条件の失敗内訳（Issue #110 の空欄1）")  
    if "SSYUKKA" not in df_s.columns:  
        flag("STOP", "SSYUKKA 列がありません")  
        return  
    print("  --- SSYUKKA (入力) value_counts ---")  
    print(df_s["SSYUKKA"].value_counts().to_string())  
    print("  --- 仕入先工区 (places) value_counts ---")  
    print(df_p["仕入先工区"].value_counts().to_string())  
    set_ss = set(df_s["SSYUKKA"].astype(str).unique())  
    set_pk = set(df_p["仕入先工区"].astype(str).unique())  
    inter = sorted(set_ss & set_pk)  
    print("  積集合 : " + str(inter))  
    REPORT["SSYUKKA 一意"] = str(sorted(set_ss))  
    REPORT["仕入先工区 一意"] = str(sorted(set_pk))  
    if inter:  
        REPORT["積集合"] = str(inter)  
    else:  
        REPORT["積集合"] = "[] (空)"  
        flag("FOUND", "SSYUKKA と 仕入先工区 の積集合が空 -> strict は全便0件確定")  
  
    print("")  
    print("  --- 各条件の単独マッチ件数（place行ごと） ---")  
    print("  便名      受入   c1_SSYUKKA  c2_納入先CD  c3_KOKU  c4_UKEIRE  strict")  
    shp_u = None  
    if "UKEIRE" in df_s.columns:  
        shp_u = df_s["UKEIRE"].apply(nu)  
    strict_total = 0  
    for _, r in df_p.iterrows():  
        c1 = int((df_s["SSYUKKA"] == r["仕入先工区"]).sum())  
        c2 = -1  
        if "納入先コード" in df_s.columns:  
            c2 = int((df_s["納入先コード"] == str(r.get("納入先コード", ""))).sum())  
        c3 = -1  
        if "SYUKKAKOKU" in df_s.columns:  
            c3 = int((df_s["SYUKKAKOKU"] == r["納入先工区"]).sum())  
        c4 = -1  
        if shp_u is not None:  
            c4 = int((shp_u == nu(r["受入"])).sum())  
        sm = -1  
        try:  
            sm = int(dm._mask_for_place_row(r).sum())  
        except Exception as e:  
            print("    (mask 失敗 " + type(e).__name__ + ": " + str(e) + ")")  
        if sm > 0:  
            strict_total = strict_total + sm  
        line = "  " + str(r["便名"]).ljust(9) + str(r["受入"]).ljust(6)  
        line = line + str(c1).rjust(11) + str(c2).rjust(12)  
        line = line + str(c3).rjust(9) + str(c4).rjust(11) + str(sm).rjust(8)  
        print(line)  
    print("  strict 合計ヒット : " + str(strict_total))  
    REPORT["strict 合計ヒット"] = str(strict_total)  
    if strict_total == 0:  
        flag("FOUND", "strict は全place行で0件（デッドコードを実測）")  
  
    sec("[3] 案C 等価性：全(便名,受入,オーダー)で 現行 vs fallback-only")  
    pairs = df_p[["便名", "受入"]].drop_duplicates().values.tolist()  
    n_cmp = 0  
    n_diff = 0  
    tot_cur_r = 0  
    tot_cur_p = 0  
    tot_fb_r = 0  
    tot_fb_p = 0  
    diff_lines = []  
    for rt, rc in pairs:  
        try:  
            fb = dm._fallback_mask(rt, receipt=rc)  
        except Exception as e:  
            print("  fallback 失敗 " + str(rt) + "/" + str(rc) + " " + type(e).__name__)  
            continue  
        orders = []  
        if "NONYUHIBIN" in df_s.columns:  
            orders = sorted(df_s.loc[fb, "NONYUHIBIN"].astype(str).unique().tolist())  
        p_cur_r = 0  
        p_cur_p = 0  
        p_fb_r = 0  
        p_fb_p = 0  
        for od in orders:  
            n_cmp = n_cmp + 1  
            cur = dm.filter_shipments([{"便名": rt, "受入": rc, "オーダー": od}])  
            m2 = dm._fallback_mask(rt, receipt=rc, order=od)  
            fbd = df_s.loc[m2]  
            cr = len(cur)  
            cp = pal_sum(cur)  
            fr = len(fbd)  
            fp = pal_sum(fbd)  
            p_cur_r = p_cur_r + cr  
            p_cur_p = p_cur_p + cp  
            p_fb_r = p_fb_r + fr  
            p_fb_p = p_fb_p + fp  
            if cr != fr or cp != fp:  
                n_diff = n_diff + 1  
                d = "    DIFF " + str(rt) + "/" + str(rc) + "/" + od  
                d = d + "  現行 " + str(cr) + "行/" + str(cp) + "pal"  
                d = d + "  fb " + str(fr) + "行/" + str(fp) + "pal"  
                diff_lines.append(d)  
        tot_cur_r = tot_cur_r + p_cur_r  
        tot_cur_p = tot_cur_p + p_cur_p  
        tot_fb_r = tot_fb_r + p_fb_r  
        tot_fb_p = tot_fb_p + p_fb_p  
        mark = "  OK"  
        if p_cur_r != p_fb_r or p_cur_p != p_fb_p:  
            mark = "  ★DIFF"  
        line = "  " + str(rt).ljust(9) + str(rc).ljust(6)  
        line = line + " orders=" + str(len(orders)).rjust(3)  
        line = line + "  現行 " + str(p_cur_r).rjust(4) + "行/" + str(p_cur_p).rjust(4) + "pal"  
        line = line + "  fb " + str(p_fb_r).rjust(4) + "行/" + str(p_fb_p).rjust(4) + "pal"  
        print(line + mark)  
    print("")  
    print("  比較件数 : " + str(n_cmp) + " / 差分件数 : " + str(n_diff))  
    print("  合計 現行 : " + str(tot_cur_r) + "行 / " + str(tot_cur_p) + "pal")  
    print("  合計 fb   : " + str(tot_fb_r) + "行 / " + str(tot_fb_p) + "pal")  
    if diff_lines:  
        print("  --- 差分の詳細 ---")  
        for l in diff_lines:  
            print(l)  
    if n_diff == 0:  
        REPORT["案C 等価性(1選択)"] = "完全一致 " + str(n_cmp) + "件"  
    else:  
        REPORT["案C 等価性(1選択)"] = "差分 " + str(n_diff) + "/" + str(n_cmp) + "件"  
  
    sec("[4] 一括選択時の比較（複数選択の相互作用の検証）")  
    sels = []  
    for rt, rc in pairs:  
        try:  
            fb = dm._fallback_mask(rt, receipt=rc)  
        except Exception:  
            continue  
        if "NONYUHIBIN" not in df_s.columns:  
            continue  
        for od in sorted(df_s.loc[fb, "NONYUHIBIN"].astype(str).unique().tolist()):  
            sels.append({"便名": rt, "受入": rc, "オーダー": od})  
    print("  selections 件数 : " + str(len(sels)))  
    cur_all = None  
    try:  
        cur_all = dm.filter_shipments(sels)  
        print("  現行(一括)   : " + str(len(cur_all)) + "行 / " + str(pal_sum(cur_all)) + "pal")  
    except Exception as e:  
        print("  現行(一括) 失敗 : " + type(e).__name__ + ": " + str(e))  
    mask_u = None  
    for s in sels:  
        m = dm._fallback_mask(s["便名"], receipt=s["受入"], order=s["オーダー"])  
        if mask_u is None:  
            mask_u = m  
        else:  
            mask_u = mask_u | m  
    if mask_u is None:  
        fb_all = df_s.iloc[0:0]  
    else:  
        fb_all = df_s.loc[mask_u]  
    print("  fb-only(一括): " + str(len(fb_all)) + "行 / " + str(pal_sum(fb_all)) + "pal")  
    if cur_all is not None:  
        same = False  
        if len(cur_all) == len(fb_all):  
            if pal_sum(cur_all) == pal_sum(fb_all):  
                same = True  
        print("  一致 : " + str(same))  
        if same:  
            REPORT["案C 等価性(一括)"] = "一致"  
        else:  
            REPORT["案C 等価性(一括)"] = "不一致 現行 " + str(len(cur_all)) + "行 vs fb " + str(len(fb_all)) + "行"  
  
    sec("[5] 到達可能／到達不能の再検算")  
    try:  
        keys = set()  
        for _, r in df_p.iterrows():  
            keys.add((nd(str(r["便名"])), nu(r["受入"])))  
        vend = None  
        if hasattr(dm, "_fallback_vendor_series"):  
            vend = dm._fallback_vendor_series()  
            print("  vendor series : dm._fallback_vendor_series() を使用")  
        if vend is None:  
            col = None  
            for cand in ("納入先", "SYUKKASAKI", "NONYUSAKI"):  
                if cand in df_s.columns:  
                    col = cand  
                    break  
            if col is None:  
                raise RuntimeError("納入先に相当する列が見つかりません")  
            print("  vendor series : " + col + " 列を使用")  
            vend = df_s[col].astype(str).map(nd)  
        uk = df_s["UKEIRE"].apply(nu)  
        pal = pal_series(df_s)  
        hit = []  
        for v, u in zip(vend.tolist(), uk.tolist()):  
            hit.append((v, u) in keys)  
        reach = pd.Series(hit, index=df_s.index)  
        print("  到達可能 : " + str(int(reach.sum())) + "行 / " + str(int(pal[reach].sum())) + "pal")  
        print("  到達不能 : " + str(int((~reach).sum())) + "行 / " + str(int(pal[~reach].sum())) + "pal")  
        print("  検算 行  : " + str(len(df_s)) + " / 検算 pal : " + str(int(pal.sum())))  
        print("  --- 到達不能の内訳 ---")  
        ng = pd.DataFrame({"納入先": vend[~reach], "UKEIRE": uk[~reach], "pal": pal[~reach]})  
        if len(ng) > 0:  
            gg = ng.groupby(["納入先", "UKEIRE"]).agg(行数=("pal", "size"), パレット=("pal", "sum"))  
            print(gg.to_string())  
        else:  
            print("    なし")  
        REPORT["到達可能"] = str(int(reach.sum())) + "行 / " + str(int(pal[reach].sum())) + "pal"  
        REPORT["到達不能"] = str(int((~reach).sum())) + "行 / " + str(int(pal[~reach].sum())) + "pal"  
    except Exception as e:  
        flag("WARN", "[5] で例外: " + type(e).__name__ + ": " + str(e))  
        traceback.print_exc()  
  
    sec("[6] get_receipts_for_route の非対称（ukeire 指定で空になるか）")  
    empty_hit = 0  
    try:  
        uk_vals = sorted(df_s["UKEIRE"].astype(str).str.strip().unique().tolist())  
        print("  UKEIRE 一意 : " + str(uk_vals[:30]))  
        for rt in dm.get_routes():  
            a = dm.get_receipts_for_route(rt)  
            print("  " + str(rt).ljust(9) + " ukeire なし : " + str(a))  
            for u in uk_vals[:10]:  
                b = dm.get_receipts_for_route(rt, ukeire=u)  
                if not b:  
                    empty_hit = empty_hit + 1  
                    print("      ★空 : ukeire=" + repr(u))  
                    break  
        REPORT["get_receipts_for_route 空発生"] = str(empty_hit) + " 便"  
        if empty_hit > 0:  
            flag("FOUND", "get_receipts_for_route(ukeire=...) が空を返す便が " + str(empty_hit) + " 件")  
    except Exception as e:  
        flag("WARN", "[6] で例外: " + type(e).__name__ + ": " + str(e))  
        traceback.print_exc()  
  
    sec("[7] REPORT")  
    order = ["入力CSV", "入力CSV SHA256", "入力CSV size", "入力 行数/パレット",  
             "SSYUKKA 一意", "仕入先工区 一意", "積集合", "strict 合計ヒット",  
             "案C 等価性(1選択)", "案C 等価性(一括)", "到達可能", "到達不能",  
             "get_receipts_for_route 空発生"]  
    print("| 項目 | 実測値 |")  
    print("|---|---|")  
    for k in order:  
        v = str(REPORT.get(k, "-")).replace("|", "/")  
        print("| " + k + " | " + v + " |")  
    print("")  
    print("  --- FLAGS ---")  
    if FLAGS:  
        for lv, m in FLAGS:  
            print("  " + lv + " : " + m)  
    else:  
        print("  なし")  
    ns = 0  
    for lv, m in FLAGS:  
        if lv == "STOP":  
            ns = ns + 1  
    print("")  
    print("  総合判定 : STOP=" + str(ns))  
    print("  -> CC(実装)へ進むかは河崎の判断を待つ。")  
  
  
if __name__ == "__main__":  
    try:  
        main()  
    except Exception:  
        print("")  
        print("!!! 例外で中断 !!!")  
        traceback.print_exc()  
        sys.exit(1)  
