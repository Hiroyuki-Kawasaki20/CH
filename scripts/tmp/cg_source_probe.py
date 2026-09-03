# -*- coding: utf-8 -*-
"""CG工程 前詰め実装のソース採取（読み取り専用）

process_assigner.py を import せず、テキスト + ast だけで静的解析する。
pandas / src を一切 import しない。ファイル書き込み・git 操作を一切行わない。
標準出力のみ。SECTION 引数で A（走査）/ B（ソース全文）を切り替える。
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "CG-source-probe-1"
SECTION = sys.argv[1].strip().upper() if len(sys.argv) > 1 else "A"
DO_A = (SECTION == "A")
DO_B = (SECTION == "B")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
T0 = time.time()
FLAGS = []
VALS = {}
DEFS = []
OCC = {}
DUMPED = {}

DUMP_FIXED = [
    "_fits_idle_gap_on_main",
    "_try_front_pack_to_main_idle_gap",
    "_hino_front_pack_allowed",
    "_adjust_start_for_breaks",
    "_calc_work_end_with_breaks",
    "_seconds_to_hhmm",
]

PROBE_NAMES = [
    "_fits_idle_gap_on_main",
    "_fits_idle_gap_on_relief",
    "_try_front_pack_to_main_idle_gap",
    "_try_front_pack_to_relief_idle_gap",
    "_hino_front_pack_allowed",
    "_post_serialize_front_pack",
    "_try_repromote_overflow_to_relief",
    "_reapply_overflow_for_relief",
    "_seconds_to_hhmm",
    "_adjust_start_for_breaks",
    "_calc_work_end_with_breaks",
    "mtn_start_floor_map",
    "front_pack_diag",
    "PROC_RELIEF",
    "PROC_OVERFLOW",
    "EXHAUSTIVE_THRESHOLD",
]

LINE_KEYS = [
    "gap_end",
    "gap_start",
    "earliest_start",
    "earliest_end",
    "work_dur",
    "mtn_start_floor_map",
    "86400",
    "DAY_START",
]

NORM_RE = re.compile("secs|second|hhmm|normal|day|floor|wrap|midnight", re.IGNORECASE)
WIDE_RE = re.compile("front_pack|idle_gap|overflow|relief|hino", re.IGNORECASE)

def flag(level, msg):
    FLAGS.append((str(level), str(msg)))

def sec(no, title):
    print("")
    print("=" * 78)
    print("[{0}] {1}".format(no, title))
    print("=" * 78)
    sys.stdout.flush()

def find_defs(name):
    return [d for d in DEFS if d["name"] == name]

def enclosing(lineno):
    cands = [d for d in DEFS if d["lineno"] <= lineno <= d["end"]]
    if not cands:
        return "<module>"
    cands.sort(key=lambda d: d["end"] - d["lineno"])
    d = cands[0]
    return "{0}(L{1}-{2},depth={3})".format(d["name"], d["lineno"], d["end"], d["depth"])

sec(0, "実行環境")
print("SCRIPT_VERSION = " + SCRIPT_VERSION)
print("SECTION        = " + SECTION)
print("ROOT           = " + str(ROOT))
print("PYTHON         = " + sys.version.split()[0])
print("EXECUTABLE     = " + str(sys.executable))
print("NOTE           = no pandas / no src import / read-only / no file write")

TARGET = None
SRC_TEXT = ""
SRC_LINES = []
TREE = None

sec(1, "対象ファイルの発見と SHA256")
try:
    cands = sorted(ROOT.glob("src/**/process_assigner.py"))
    print("candidates = " + str([str(p.relative_to(ROOT)) for p in cands]))
    if not cands:
        flag("STOP", "process_assigner.py が見つからない")
    else:
        TARGET = cands[0]
        SRC_TEXT = TARGET.read_text(encoding="utf-8")
        SRC_LINES = SRC_TEXT.splitlines()
        h = hashlib.sha256()
        h.update(TARGET.read_bytes())
        print("TARGET = " + str(TARGET.relative_to(ROOT)))
        print("  bytes  = " + str(TARGET.stat().st_size))
        print("  lines  = " + str(len(SRC_LINES)))
        print("  sha256 = " + h.hexdigest())
        VALS["src_lines"] = len(SRC_LINES)
        VALS["src_sha256"] = h.hexdigest()
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[1] 例外で中断")

sec(2, "AST 解析と対象 def の行範囲")
try:
    if SRC_TEXT:
        TREE = ast.parse(SRC_TEXT)
        print("ast.parse = OK")

        def collect(node, stack):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    DEFS.append({
                        "name": ch.name,
                        "lineno": int(ch.lineno),
                        "end": int(getattr(ch, "end_lineno", ch.lineno) or ch.lineno),
                        "depth": len(stack),
                        "parent": stack[-1] if stack else "<module>",
                        "args": [a.arg for a in ch.args.args],
                        "kwonly": [a.arg for a in ch.args.kwonlyargs],
                    })
                    collect(ch, stack + [ch.name])
                elif isinstance(ch, ast.ClassDef):
                    collect(ch, stack + [ch.name])
                else:
                    collect(ch, stack)

        collect(TREE, [])
    print("def_count = " + str(len(DEFS)))
    VALS["def_count"] = len(DEFS)
    print("")
    print("{0:>6s} {1:>6s} {2:>5s} {3:>5s} {4:46s} {5}".format(
        "start", "end", "len", "depth", "name", "parent"))
    for nm in DUMP_FIXED:
        ds = find_defs(nm)
        if not ds:
            print("{0:>6s} {1:>6s} {2:>5s} {3:>5s} {4:46s} {5}".format(
                "-", "-", "-", "-", nm, "<NOT FOUND>"))
            continue
        for d in ds:
            print("{0:6d} {1:6d} {2:5d} {3:5d} {4:46s} {5}".format(
                d["lineno"], d["end"], d["end"] - d["lineno"] + 1,
                d["depth"], d["name"], d["parent"]))
            print("       args={0} kwonly={1}".format(str(d["args"]), str(d["kwonly"])))
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[2] 例外で中断")

sec(3, "シンボル出現位置と関連 def の自動発見")
try:
    for nm in PROBE_NAMES:
        occ = [i + 1 for i, l in enumerate(SRC_LINES) if nm in l]
        OCC[nm] = occ
        if DO_A:
            tail = " ..." if len(occ) > 14 else ""
            print("{0:38s} occ={1:3d} at={2}{3}".format(nm, len(occ), str(occ[:14]), tail))
    if DO_A:
        print("")
        print("--- 時刻正規化に関係しそうな def ---")
        for d in sorted(DEFS, key=lambda x: x["lineno"]):
            if NORM_RE.search(d["name"]):
                print("  L{0:<6d}-{1:<6d} depth={2} {3:44s} parent={4}".format(
                    d["lineno"], d["end"], d["depth"], d["name"], d["parent"]))
        print("")
        print("--- 前詰め・あふれ・リリーフ・日野に関係する def ---")
        for d in sorted(DEFS, key=lambda x: x["lineno"]):
            if WIDE_RE.search(d["name"]):
                print("  L{0:<6d}-{1:<6d} depth={2} {3:44s} parent={4}".format(
                    d["lineno"], d["end"], d["depth"], d["name"], d["parent"]))
    else:
        print("(SECTION B のため印字を省略。集計のみ実施)")
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[3] 例外で中断")

sec(4, "キーワードを含む行の全出力（日跨ぎ比較の検証用）")
try:
    if not DO_A:
        print("(SECTION B のため省略)")
    else:
        for key in LINE_KEYS:
            hits = [i for i, l in enumerate(SRC_LINES) if key in l]
            print("")
            print("--- キーワード: " + key + " (hits=" + str(len(hits)) + ") ---")
            if not hits:
                print("  <NO HIT>")
            for i in hits[:40]:
                print("  L{0} in {1}".format(i + 1, enclosing(i + 1)))
                print("  {0:6d}| {1}".format(i + 1, SRC_LINES[i]))
            if len(hits) > 40:
                print("  ... 残り {0} 件省略 ...".format(len(hits) - 40))
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[4] 例外で中断")

sec(5, "対象関数のソース全文（SECTION B のみ）")
try:
    for nm in DUMP_FIXED:
        ds = find_defs(nm)
        if not ds:
            DUMPED[nm] = ""
            if DO_B:
                print("")
                print("--- " + nm + " : <NOT FOUND> ---")
            continue
        buf = []
        for d in ds:
            if DO_B:
                print("")
                print("--- " + nm + " ---")
                print("# def L{0}-{1} depth={2} parent={3} args={4} kwonly={5}".format(
                    d["lineno"], d["end"], d["depth"], d["parent"],
                    str(d["args"]), str(d["kwonly"])))
            for i in range(d["lineno"] - 1, min(d["end"], len(SRC_LINES))):
                buf.append(SRC_LINES[i])
                if DO_B:
                    print("{0:6d}| {1}".format(i + 1, SRC_LINES[i]))
        DUMPED[nm] = "\n".join(buf)
    if not DO_B:
        print("(SECTION A のためソース全文は印字しない。内部抽出のみ実施)")
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[5] 例外で中断")

sec(6, "内容ベースの判定")
try:
    fits = DUMPED.get("_fits_idle_gap_on_main", "")
    mainfp = DUMPED.get("_try_front_pack_to_main_idle_gap", "")
    CHECKS = [
        ("FITS_HAS_FLOOR_MAP", fits, "mtn_start_floor_map"),
        ("FITS_HAS_BREAK_ADJUST", fits, "_adjust_start_for_breaks"),
        ("FITS_HAS_GAP_END", fits, "gap_end"),
        ("FITS_HAS_86400", fits, "86400"),
        ("FITS_HAS_PROC_MAIN", fits, "PROC_MAIN"),
        ("FITS_HAS_PROC_RELIEF", fits, "PROC_RELIEF"),
        ("MAINFP_HAS_HINO_GUARD", mainfp, "_hino_front_pack_allowed"),
        ("MAINFP_HAS_FITS_CALL", mainfp, "_fits_idle_gap_on_main"),
        ("MAINFP_HAS_PROC_MAIN", mainfp, "PROC_MAIN"),
        ("MAINFP_HAS_PROC_RELIEF", mainfp, "PROC_RELIEF"),
        ("MAINFP_HAS_PROC_OVERFLOW", mainfp, "PROC_OVERFLOW"),
        ("MAINFP_HAS_DIAG", mainfp, "diag"),
    ]
    for k, hay, needle in CHECKS:
        v = (needle in hay) if hay else None
        VALS[k] = v
        print("{0:28s} = {1}".format(k, str(v)))
    rfp = len(OCC.get("_try_front_pack_to_relief_idle_gap", [])) > 0
    rfits = len(OCC.get("_fits_idle_gap_on_relief", [])) > 0
    VALS["RELIEF_FP_EXISTS"] = rfp
    VALS["RELIEF_FITS_EXISTS"] = rfits
    print("{0:28s} = {1}".format("RELIEF_FP_EXISTS", str(rfp)))
    print("{0:28s} = {1}".format("RELIEF_FITS_EXISTS", str(rfits)))
    if rfp or rfits:
        flag("STOP", "リリーフ版が既に存在する（重複実装の恐れ）")
    if VALS.get("FITS_HAS_86400") is False:
        flag("FOUND", "_fits_idle_gap_on_main に 86400 の記述がない（日跨ぎ補正の有無を要確認）")
    if VALS.get("FITS_HAS_FLOOR_MAP") is False:
        flag("FOUND", "_fits_idle_gap_on_main が mtn_start_floor_map を参照していない")
except Exception:
    import traceback
    traceback.print_exc()
    flag("STOP", "[6] 例外で中断")

sec(7, "REPORT")
try:
    rows = []
    rows.append(("process_assigner.py を発見", TARGET is not None))
    rows.append(("ast.parse が成功", TREE is not None))
    rows.append(("_fits_idle_gap_on_main を抽出", bool(DUMPED.get("_fits_idle_gap_on_main"))))
    rows.append(("_try_front_pack_to_main_idle_gap を抽出",
                 bool(DUMPED.get("_try_front_pack_to_main_idle_gap"))))
    rows.append(("_hino_front_pack_allowed を抽出",
                 bool(DUMPED.get("_hino_front_pack_allowed"))))
    rows.append(("_adjust_start_for_breaks を抽出",
                 bool(DUMPED.get("_adjust_start_for_breaks"))))
    rows.append(("リリーフ版が未実装（重複なし）",
                 not (VALS.get("RELIEF_FP_EXISTS") or VALS.get("RELIEF_FITS_EXISTS"))))
    ng = 0
    print("{0:3s} {1:46s} {2}".format("#", "検証項目", "結果"))
    for i, (label, ok) in enumerate(rows):
        mark = "OK" if ok else "★NG"
        if not ok:
            ng = ng + 1
        print("{0:3d} {1:46s} {2}".format(i + 1, label, mark))
    print("")
    print("NG件数 = " + str(ng))
    print("NG一覧 = " + str([l for l, ok in rows if not ok]))
    print("")
    print("--- VALS ---")
    for k in sorted(VALS.keys()):
        print("  {0:24s} = {1}".format(k, str(VALS[k])))
    print("")
    print("--- FLAGS ---")
    if not FLAGS:
        print("  (なし)")
    for lv, msg in FLAGS:
        print("  {0:6s} {1}".format(lv, msg))
    n_stop = len([1 for lv, _ in FLAGS if lv == "STOP"])
    n_warn = len([1 for lv, _ in FLAGS if lv == "WARN"])
    n_found = len([1 for lv, _ in FLAGS if lv == "FOUND"])
    print("")
    print("ELAPSED_SECS = {0:.2f}".format(time.time() - T0))
    print("総合判定 : STOP={0} WARN={1} FOUND={2} NG={3}".format(
        n_stop, n_warn, n_found, ng))
    print("-> 次工程へ進むかは河崎の判断を待つ。")
    print("SCRIPT_VERSION = " + SCRIPT_VERSION)
    print("=== END OF SECTION " + SECTION + " ===")
except Exception:
    import traceback
    traceback.print_exc()
    print("!!! 例外で中断 !!!")
