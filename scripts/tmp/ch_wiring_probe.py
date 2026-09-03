# -*- coding: utf-8 -*-
"""CH工程 呼び出し配線と既存あふれ→リリーフ処理の採取（読み取り専用）

process_assigner.py を import せず、テキスト + ast だけで抽出する。
pandas / src を一切 import しない。ファイル書き込み・git 操作を一切行わない。
各行の先頭にインデント幅を i02 形式で出力し、転記時の空白欠落を検知できるようにする。
"""
from __future__ import annotations

import ast
import hashlib
import sys
import time
from pathlib import Path

SCRIPT_VERSION = "CH-wiring-probe-1"
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
DEFS = []
FOUNDN = {}

A_TARGETS = [
    "_shift_index_for_secs",
    "_shift_start_secs",
    "_break_policy",
    "_time_to_seconds",
    "_deadline_violation_set",
    "_finalize_inspection_delay_flags",
    "_schedule_proc_rows",
]

B_TARGETS = [
    "_can_relief_at_floor",
    "_reapply_overflow_for_relief",
    "_try_repromote_overflow_to_relief",
    "_serialize_lanes_final",
    "_post_serialize_front_pack",
]

A_RANGES = [
    (690, 716, "_legacy_assign_processes_by_arrival_time のシグネチャ"),
    (2440, 2514, "ファイル末尾（公開ラッパと front_pack_diag の経路）"),
]

MAP_KEYS = [
    "mtn_work_map =",
    "mtn_deadline_map =",
    "mtn_hino_bins_map =",
    "mtn_prev_arrival_floor_map =",
    "mountain_proc_map =",
]

def sec(no, title):
    print("")
    print("=" * 78)
    print("[{0}] {1}".format(no, title))
    print("=" * 78)
    sys.stdout.flush()

SRC_LINES = []

def emit(i):
    raw = SRC_LINES[i]
    st = raw.lstrip()
    ind = len(raw) - len(st)
    print("{0:6d}|i{1:02d}| {2}".format(i + 1, ind, st))

def dump_def(name):
    ds = [d for d in DEFS if d["name"] == name]
    FOUNDN[name] = len(ds)
    if not ds:
        print("")
        print("--- " + name + " : <NOT FOUND> ---")
        return
    for d in ds:
        print("")
        print("--- {0} (L{1}-{2} depth={3} parent={4}) ---".format(
            name, d["lineno"], d["end"], d["depth"], d["parent"]))
        print("# args={0} kwonly={1} lines={2}".format(
            str(d["args"]), str(d["kwonly"]), d["end"] - d["lineno"] + 1))
        for i in range(d["lineno"] - 1, min(d["end"], len(SRC_LINES))):
            emit(i)

def dump_range(a, b, label):
    print("")
    print("--- 範囲: {0} (L{1}-{2}) ---".format(label, a, b))
    for i in range(a - 1, min(b, len(SRC_LINES))):
        emit(i)

sec(0, "実行環境")
print("SCRIPT_VERSION = " + SCRIPT_VERSION)
print("SECTION        = " + SECTION)
print("ROOT           = " + str(ROOT))
print("PYTHON         = " + sys.version.split()[0])
print("EXECUTABLE     = " + str(sys.executable))
print("NOTE           = no pandas / no src import / read-only / no file write")

TARGET = None
sec(1, "対象ファイルと SHA256 の一致確認")
EXPECT = "c6d87ec9f6d0de16c8ec5af33bf678224a8c616dc63a06139c39b09d2d00cb24"
try:
    cands = sorted(ROOT.glob("src/**/process_assigner.py"))
    if not cands:
        print("<NOT FOUND>")
    else:
        TARGET = cands[0]
        SRC_LINES = TARGET.read_text(encoding="utf-8").splitlines()
        h = hashlib.sha256()
        h.update(TARGET.read_bytes())
        got = h.hexdigest()
        print("TARGET = " + str(TARGET.relative_to(ROOT)))
        print("  lines  = " + str(len(SRC_LINES)))
        print("  sha256 = " + got)
        print("  expect = " + EXPECT)
        print("  MATCH  = " + str(got == EXPECT))
except Exception:
    import traceback
    traceback.print_exc()

sec(2, "AST 解析")
try:
    if SRC_LINES:
        tree = ast.parse("\n".join(SRC_LINES))
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

        collect(tree, [])
    print("def_count = " + str(len(DEFS)))
except Exception:
    import traceback
    traceback.print_exc()

sec(3, "SECTION A: 基盤ヘルパのソース")
try:
    if not DO_A:
        print("(SECTION B のため省略)")
    else:
        for nm in A_TARGETS:
            dump_def(nm)
except Exception:
    import traceback
    traceback.print_exc()

sec(4, "SECTION A: 指定範囲のソース")
try:
    if not DO_A:
        print("(SECTION B のため省略)")
    else:
        for a, b, label in A_RANGES:
            dump_range(a, b, label)
except Exception:
    import traceback
    traceback.print_exc()

sec(5, "SECTION A: クロージャ変数の定義行")
try:
    if not DO_A:
        print("(SECTION B のため省略)")
    else:
        for key in MAP_KEYS:
            hits = [i for i, l in enumerate(SRC_LINES) if key in l]
            print("")
            print("--- キーワード: " + key + " (hits=" + str(len(hits)) + ") ---")
            if not hits:
                print("  <NO HIT>")
            for i in hits[:10]:
                emit(i)
except Exception:
    import traceback
    traceback.print_exc()

sec(6, "SECTION B: あふれ→リリーフ処理と配線のソース")
try:
    if not DO_B:
        print("(SECTION A のため省略)")
    else:
        for nm in B_TARGETS:
            dump_def(nm)
except Exception:
    import traceback
    traceback.print_exc()

sec(7, "REPORT")
try:
    want = A_TARGETS if DO_A else B_TARGETS
    ng = 0
    print("{0:3s} {1:44s} {2}".format("#", "抽出対象", "件数"))
    for i, nm in enumerate(want):
        n = FOUNDN.get(nm, 0)
        mark = str(n) if n > 0 else "★NG(0)"
        if n == 0:
            ng = ng + 1
        print("{0:3d} {1:44s} {2}".format(i + 1, nm, mark))
    print("")
    print("NG件数 = " + str(ng))
    print("NG一覧 = " + str([nm for nm in want if FOUNDN.get(nm, 0) == 0]))
    print("")
    print("ELAPSED_SECS = {0:.2f}".format(time.time() - T0))
    print("SCRIPT_VERSION = " + SCRIPT_VERSION)
    print("=== END OF SECTION " + SECTION + " ===")
except Exception:
    import traceback
    traceback.print_exc()
    print("!!! 例外で中断 !!!")
