# -*- coding: utf-8 -*-
# Issue #110 CC検証: 改修後コードが CB 基準値と一致するか / ukeire 対称化が効いているか
# 読み取り専用。ファイルへの書き込みは一切行わない。行継続記号は使用しない。
SCRIPT_VERSION = "CC-VERIFY-1"

import hashlib
import json
import pathlib
import sys
import traceback

import pandas as pd

# ---- CB(改修前)で実測した基準値 ----
BASE_SHA256 = "3367f389cd88eea142c13b7f2aeb4bc12f0654c9e048a4a6a99e89dfa82a6ebb"
BASE_ROWS = 1113
BASE_PAL = 1250
BASE_CMP = 328
BASE_SEL_ROWS = 1030
BASE_SEL_PAL = 1162
BASE_UNREACH_ROWS = 83
BASE_UNREACH_PAL = 88

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
	return int(pal_series(df).sum())


def main():
	root = pathlib.Path(__file__).resolve().parents[2]
	sys.path.insert(0, str(root))

	sec("[0] 実行環境")
	print("  SCRIPT_VERSION : " + SCRIPT_VERSION)
	print("  python         : " + sys.version.replace("\n", " "))
	print("  pandas         : " + pd.__version__)
	print("  repo root      : " + str(root))

	sec("[1] データ読込（get_base_dir はメモリ上のみ差し替え）")
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
	except Exception as e:
		flag("STOP", "出荷情報CSVが見つかりません: " + str(e))
		return
	sha = hashlib.sha256(s_path.read_bytes()).hexdigest()
	print("  入力CSV : " + s_path.name)
	print("  SHA256  : " + sha)
	same_src = (sha == BASE_SHA256)
	print("  CB時と同一 : " + str(same_src))
	if not same_src:
		flag("WARN", "入力CSVが CB 時と異なる（日次更新）。絶対値の一致比較は無効。相対検証のみ有効")
	REPORT["入力CSV SHA256 一致"] = str(same_src)
	try:
		df_s, df_p = dl.load_data()
	except Exception as e:
		flag("STOP", "load_data() 失敗: " + type(e).__name__ + ": " + str(e))
		traceback.print_exc()
		return
	print("  shipments : " + str(len(df_s)) + "行 / " + str(pal_sum(df_s)) + "pal")
	print("  places    : " + str(len(df_p)) + "行")
	REPORT["入力 行数/パレット"] = str(len(df_s)) + "行 / " + str(pal_sum(df_s)) + "pal"
	dm = dl.DataManager(df_s, df_p)

	sec("[2] API 形状の確認（strict 撤去と新メソッドの導入）")
	has_old = hasattr(dm, "_mask_for_place_row")
	has_match = hasattr(dm, "_match_mask")
	has_um = hasattr(dm, "_ukeire_mask")
	has_fb = hasattr(dm, "_fallback_mask")
	print("  _mask_for_place_row 残存 : " + str(has_old) + "  (期待 False)")
	print("  _match_mask 存在         : " + str(has_match) + "  (期待 True)")
	print("  _ukeire_mask 存在        : " + str(has_um) + "  (期待 True)")
	print("  _fallback_mask 存在      : " + str(has_fb) + "  (期待 True)")
	if has_old:
		flag("WARN", "_mask_for_place_row が残っている（置換漏れの可能性）")
	if not (has_match and has_um and has_fb):
		flag("STOP", "新メソッドが見つからない。置換が正しく行われていない")
		return
	REPORT["strict 撤去"] = "OK" if not has_old else "残存"

	sec("[3] 改修後の突合結果 vs CB 基準値")
	pairs = df_p[["便名", "受入"]].drop_duplicates().values.tolist()
	n_cmp = 0
	tot_r = 0
	tot_p = 0
	sels = []
	for rt, rc in pairs:
		try:
			fb = dm._fallback_mask(rt, receipt=rc)
		except Exception as e:
			print("  fallback 失敗 " + str(rt) + "/" + str(rc) + " " + type(e).__name__)
			continue
		orders = []
		if "NONYUHIBIN" in df_s.columns:
			orders = sorted(df_s.loc[fb, "NONYUHIBIN"].astype(str).unique().tolist())
		p_r = 0
		p_p = 0
		for od in orders:
			n_cmp = n_cmp + 1
			cur = dm.filter_shipments([{"便名": rt, "受入": rc, "オーダー": od}])
			p_r = p_r + len(cur)
			p_p = p_p + pal_sum(cur)
			sels.append({"便名": rt, "受入": rc, "オーダー": od})
		tot_r = tot_r + p_r
		tot_p = tot_p + p_p
		line = "  " + str(rt).ljust(9) + str(rc).ljust(6)
		line = line + " orders=" + str(len(orders)).rjust(3)
		line = line + "  " + str(p_r).rjust(4) + "行/" + str(p_p).rjust(4) + "pal"
		print(line)
	print("")
	print("  単一選択 比較件数 : " + str(n_cmp) + "  (CB=" + str(BASE_CMP) + ")")
	print("  単一選択 合計     : " + str(tot_r) + "行 / " + str(tot_p) + "pal"
		  + "  (CB=" + str(BASE_SEL_ROWS) + "行/" + str(BASE_SEL_PAL) + "pal)")
	bulk = dm.filter_shipments(sels)
	print("  一括選択          : " + str(len(bulk)) + "行 / " + str(pal_sum(bulk)) + "pal")
	ok3 = False
	if same_src:
		if n_cmp == BASE_CMP and tot_r == BASE_SEL_ROWS and tot_p == BASE_SEL_PAL:
			if len(bulk) == BASE_SEL_ROWS and pal_sum(bulk) == BASE_SEL_PAL:
				ok3 = True
		if ok3:
			print("  ★判定 : CB 基準値と完全一致（挙動不変を実測）")
			REPORT["CB 基準値との一致"] = "完全一致"
		else:
			flag("STOP", "CB 基準値と不一致。案Cの等価性が崩れている")
			REPORT["CB 基準値との一致"] = "不一致"
	else:
		rel = (len(bulk) == tot_r and pal_sum(bulk) == tot_p)
		print("  ★判定 : 入力CSV差異のため相対検証のみ。単一総和と一括の一致 = " + str(rel))
		REPORT["CB 基準値との一致"] = "入力CSV差異のため絶対比較不可（相対一致=" + str(rel) + "）"

	sec("[4] ukeire 対称化の検証（その便に実在する UKEIRE のみを対象）")
	pbr = {}
	for _, r in df_p.iterrows():
		pbr.setdefault(str(r["便名"]), set()).add(str(r["受入"]))
	print("  便名      ukeire  出荷行数  places登録  get_receipts_for_route  判定")
	ng4 = 0
	unreg = []
	for rt in dm.get_routes():
		try:
			fb = dm._fallback_mask(rt)
		except Exception as e:
			print("  " + str(rt) + " fallback 失敗 " + type(e).__name__)
			continue
		uks = sorted(df_s.loc[fb, "UKEIRE"].astype(str).str.strip().unique().tolist())
		for u in uks:
			rows = int((fb & (df_s["UKEIRE"].astype(str).str.strip() == u)).sum())
			reg = False
			for rc in pbr.get(rt, set()):
				if nu(rc) == nu(u):
					reg = True
			got = dm.get_receipts_for_route(rt, ukeire=u)
			judge = "OK"
			if reg and not got:
				judge = "★NG(登録済なのに空)"
				ng4 = ng4 + 1
			if (not reg) and got:
				judge = "★NG(未登録なのに非空)"
				ng4 = ng4 + 1
			if not reg:
				unreg.append(str(rt) + "/" + u + " (" + str(rows) + "行)")
			line = "  " + str(rt).ljust(9) + str(u).ljust(7)
			line = line + str(rows).rjust(8) + str(reg).rjust(12)
			line = line + ("  " + str(got)).ljust(26) + judge
			print(line)
	print("")
	print("  未登録ペア（GUIから到達できない）: " + str(unreg))
	print("  NG 件数 : " + str(ng4))
	REPORT["ukeire 対称化"] = "OK" if ng4 == 0 else ("NG " + str(ng4) + "件")
	REPORT["未登録ペア"] = str(unreg)
	if ng4 == 0:
		flag("FOUND", "ukeire 指定が登録済ペアで機能。空になるのは places 未登録ペアのみ")

	sec("[5] get_receipts_for_route_order の戻り値の値域（受入 か UKEIRE か）")
	bad5 = 0
	for rt in dm.get_routes():
		allow = pbr.get(rt, set())
		try:
			ods = dm.get_orders_for_route(rt)
		except Exception as e:
			print("  " + str(rt) + " orders 取得失敗 " + type(e).__name__)
			continue
		for od in ods[:3]:
			got = dm.get_receipts_for_route_order(rt, od)
			outside = []
			for g in got:
				if str(g) not in allow:
					outside.append(str(g))
			mk = "OK"
			if outside:
				mk = "★値域外 " + str(outside)
				bad5 = bad5 + 1
			print("  " + str(rt).ljust(9) + str(od).ljust(12) + str(got).ljust(20) + mk)
	print("  値域外 件数 : " + str(bad5))
	REPORT["get_receipts_for_route_order 値域"] = "OK" if bad5 == 0 else ("値域外 " + str(bad5) + "件")

	sec("[6] 到達可能／到達不能")
	try:
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
		print("  到達可能 : " + str(int(reach.sum())) + "行 / " + str(int(pal[reach].sum())) + "pal")
		print("  到達不能 : " + str(ur) + "行 / " + str(up) + "pal"
			  + "  (CB=" + str(BASE_UNREACH_ROWS) + "行/" + str(BASE_UNREACH_PAL) + "pal)")
		ng = pd.DataFrame({"納入先": vend[~reach], "UKEIRE": uk[~reach], "pal": pal[~reach]})
		if len(ng) > 0:
			gg = ng.groupby(["納入先", "UKEIRE"]).agg(行数=("pal", "size"), パレット=("pal", "sum"))
			print(gg.to_string())
		REPORT["到達不能"] = str(ur) + "行 / " + str(up) + "pal"
	except Exception as e:
		flag("WARN", "[6] で例外: " + type(e).__name__ + ": " + str(e))
		traceback.print_exc()

	sec("[7] REPORT")
	order = ["入力CSV SHA256 一致", "入力 行数/パレット", "strict 撤去",
			 "CB 基準値との一致", "ukeire 対称化", "未登録ペア",
			 "get_receipts_for_route_order 値域", "到達不能"]
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
