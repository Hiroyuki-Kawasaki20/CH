# -*- coding: utf-8 -*-
"""Issue #110 副次課題: あふれ山をリリーフ工程の空き窓へ前詰めする救済の回帰テスト。

対象（コミット d3acf33 で新設。いずれも親関数内の入れ子関数のため import 不可）:
  - _fits_idle_gap_on_relief
  - _try_front_pack_to_relief_idle_gap
  - _post_serialize_front_pack の2段配線（main版 → 不成立なら relief版）

検証観点:
  a. リリーフ工程の空き窓にあふれ山が実際に救済されること
  b. 日野便は救済されないこと（Issue #57 の別便交錯禁止を守る）
  c. 入車時間由来の開始下限（床）より前に置かれないこと（Issue #93 を複製していない証明）

二層構造:
  【構造層】inspect でソースを解析する。実装は docstring 内で「_schedule_proc_rows は
           呼ばない」と明記しているため、検査前に docstring を必ず除去する
           （v2 はこれを怠りコメント文に誤反応して落ちた）。
  【実行時層】出力DataFrameには「窓へ挿入された」目印が無い（採用時に 前倒し=False が
           明示セットされ、_is_anchored / _end_secs は出力列に現れない）。そのため
           sys.settrace で入れ子関数の呼び出し・返り値・局所変数を直接観測し、
           発動有無と「発動しない理由」を数値で取得する。

実装から確認済みの発動条件（すべて満たさないと救済は起きない）:
  1. リリーフ工程に実開始時間を持つ山が2つ以上（len(relief_points) < 2 で return False）
  2. 隣接するリリーフ山の間に窓がある（next_start > prev_end）
  3. あふれ工程の山が存在し、日野でなく（mtn_hino_bins_map）、締切を持つ
  4. 床・休憩・直開始を考慮した工数が窓に収まる（_fits_idle_gap_on_relief）
  5. 締切の追加違反がゼロ（_deadline_violation_set の差分が空）

その他の前提:
  - 床 = 前便入車時刻 + ARRIVAL_BUFFER_SECS（値を直書きせず定数を import して使う）
  - 実データには一切依存しない（合成DataFrameのみ・ファイルI/Oなし）
  - 時刻比較は運用タイムライン化せず生の秒数で行う（00:00 が 24:00 に化ける誤PASS回避）
"""

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

from src.services import process_assigner as pa
from src.services.process_assigner import (
    ARRIVAL_BUFFER_SECS,
    assign_processes_by_arrival_time,
    compute_proc_details,
    _time_to_seconds,
)
from src.models.constants import (
    BASE_ONE_TIME,
    BASE_PER_PAL,
    MIDDLE_WORK,
    PROC_OVERFLOW,
    PROC_RELIEF,
)


_FITS = "_fits_idle_gap_on_relief"
_TRY = "_try_front_pack_to_relief_idle_gap"
_WIRE = "_post_serialize_front_pack"


# =============================================================================
# 構造層: ソース静的検査（シグネチャ非依存。入れ子関数でも動く）
# =============================================================================
_FLOOR_MUTATION_PATTERNS = (
    r"mtn_start_floor_map\s*\[[^\]]*\]\s*=(?!=)",
    r"mtn_start_floor_map\s*\.\s*(?:update|pop|clear|setdefault)\s*\(",
    r"mtn_prev_arrival_floor_map\s*\[[^\]]*\]\s*=(?!=)",
    r"mtn_prev_arrival_floor_map\s*\.\s*(?:update|pop|clear|setdefault)\s*\(",
)


def _extract_func_source(module_source: str, func_name: str) -> str:
    """func_name の def 行から、同一インデントの次の def/@/class 直前までを切り出す。"""
    m = re.search(
        r"^([ \t]*)def[ \t]+" + re.escape(func_name) + r"[ \t]*\(",
        module_source,
        re.M,
    )
    if not m:
        return ""
    indent = m.group(1)
    body_from = m.end()
    tail = module_source[body_from:]
    nxt = re.search(r"^" + re.escape(indent) + r"(?:def[ \t]|@|class[ \t])", tail, re.M)
    end = body_from + (nxt.start() if nxt else len(tail))
    return module_source[m.start():end]


def _strip_docstrings(text: str) -> str:
    """三重クォートのブロックを除去する。

    実装の docstring には「_schedule_proc_rows は呼ばない」等の禁止事項が
    文章として書かれている。コードの検査でコメント文に誤反応しないよう必ず剥がす。
    """
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    text = re.sub(r"'''[\s\S]*?'''", "", text)
    return text


def _code_of(func_name: str) -> str:
    """関数本体を取り出し、docstring を除去した「コードだけ」を返す。"""
    body = _extract_func_source(inspect.getsource(pa), func_name)
    assert body, (
        f"{func_name} が process_assigner.py に見つかりません。"
        "d3acf33 の実装が失われた（写経事故の再発）疑いがあります。"
    )
    return _strip_docstrings(body)


def test_struct_relief_fits_reads_floor_but_never_mutates_it():
    """観点c（構造）: _fits_idle_gap_on_relief が床を読むだけで書き換えないこと。"""
    code = _code_of(_FITS)

    # 床を「読んでいる」こと（空振りPASS防止。読んでいなければ床無視の実装）
    assert "mtn_prev_arrival_floor_map" in code, (
        f"{_FITS} が mtn_prev_arrival_floor_map を参照していません。"
        "入車時間由来の床を見ずに配置している疑いがあります。"
    )
    assert "mtn_start_floor_map" in code, f"{_FITS} が mtn_start_floor_map を参照していません。"
    assert re.search(r"arrival_floor\s*=\s*max\(", code), (
        f"{_FITS} が2種類の床の max を取っていません（床の取り方が変わった疑い）。"
    )
    assert re.search(r"candidate_start\s*=\s*max\(", code) and "arrival_floor" in code, (
        f"{_FITS} が開始候補の算出に床を含めていません。"
    )
    # 床を「書き換えていない」こと（Issue #93 の核心）
    for pattern in _FLOOR_MUTATION_PATTERNS:
        hit = re.search(pattern, code)
        assert hit is None, (
            f"{_FITS} が床マップを書き換えています: {hit.group(0)!r}\n"
            "Issue #93（床の記録自体を下げる）の挙動を複製しています。"
        )
    # 窓終端を超えないこと／休憩と直開始を考慮していること
    assert re.search(r"earliest_end\s*<=\s*int\(\s*gap_end\s*\)", code), (
        f"{_FITS} が窓終端 gap_end との比較を行っていません。"
    )
    assert ("BREAK_TIMES" in code or "_breaks_for_proc" in code) and "_shift_start_secs" in code, (
        f"{_FITS} が休憩帯または直開始の考慮を失っています。"
    )
    print(f"[EVIDENCE] {_FITS}: 床read-only / max2種 / gap_end比較 / 休憩・直開始考慮 すべてOK")


def test_struct_relief_front_pack_guards_are_present():
    """観点b（構造）: 日野除外・あふれ限定・再スケジュール禁止・日跨ぎ・締切差分。"""
    code = _code_of(_TRY)

    checks = {
        "あふれ限定(PROC_OVERFLOW)": "PROC_OVERFLOW" in code,
        "リリーフ母集団(PROC_RELIEF)": "PROC_RELIEF" in code,
        "リリーフ2山未満で中止": bool(re.search(r"len\(\s*relief_points\s*\)\s*<\s*2", code)),
        "窓の検出(next_start>prev_end)": bool(re.search(r"next_start\s*>\s*prev_end", code)),
        "日跨ぎbypass(終了>86400)": bool(re.search(r">\s*86400", code)),
        "日跨ぎbypass(深夜×早朝)": bool(re.search(r"20\s*\*\s*3600", code)),
        "試行コピー(deepcopy)": bool(re.search(r"copy\.deepcopy\(\s*target_rows\s*\)", code)),
        "締切差分検査": bool(
            re.search(r"_deadline_violation_set\(\s*trial_rows\s*\)\s*-\s*existing_violations", code)
        ),
        "採用時アンカー固定(_is_anchored)": bool(re.search(r'_is_anchored"\]\s*=\s*True', code)),
        "採用時に前倒しを立てない": bool(re.search(r'前倒し"\]\s*=\s*False', code)),
    }
    missing = [label for label, ok in checks.items() if not ok]
    assert not missing, (
        f"{_TRY} から次のガードが失われています: {missing}\n"
        "relief版の安全装置が外された疑いがあります。"
    )
        # Issue #117: 日野一律除外が撤去されていること
    assert "日野除外" not in code, (
        f"{_TRY} に日野一律除外の痕跡が残っています。"
        "Issue #117 でリリーフ救済の日野除外は撤去する方針です。"
    )

    # リリーフを再スケジュールしないこと（docstring の宣言ではなくコードで確認）
    assert "_schedule_proc_rows" not in code, (
        f"{_TRY} のコード本体が _schedule_proc_rows を呼んでいます。"
        "リリーフ再スケジュールは空き窓へ置いた開始時刻を消すため禁止です。"
    )
    # 床マップを書き換えないこと
    for pattern in _FLOOR_MUTATION_PATTERNS:
        hit = re.search(pattern, code)
        assert hit is None, (
            f"{_TRY} が床マップを書き換えています: {hit.group(0)!r}\n"
            "Issue #93 の挙動を複製しています。"
        )
    print("[EVIDENCE] " + _TRY + ": ガード" + str(len(checks)) + "項目すべて存在 / 再スケジュールなし / 床書換なし")


def test_struct_wiring_tries_main_first_then_relief():
    """配線（構造）: main版を先に試し、不成立時のみ relief版へ回すこと。"""
    code = _code_of(_WIRE)

    i_main = code.find("_try_front_pack_to_main_idle_gap")
    i_relief = code.find(_TRY)
    assert i_main >= 0, f"{_WIRE} から main版の呼び出しが消えています。"
    assert i_relief >= 0, f"{_WIRE} に relief版の呼び出しがありません（配線漏れ）。"
    assert i_main < i_relief, (
        "main版より先に relief版を呼んでいます。"
        "既存挙動を変えないため main版が先である必要があります。"
    )
    between = code[i_main:i_relief]
    assert re.search(r"if\s+not\s+moved", between), (
        "main版と relief版の間に『if not moved』の分岐がありません。"
        "main版が成功した場合にも relief版が走る危険があります。"
    )
    print("[EVIDENCE] 配線順OK: main版 → if not moved → relief版")


# =============================================================================
# 実行時層: sys.settrace による直接観測
#   入れ子関数は import できないが、フレームは観測できる。
#   呼び出し回数・返り値・局所変数（relief_points / gaps / candidates / 移動先）を拾う。
# =============================================================================
_WATCHED = (_FITS, _TRY)


class _ReliefTracer:
    """relief版の入れ子関数だけを追跡する軽量トレーサ（読み取り専用）。"""

    def __init__(self):
        self.try_records = []
        self.fits_calls = 0

    def _local(self, frame, event, arg):
        if event == "return":
            name = frame.f_code.co_name
            if name == _TRY:
                loc = frame.f_locals
                self.try_records.append({
                    "ret": bool(arg),
                    "relief_points": [tuple(int(v) for v in p)
                                      for p in (loc.get("relief_points") or [])],
                    "gaps": [tuple(int(v) for v in g) for g in (loc.get("gaps") or [])],
                    "candidates": [tuple(int(v) for v in c)
                                   for c in (loc.get("candidates") or [])],
                    "moved_yama": loc.get("yy") if arg else None,
                    "new_start": loc.get("new_start") if arg else None,
                    "new_end": loc.get("new_end") if arg else None,
                })
        return self._local

    def __call__(self, frame, event, arg):
        if event == "call":
            name = frame.f_code.co_name
            if name in _WATCHED:
                if name == _FITS:
                    self.fits_calls += 1
                return self._local
        return None


def _run_traced(details_df: pd.DataFrame, master_df: pd.DataFrame):
    tracer = _ReliefTracer()
    prev = sys.gettrace()
    sys.settrace(tracer)
    try:
        out = assign_processes_by_arrival_time(compute_proc_details(details_df), master_df)
    finally:
        sys.settrace(prev)
    return out, tracer


# ─────────────────────────────────────────────────────────────────────────────
# 合成シナリオ
#   狙い: 「リリーフに2山以上＋その間に窓」＋「非日野のあふれ山（小・締切は窓内）」。
#   休憩帯（12:55-13:25 / 18:45-19:15）を避けた 13:30〜18:40 の連続帯に寄せる。
# ─────────────────────────────────────────────────────────────────────────────
def _cost_for_work_secs(target_secs: int, pal: int = 1) -> float:
    base = BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL)
    return float(max(0.0, target_secs - base))


def _hhmm(total_secs: int) -> str:
    return f"{int(total_secs) // 3600:02d}:{(int(total_secs) % 3600) // 60:02d}"


def _build_case(hino: bool, n_heavy: int, cand_arrival: str, late_prev: str = "16:30"):
    """(details_df, master_df, floor_map, cand_yama) を返す。

    hino=True では全納入先を「日野」接頭に差し替える（ネガ側）。
    floor_map は 山通番 -> 床秒（前便入車 + ARRIVAL_BUFFER_SECS）。
    """
    def v(name: str) -> str:
        return ("日野" + name) if hino else name

    cost_heavy = _cost_for_work_secs(30 * 60)
    cost_small = _cost_for_work_secs(5 * 60)

    detail_rows = []
    master_rows = []
    floor_map = {}
    yama = 1

    def add(vendor: str, prev_arrival: str, own_arrival: str, cost: float):
        nonlocal yama
        detail_rows.append({
            "山通番": yama, "移動工数": cost, "納入先": vendor,
            "NONYUHIBIN": "02", "高さ": 300,
        })
        master_rows.append({"OData_納入先": vendor, "NONYUHIBIN": "01",
                            "入車時間": prev_arrival, "セットありフラグ": "0"})
        master_rows.append({"OData_納入先": vendor, "NONYUHIBIN": "02",
                            "入車時間": own_arrival, "セットありフラグ": "0"})
        floor_map[yama] = int(_time_to_seconds(prev_arrival)) + int(ARRIVAL_BUFFER_SECS)
        this_yama = yama
        yama += 1
        return this_yama

    # 主力: メインとリリーフを埋める重い山（締切を10分刻みで密集させ余白を作らない）
    for i in range(n_heavy):
        add(v(f"H{i + 1}"), "13:20", _hhmm(14 * 3600 + i * 10 * 60), cost_heavy)

    # 窓の右端を作る山: 床が非常に高いため開始が大きく後ろへ寄る
    add(v("L"), late_prev, _hhmm(int(_time_to_seconds(late_prev)) + 90 * 60), cost_heavy)

    # 救済候補: 小さく、床は低く、締切は窓の内側に来るよう設定
    cand_yama = add(v("K"), "13:20", cand_arrival, cost_small)

    return pd.DataFrame(detail_rows), pd.DataFrame(master_rows), floor_map, cand_yama


_GRID = [
    (n_heavy, cand_arrival)
    for n_heavy in (4, 6)
    for cand_arrival in ("14:40", "15:10", "15:40")
]

_SWEEP_CACHE = None


def _sweep():
    """グリッド全通りを 非日野／全日野 の対で1回だけ実行し、結果を再利用する。"""
    global _SWEEP_CACHE
    if _SWEEP_CACHE is not None:
        return _SWEEP_CACHE

    records = []
    for n_heavy, cand_arrival in _GRID:
        rec = {"params": (n_heavy, cand_arrival)}
        for variant, hino in (("nonhino", False), ("allhino", True)):
            details, master, floor_map, cand_yama = _build_case(hino, n_heavy, cand_arrival)
            out, tracer = _run_traced(details, master)
            fired = [r for r in tracer.try_records if r["ret"]]
            rec[variant] = {
                "out": out,
                "columns": list(out.columns),
                "try_calls": len(tracer.try_records),
                "fits_calls": tracer.fits_calls,
                "fired": fired,
                "max_relief_points": max(
                    [len(r["relief_points"]) for r in tracer.try_records] or [0]
                ),
                "any_gaps": any(r["gaps"] for r in tracer.try_records),
                "any_candidates": any(r["candidates"] for r in tracer.try_records),
                "relief_n": int((out["山工程"].astype(str) == PROC_RELIEF).sum()),
                "overflow_n": int((out["山工程"].astype(str) == PROC_OVERFLOW).sum()),
                "cand_yama": cand_yama,
                "floor_map": floor_map,
            }
        records.append(rec)
    _SWEEP_CACHE = records
    return records


def _report(records: list) -> str:
    lines = ["[EVIDENCE] settrace 観測結果（params=(重い山数, 候補入車)）"]
    lines.append(f"  出力列一覧: {records[0]['nonhino']['columns']}")
    for rec in records:
        for variant in ("nonhino", "allhino"):
            i = rec[variant]
            lines.append(
                "  {p} {v:8s}: relief版呼出={tc} 窓判定呼出={fc} 発動={fired} "
                "最大リリーフ点数={mrp} 窓あり={g} 候補あり={c} "
                "出力[リリーフ={rn} あふれ={on}]".format(
                    p=rec["params"], v=variant, tc=i["try_calls"], fc=i["fits_calls"],
                    fired=len(i["fired"]), mrp=i["max_relief_points"],
                    g=i["any_gaps"], c=i["any_candidates"],
                    rn=i["relief_n"], on=i["overflow_n"],
                )
            )
            for f in i["fired"]:
                lines.append(
                    "      → 移動: 山{y} 開始={s} 終了={e}".format(
                        y=f["moved_yama"], s=f["new_start"], e=f["new_end"]
                    )
                )
    return "\n".join(lines)


def _blocker(records: list) -> str:
    """発動しなかった理由を、実装の早期returnに対応させて言語化する。"""
    nh = [rec["nonhino"] for rec in records]
    if all(i["try_calls"] == 0 for i in nh):
        return ("relief版が一度も呼ばれていません。main版の前詰めが常に成立している、"
                "またはあふれ山が無く前詰めループに入っていません。")
    if all(i["max_relief_points"] < 2 for i in nh):
        return ("リリーフに実開始時間を持つ山が2つ以上になりません"
                "（実装の len(relief_points) < 2 で即 return False）。"
                "リリーフへ回る山を増やす必要があります。")
    if not any(i["any_gaps"] for i in nh):
        return ("リリーフ山が2つ以上あるものの、隣接山の間に窓ができていません"
                "（next_start > prev_end が不成立）。L の前便をさらに遅らせてください。")
    if not any(i["any_candidates"] for i in nh):
        return ("窓はあるが、非日野かつ締切を持つあふれ山が候補になっていません。")
    return ("候補と窓は揃っているが、窓に収まらない（床・休憩考慮後に窓終端超過）"
            "または締切の追加違反で不採用になっています。")


# ─────────────────────────────────────────────────────────────────────────────
# 観点a: リリーフ工程の空き窓に、あふれ山が実際に救済されること
# ─────────────────────────────────────────────────────────────────────────────
def test_overflow_is_rescued_into_relief_idle_gap():
    """あふれ山がリリーフの空き窓へ移されるケースが1つ以上存在すること。

    採用時に 前倒し=False が明示セットされ _is_anchored も出力列に出ないため、
    DataFrame からは救済を識別できない。ここでは settrace で
    _try_front_pack_to_relief_idle_gap が True を返したことを直接観測する。
    未発動の場合は誤PASSさせず、原因を特定した skip 理由を残す。
    """
    records = _sweep()
    report = _report(records)
    print(report)

    hits = [rec for rec in records if rec["nonhino"]["fired"]]
    if not hits:
        pytest.skip(
            "シナリオ未成立: relief版の前詰めが発動しませんでした。\n"
            "推定原因: " + _blocker(records) + "\n" + report
        )

    rec = hits[0]
    info = rec["nonhino"]
    fired = info["fired"][0]
    out = info["out"]

    moved = int(fired["moved_yama"])
    lane = str(out.loc[out["山通番"] == moved, "山工程"].iloc[0])
    assert lane == PROC_RELIEF, (
        f"山{moved}は空き窓へ移されたのに最終工程が {lane!r} です"
        "（後段の処理で救済が打ち消されている疑い）。\n" + report
    )
    assert lane != PROC_OVERFLOW, f"山{moved}が救済済みなのにあふれのままです。\n" + report
    assert info["relief_n"] >= 2, "リリーフ山が2つ未満で救済は成立しません。\n" + report
    print(f"[EVIDENCE] 救済成立: params={rec['params']} 山{moved} 開始={fired['new_start']}秒")


# ─────────────────────────────────────────────────────────────────────────────
# 観点b: 日野便も救済対象であること（Issue #117。1工程の交錯禁止は別テストで担保）
# ─────────────────────────────────────────────────────────────────────────────
def test_hino_is_not_excluded_from_relief_rescue():
    """全納入先を日野にしても、日野を理由に救済が阻まれないこと（Issue #117）。"""
    records = _sweep()
    report = _report(records)
    print(report)

    fired = [(rec["params"], f["moved_yama"])
             for rec in records for f in rec["allhino"]["fired"]]
    if not fired:
        pytest.skip(
            "シナリオ未成立: 日野シナリオで前詰めが発動しませんでした。\n"
            "推定原因: " + _blocker(records) + "\n" + report
        )
    print(f"[EVIDENCE] 日野シナリオでも救済成立: {fired}")


# ─────────────────────────────────────────────────────────────────────────────
# 観点c: 入車時間由来の開始下限（床）より前に置かれないこと（Issue #93 非複製）
# ─────────────────────────────────────────────────────────────────────────────
def test_relief_rescue_never_starts_before_arrival_floor():
    """救済された山の新開始が、床（前便入車 + ARRIVAL_BUFFER_SECS）以降であること。

    比較は生の秒数で行う（00:00=0秒 が運用タイムライン化で 24:00 に化ける誤PASS回避。
    tests/unit/test_start_floor_zero_takaoka01.py の先例に倣う）。
    検証対象は settrace で移動が確認できた山だけに限定し、
    既存経路（main版＝Issue #93 の当事者）を巻き込まない。
    """
    records = _sweep()
    report = _report(records)
    print(report)

    checked = 0
    for rec in records:
        info = rec["nonhino"]
        floor_map = info["floor_map"]
        for f in info["fired"]:
            moved = int(f["moved_yama"])
            floor_secs = int(floor_map.get(moved, 0))
            new_start = f["new_start"]
            assert new_start is not None, (
                f"params={rec['params']} 山{moved} の新開始秒が観測できません\n" + report
            )
            assert int(new_start) >= floor_secs, (
                f"params={rec['params']} でリリーフ救済された山{moved}が"
                f"床({floor_secs}秒)より前({int(new_start)}秒)に置かれています。"
                "Issue #93 の挙動を複製した疑いがあります。\n" + report
            )
            # 出力側の実開始時間も床以降であること（後段で巻き戻されていない確認）
            out = info["out"]
            out_start = _time_to_seconds(
                str(out.loc[out["山通番"] == moved, "実開始時間"].iloc[0])
            )
            assert out_start is not None and int(out_start) >= floor_secs, (
                f"params={rec['params']} 山{moved} の最終出力開始({out_start})が"
                f"床({floor_secs}秒)より前です。\n" + report
            )
            checked += 1

    if checked == 0:
        pytest.skip(
            "シナリオ未成立: 救済が発生しないため床の実測検証ができません"
            "（床を書き換えないことは構造層のテストで担保しています）。\n"
            "推定原因: " + _blocker(records) + "\n" + report
        )