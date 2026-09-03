# -*- coding: utf-8 -*-
# Issue #110 CD-0: GUI が渡す ukeire の実値採取 + ukeire 値のゆれに対する耐性の実測
# 読み取り専用。ファイルへの書き込みは一切行わない。行継続記号は使用しない。
SCRIPT_VERSION = "CD-PROBE-1"

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


def variants(v):
    out = []
    s = str(v).strip()
    if s == "":
        return out
    out.append(s)
    if s.isdigit():
        st = s.lstrip("0")
        if st == "":
            st = "0"
        if st not in out:
            out.append(st)
        z = s.zfill(2)
        if z not in out:
            out.append(z)
    return out


def main():
    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))

    sec("[0] 実行環境")
    print("  SCRIPT_VERSION : " + SCRIPT_VERSION)
    print("  python         : " + sys.version.replace("\n", " "))
    print("  pandas         : " + pd.__version__)
    print("  repo root      : " + str(root))

    sec("[1] data_loader.py の該当箇所の残存確認（コメント見出しと strict）")
    dlp = root / "src" / "services" / "data_loader.py"
    if not dlp.exists():
        flag("STOP", "src/services/data_loader.py がありません")
        return
    lines = dlp.read_text(encoding="utf-8", errors="replace").splitlines()
    keys = ["_mask_for_place_row", "突合ロジック", "def _ukeire_mask", "def _match_mask",
            "def _fallback_mask", "_normalize_ukeire", "Issue #110"]
    n_hit = 0
    for i, ln in enumerate(lines, 1):
        for k in keys:
            if k in ln:
                n_hit = n_hit + 1
                print("  " + str(i).rjust(5) + ": " + ln.rstrip()[:120])
                break
    print("  ヒット行数 : " + str(n_hit) + " / 総行数 " + str(len(lines)))

    sec("[2] gui.py が ukeire に渡している実値を採取（読み取りのみ）")
    guip = root / "src" / "app" / "gui.py"
    if not guip.exists():
        flag("WARN", "src/app/gui.py がありません")
    else:
        glines = guip.read_text(encoding="utf-8", errors="replace").splitlines()
        shown = 0
        for i, ln in enumerate(glines, 1):
            if "ukeire" in ln:
                if shown < 90:
                    print("  " + str(i).rjust(5) + ": " + ln.rstrip()[:150])
                shown = shown + 1
        print("  ukeire を含む行数 : " + str(shown) + " / 総行数 " + str(len(glines)))
        print("")
        print("  --- 表示名マッピングらしき定義行（route と ukeire を同時に含む行） ---")
        m2 = 0
        for i, ln in enumerate(glines, 1):
            if "ukeire" in ln and "route" in ln:
                m2 = m2 + 1
                print("  " + str(i).rjust(5) + ": " + ln.rstrip()[:150])
        print("  該当 : " + str(m2) + " 行")

    sec("[3] データ読込")
    cfg_path = root / "config" / "ch_kanban_settings.json"
    if not cfg_path.exists():
        flag("STOP", "config/ch_kanban_settings.json がありません")
        return
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = pathlib.Path(cfg.get("base_dir", ""))
    if not base.exists():
        flag("STOP", "base_dir が存在しません: " + str(base))
        return
    try:
        import src.services.data_loader as dl
        from src.utils.normalizer import _normalize_ukeire as nu
    except Exception as e:
        flag("STOP", "import 失敗: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()
        return
    dl.get_base_dir = lambda: base
    try:
        s_path = dl._resolve_shipments_path(base)
        sha = hashlib.sha256(s_path.read_bytes()).hexdigest()
        df_s, df_p = dl.load_data()
    except Exception as e:
        flag("STOP", "load_data 失敗: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()
        return
    print("  入力CSV : " + s_path.name)
    print("  SHA256  : " + sha)
    print("  shipments : " + str(len(df_s)) + "行 / " + str(int(pal_series(df_s).sum())) + "pal")
    REPORT["入力CSV SHA256"] = sha
    dm = dl.DataManager(df_s, df_p)

    sec("[4] ukeire 値のゆれ耐性（生値 / ゼロ埋めなし / ゼロ埋めあり）")
    pbr = {}
    for _, r in df_p.iterrows():
        pbr.setdefault(str(r["便名"]), set()).add(str(r["受入"]))
    print("  便名      渡した値   正規化後  該当行数  受入登録  戻り値                判定")
    ng = 0
    ng_list = []
    for rt in dm.get_routes():
        try:
            fb = dm._fallback_mask(rt)
        except Exception as e:
            print("  " + str(rt) + " fallback 失敗 " + type(e).__name__)
            continue
        uk_data = sorted(df_s.loc[fb, "UKEIRE"].astype(str).str.strip().unique().tolist())
        cands = []
        for u in uk_data:
            for v in variants(u):
                if v not in cands:
                    cands.append(v)
        for rc in sorted(pbr.get(rt, set())):
            for v in variants(rc):
                if v not in cands:
                    cands.append(v)
        uk_norm = df_s["UKEIRE"].apply(nu)
        for v in cands:
            rows = int((fb & (uk_norm == nu(v))).sum())
            reg = False
            for rc in pbr.get(rt, set()):
                if nu(rc) == nu(v):
                    reg = True
            got = dm.get_receipts_for_route(rt, ukeire=v)
            judge = "OK"
            if reg and rows > 0 and not got:
                judge = "★NG(値のゆれで空)"
                ng = ng + 1
                ng_list.append(str(rt) + "/" + v)
            if (not reg) and got:
                judge = "★NG(未登録なのに非空)"
                ng = ng + 1
                ng_list.append(str(rt) + "/" + v)
            line = "  " + str(rt).ljust(9) + str(v).ljust(10) + str(nu(v)).ljust(9)
            line = line + str(rows).rjust(8) + str(reg).rjust(10)
            line = line + ("  " + str(got)).ljust(22) + judge
            print(line)
    print("")
    print("  NG 件数 : " + str(ng))
    print("  NG 一覧 : " + str(ng_list))
    REPORT["ukeire 値ゆれ NG"] = str(ng) + "件 " + str(ng_list)
    if ng > 0:
        flag("FOUND", "ukeire の値のゆれで受入が空になるケースを検出（_ukeire_mask の正規化が必要）")

    sec("[5] get_orders_for_route も同様に確認")
    ng5 = 0
    for rt in dm.get_routes():
        try:
            fb = dm._fallback_mask(rt)
        except Exception:
            continue
        uk_data = sorted(df_s.loc[fb, "UKEIRE"].astype(str).str.strip().unique().tolist())
        for u in uk_data:
            for v in variants(u):
                a = dm.get_orders_for_route(rt, ukeire=v)
                mk = "OK"
                if nu(v) == nu(u) and not a:
                    mk = "★空"
                    ng5 = ng5 + 1
                print("  " + str(rt).ljust(9) + str(v).ljust(8) + "orders=" + str(len(a)).rjust(3) + "  " + mk)
    print("  空 件数 : " + str(ng5))
    REPORT["get_orders_for_route 空"] = str(ng5) + "件"

    sec("[6] 到達不能サマリ（CD の警告文の材料）")
    try:
        from src.utils.normalizer import _normalize_dest_name as nd
        keys = set()
        for _, r in df_p.iterrows():
            keys.add((nd(str(r["便名"])), nu(r["受入"])))
        vend = dm._fallback_vendor_series()
        uk = df_s["UKEIRE"].apply(nu)
        pal = pal_series(df_s)
        hit = []
        for v, u in zip(vend.tolist(), uk.tolist()):
            hit.append((v, u) in keys)
        reach = pd.Series(hit, index=df_s.index)
        ur = int((~reach).sum())
        up = int(pal[~reach].sum())
        print("  到達不能 : " + str(ur) + "行 / " + str(up) + "pal")
        ngdf = pd.DataFrame({"納入先": vend[~reach], "UKEIRE": df_s["UKEIRE"].astype(str)[~reach], "pal": pal[~reach]})
        parts = []
        if len(ngdf) > 0:
            gg = ngdf.groupby(["納入先", "UKEIRE"]).agg(行数=("pal", "size"), パレット=("pal", "sum"))
            print(gg.to_string())
            for idx, row in gg.iterrows():
                parts.append(str(idx[0]) + "/" + str(idx[1]) + " " + str(int(row["行数"])) + "行(" + str(int(row["パレット"])) + "パレット)")
        print("")
        print("  --- 警告メッセージ案（そのまま GUI に出す想定） ---")
        if parts:
            print("  出荷場一覧に未登録の組合せがあるため、次のデータは割り振り対象外です。")
            for p in parts:
                print("    ・" + p)
            print("  合計 " + str(ur) + "行 / " + str(up) + "パレット")
        else:
            print("  （到達不能なし）")
        REPORT["到達不能"] = str(ur) + "行 / " + str(up) + "pal"
        REPORT["未登録ペア"] = str(parts)
    except Exception as e:
        flag("WARN", "[6] で例外: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()

    sec("[7] REPORT")
    order = ["入力CSV SHA256", "ukeire 値ゆれ NG", "get_orders_for_route 空",
             "到達不能", "未登録ペア"]
    print("| 項目 | 実測値 |")
    print("|---|---|")
    for k in order:
        print("| " + k + " | " + str(REPORT.get(k, "-")).replace("|", "/") + " |")
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
    print("  -> 次工程へ進むかは河崎の判断を待つ。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("")
        print("!!! 例外で中断 !!!")
        traceback.print_exc()
        sys.exit(1)
