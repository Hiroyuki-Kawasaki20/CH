#!/usr/bin/env python
"""Issue #119 / Patch C-1b を安全に適用するスクリプト。

対象関数のスコープ内だけを検索し、期待どおりの行が期待件数あるときだけ置換する。
1件でも不一致なら1バイトも書き換えず異常終了する。
"""
import sys
from pathlib import Path

SRC = "src/services/process_assigner.py"
TST = "tests/unit/test_relief_idle_gap_front_pack.py"
BAK_DIR = Path("scripts/tmp")

PATCHES = {
    "A": {
        "file": SRC,
        "func": "def _fits_idle_gap_on_relief(",
        "marker": "relief_breaks = _breaks_for_proc(",
        "edits": [
            {"op": "insert_before", "count": 1,
             "old": "        shift_floor = _shift_start_secs(_shift_index_for_secs(int(gap_start)))",
             "new": [
                 "        # Issue #119: リリーフは仕分け猶予20分中も引取を開始できるため、",
                 "        # 短休憩を純休憩10分として評価する(食事45分・朝一35分は不変)。",
                 "        relief_breaks = _breaks_for_proc(PROC_RELIEF)",
             ]},
            {"op": "replace", "count": 1,
             "old": "        for bs, be in BREAK_TIMES:",
             "new": ["        for bs, be in relief_breaks:"]},
            {"op": "replace", "count": 1,
             "old": "        earliest_start = _adjust_start_for_breaks(candidate_start, work_dur)",
             "new": [
                 "        earliest_start = _adjust_start_for_breaks(",
                 "            candidate_start, work_dur, break_times=relief_breaks",
                 "        )",
             ]},
            {"op": "replace", "count": 1,
             "old": "        earliest_end = _calc_work_end_with_breaks(earliest_start, work_dur)",
             "new": [
                 "        earliest_end = _calc_work_end_with_breaks(",
                 "            earliest_start, work_dur, break_times=relief_breaks",
                 "        )",
             ]},
        ],
    },
    "B": {
        "file": SRC,
        "func": "def _deadline_violation_set(",
        "marker": "break_times=_breaks_for_proc(",
        "edits": [
            {"op": "replace", "count": 1,
             "old": "            en = _calc_work_end_with_breaks(st, int(mtn_work_map.get(yy, 0)))",
             "new": [
                 "            en = _calc_work_end_with_breaks(",
                 "                st,",
                 "                int(mtn_work_map.get(yy, 0)),",
                 '                break_times=_breaks_for_proc(rr.get("山工程")),',
                 "            )",
             ]},
        ],
    },
    "C": {
        "file": SRC,
        "func": "def _serialize_lanes_final(",
        "marker": "lane_breaks = _breaks_for_proc(",
        "edits": [
            {"op": "insert_after", "count": 1,
             "old": "            lane_rows.sort(key=_op_start)",
             "new": ["            lane_breaks = _breaks_for_proc(proc_label)"]},
            {"op": "replace", "count": 1,
             "old": "                    new_start = int(_adjust_start_for_breaks(candidate, work_dur))",
             "new": [
                 "                    new_start = int(",
                 "                        _adjust_start_for_breaks(",
                 "                            candidate, work_dur, break_times=lane_breaks",
                 "                        )",
                 "                    )",
             ]},
            {"op": "replace", "count": 2,
             "old": "                    end_secs = int(_calc_work_end_with_breaks(new_start, work_dur))",
             "new": [
                 "                    end_secs = int(",
                 "                        _calc_work_end_with_breaks(",
                 "                            new_start, work_dur, break_times=lane_breaks",
                 "                        )",
                 "                    )",
             ]},
        ],
    },
    "D": {
        "file": SRC,
        "func": "def _final_score_rows(",
        "marker": "break_times=_breaks_for_proc(",
        "edits": [
            {"op": "replace", "count": 1,
             "old": "            end = _calc_work_end_with_breaks(start, int(mtn_work_map.get(yama_no, 0)))",
             "new": [
                 "            end = _calc_work_end_with_breaks(",
                 "                start,",
                 "                int(mtn_work_map.get(yama_no, 0)),",
                 '                break_times=_breaks_for_proc(row.get("山工程")),',
                 "            )",
             ]},
        ],
    },
    "T": {
        "file": TST,
        "func": None,
        "marker": '_breaks_for_proc" in code',
        "edits": [
            {"op": "subst", "count": 1,
             "old": '"BREAK_TIMES" in code',
             "new": '("BREAK_TIMES" in code or "_breaks_for_proc" in code)'},
        ],
    },
}


def die(msg):
    print("FATAL: %s" % msg)
    sys.exit(1)


def load(path):
    raw = open(path, "rb").read().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n").split("\n"), nl


def scope_of(lines, func_prefix):
    if func_prefix is None:
        return 0, len(lines)
    hits = [i for i, ln in enumerate(lines) if ln.strip().startswith(func_prefix)]
    if len(hits) != 1:
        die("関数定義 %r が %d 件(期待 1 件)" % (func_prefix, len(hits)))
    s = hits[0]
    ind = len(lines[s]) - len(lines[s].lstrip())
    # 複数行シグネチャを読み飛ばす(丸括弧が閉じて ':' で終わる行の次から本体)
    depth = 0
    body = s + 1
    for j in range(s, len(lines)):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth <= 0 and lines[j].rstrip().endswith(":"):
            body = j + 1
            break
    for j in range(body, len(lines)):
        if not lines[j].strip():
            continue
        if len(lines[j]) - len(lines[j].lstrip()) <= ind:
            return s, j
    return s, len(lines)


def find(lines, s, e, old, op):
    if op == "subst":
        return [i for i in range(s, e) if old in lines[i]]
    return [i for i in range(s, e) if lines[i] == old]


def run(name, dry):
    p = PATCHES[name]
    lines, nl = load(p["file"])
    s, e = scope_of(lines, p["func"])
    if p["marker"] in "\n".join(lines[s:e]):
        print("SKIP %s: 既に適用済み" % name)
        return 0
    plan = []
    for ed in p["edits"]:
        idx = find(lines, s, e, ed["old"], ed["op"])
        if len(idx) != ed["count"]:
            print("NG %s: %r -> %d 件(期待 %d 件)" % (name, ed["old"].strip()[:60], len(idx), ed["count"]))
            for i in range(s, e):
                if lines[i].strip() == ed["old"].strip() or ed["old"].strip() in lines[i]:
                    print("   候補 %d: %r" % (i + 1, lines[i]))
            return 1
        plan.append((ed, idx))
        print("OK %s: %-52s x%d @ %s" % (name, ed["old"].strip()[:52], len(idx), [i + 1 for i in idx]))
    if dry:
        return 0
    ops = [(i, ed) for ed, idx in plan for i in idx]
    for i, ed in sorted(ops, key=lambda t: -t[0]):
        if ed["op"] == "replace":
            lines[i:i + 1] = ed["new"]
        elif ed["op"] == "insert_before":
            lines[i:i] = ed["new"]
        elif ed["op"] == "insert_after":
            lines[i + 1:i + 1] = ed["new"]
        elif ed["op"] == "subst":
            lines[i] = lines[i].replace(ed["old"], ed["new"])
    text = nl.join(lines)
    compile(text.replace("\r\n", "\n"), p["file"], "exec")
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / (Path(p["file"]).name + ".bak_" + name)
    bak.write_bytes(open(p["file"], "rb").read())
    open(p["file"], "wb").write(text.encode("utf-8"))
    print("APPLIED %s -> %s  (backup: %s)" % (name, p["file"], bak))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or ["--check"]
    rc = 0
    if args[0] == "--check":
        for k in ("A", "B", "C", "D", "T"):
            rc |= run(k, True)
    else:
        for k in args:
            if k not in PATCHES:
                die("unknown patch: %s" % k)
            rc |= run(k, False)
    sys.exit(rc)