# -*- coding: utf-8 -*-
# Issue #110 CD-2b: 到達不能サマリ / 警告文面 / 突合の回帰 を実測
# 読み取り専用。ファイルへの書き込みは一切行わない。行継続記号は使用しない。
SCRIPT_VERSION = "CD2-VERIFY-1"

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


def main():
    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))

    sec("[0] 実行環境")
    print("  SCRIPT_VERSION : " + SCRIPT_VERSION)
    print("  python         : " + sys.version.replace("\n", " "))
    print("  pandas         : " + pd.__version__)
    print("  repo root      : " + str(root))

    sec("[1] データ読込 + SHA256")
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
        from src.utils.normalizer import _normalize_dest_name as nd
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
    pal = pal_series(df_s)
    print("  入力CSV : " + s_path.name)
    print("  SHA256  : " + sha)
    print("  shipments : " + str(len(df_s)) + "行 / " + str(int(pal.sum())) + "pal")
    print("  places    : " + str(len(df_p)) + "行")
    REPORT["入力CSV SHA256"] = sha
    REPORT["shipments"] = str(len(df_s)) + "行 / " + str(int(pal.sum())) + "pal"
    dm = dl.DataManager(df_s, df_p)

    sec("[2] 新メソッドの存在確認")
    ok2 = True
    for name in ["collect_unreachable_summary", "build_unreachable_warning_message"]:
        has = hasattr(dm, name)
        print("  " + name.ljust(34) + " : " + str(has))
        if not has:
            ok2 = False
    if not ok2:
        flag("STOP", "新メソッドが見つかりません（挿入位置がクラス外の可能性）")
        return

    summary = None
    sec("[3] collect_unreachable_summary の実測")
    try:
        summary = dm.collect_unreachable_summary()
        print("  rows    : " + str(summary.get("rows")))
        print("  pallets : " + str(summary.get("pallets")))
        print("  pairs   :")
        for p in summary.get("pairs", []):
            print("    " + str(p))
        REPORT["到達不能(新メソッド)"] = str(summary.get("rows")) + "行 / " + str(summary.get("pallets")) + "pal"
    except Exception as e:
        flag("STOP", "[3] で例外: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()

    sec("[4] cd_probe.py [6] と同一ロジックで独立に再計算し一致を検算")
    try:
        keys = set()
        for _, r in df_p.iterrows():
            keys.add((nd(str(r["便名"])), nu(r["受入"])))
        vend = dm._fallback_vendor_series()
        uk = df_s["UKEIRE"].apply(nu)
        hit = []
        for v, u in zip(vend.tolist(), uk.tolist()):
            hit.append((v, u) in keys)
        reach = pd.Series(hit, index=df_s.index)
        miss = ~reach
        ur = int(miss.sum())
        up = int(pal[miss].sum())
        print("  probe互換 到達不能 : " + str(ur) + "行 / " + str(up) + "pal")
        exp_pairs = []
        ngdf = pd.DataFrame({"納入先": vend[miss], "UKEIRE": df_s["UKEIRE"].astype(str)[miss], "pal": pal[miss]})
        if len(ngdf) > 0:
            gg = ngdf.groupby(["納入先", "UKEIRE"]).agg(行数=("pal", "size"), パレット=("pal", "sum"))
            print(gg.to_string())
            for idx, row in gg.iterrows():
                exp_pairs.append((str(idx[0]), str(idx[1]), int(row["行数"]), int(row["パレット"])))
        got_pairs = []
        if summary is not None:
            for p in summary.get("pairs", []):
                got_pairs.append((str(p.get("vendor")), str(p.get("ukeire")), int(p.get("rows")), int(p.get("pallets"))))
        print("  probe互換 pairs  : " + str(exp_pairs))
        print("  新メソッド pairs : " + str(got_pairs))
        same = False
        if summary is not None:
            same = (int(summary.get("rows", -1)) == ur) and (int(summary.get("pallets", -1)) == up) and (sorted(got_pairs) == sorted(exp_pairs))
        print("  一致判定 : " + str(same))
        REPORT["probe互換との一致"] = str(same)
        if not same:
            flag("STOP", "新メソッドの集計が cd_probe.py [6] と一致しません")
    except Exception as e:
        flag("STOP", "[4] で例外: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()

    sec("[5] 警告文面（GUI に出る文字列そのまま）")
    try:
        msg = dm.build_unreachable_warning_message()
        print("  --- ここから ---")
        print(msg)
        print("  --- ここまで ---")
        print("  行数 : " + str(len(msg.splitlines())))
        REPORT["警告文面 行数"] = str(len(msg.splitlines()))
        head_ok = msg.startswith("出荷場一覧に未登録の組合せがあるため、次のデータは割り振り対象外です。")
        print("  1行目一致 : " + str(head_ok))
        if not head_ok:
            flag("WARN", "警告文面の1行目が計測時の文面と異なります")
    except Exception as e:
        flag("STOP", "[5] で例外: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()

    sec("[6] 突合の回帰（CD-1 の結果が変わっていないこと）")
    try:
        expect_nonempty = [("日野", "6"), ("日野", "7"), ("日野", "06"), ("日野", "07"),
                           ("KVC", "B7"), ("元町", "1W"), ("高岡", "K5"), ("織機", "28"), ("織機", "61")]
        expect_empty = [("KVC", "B3"), ("織機", "21")]
        ng6 = 0
        for rt, v in expect_nonempty:
            got = dm.get_receipts_for_route(rt, ukeire=v)
            mk = "OK"
            if not got:
                mk = "★NG(空になった)"
                ng6 = ng6 + 1
            print("  非空期待 " + str(rt).ljust(6) + str(v).ljust(6) + str(got).ljust(16) + mk)
        for rt, v in expect_empty:
            got = dm.get_receipts_for_route(rt, ukeire=v)
            mk = "OK"
            if got:
                mk = "★NG(空でない)"
                ng6 = ng6 + 1
            print("  空期待   " + str(rt).ljust(6) + str(v).ljust(6) + str(got).ljust(16) + mk)
        print("  NG 件数 : " + str(ng6))
        REPORT["突合の回帰 NG"] = str(ng6) + "件"
        if ng6 > 0:
            flag("STOP", "CD-1 時点の突合結果と差異あり（CD-2 の追記が既存挙動に影響）")
    except Exception as e:
        flag("STOP", "[6] で例外: " + type(e).__name__ + ": " + str(e))
        traceback.print_exc()

    sec("[7] REPORT")
    order = ["入力CSV SHA256", "shipments", "到達不能(新メソッド)", "probe互換との一致",
             "警告文面 行数", "突合の回帰 NG"]
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
