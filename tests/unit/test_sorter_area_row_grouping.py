"""山組みのエリア・列集約の受け入れテスト（feat/yama-area-row-grouping）。

要件: docs/要件_山組みエリア列集約.md
題材: 2026-09-30 の 18:15〜18:46 入車分 27 パレット（織機07便・日野02便・KVC 01/02便・高岡05便）。
作業者が手で組んだ山と同じ組み合わせになることを確認する。

- サイズ1/21（21パレット）: 6山（高さ合計 13,720mm ÷ 上限 2,450mm の理論最少）
- 全体（27パレット）: 9山（サイズ17 の2山・サイズ5 の1山は今のまま）

TDD fail-first: main のロジックでは サイズ1/21 が7山（全体10山）になり、
test_size1_21_matches_worker_grouping / test_yama_count_is_minimum が失敗する。
test_other_sizes_keep_current_grouping は今のままで通る（回帰防止）。
"""

import math
from collections import Counter

import pandas as pd

from src.models.constants import DEFAULT_HEIGHT_CAP
from src.services.sorter import run_pipeline


class _StubDataManager:
    def __init__(self, df):
        self._df = df

    def filter_shipments(self, selections):
        return self._df.copy()


# ---- 入車時間マスタ（関係する納入先のみ） ------------------------------------
# セットありフラグは工程の割り振りでだけ使うため、ここでは空にしている。
_ORIKI_BINS = [
    ("01", "23:35"), ("02", "01:00"), ("03", "08:30"), ("04", "10:30"),
    ("05", "12:30"), ("06", "16:00"), ("07", "18:15"), ("08", "20:35"),
]
_MASTER_ROWS = (
    [("日野", b, t) for b, t in [
        ("01", "17:00"), ("02", "18:30"), ("03", "19:27"), ("04", "21:15"),
        ("05", "22:18"), ("06", "23:50"), ("07", "01:22"), ("08", "06:29"),
        ("09", "07:55"), ("10", "09:25"), ("11", "11:06"), ("12", "12:05"),
        ("13", "13:21"), ("14", "14:15"),
    ]]
    + [(f"織機-{u}", b, t) for u in ("21", "28") for b, t in _ORIKI_BINS]
    + [("KVC-B3", b, t) for b, t in [
        ("01", "18:46"), ("02", "18:46"), ("03", "22:41"), ("04", "06:45"),
        ("05", "10:51"), ("06", "10:51"), ("07", "14:40"), ("08", "14:40"),
    ]]
    + [("KVC-B7", b, t) for b, t in [
        ("01", "18:46"), ("02", "18:46"), ("03", "22:41"), ("04", "22:41"),
        ("05", "06:45"), ("06", "06:45"), ("07", "10:51"), ("08", "10:51"),
        ("09", "14:40"), ("10", "14:40"),
    ]]
    + [("高岡", b, t) for b, t in [
        ("01", "22:41"), ("02", "06:45"), ("03", "10:51"), ("04", "14:40"),
        ("05", "18:46"),
    ]]
)


def _master():
    return pd.DataFrame([
        {"OData_納入先": v, "NONYUHIBIN": b, "入車時間": t, "セットありフラグ": ""}
        for v, b, t in _MASTER_ROWS
    ])


# ---- パレット 27 枚（高さ・サイズ種類はストアマスタより） --------------------
# (納入先, 受入, NONYUHIBIN, ストア, 背番号, 品番12桁, サイズ種類, 高さ, 移動工数)
_PALLETS = [
    ("織機", "21", "2026092907", "Q9-A-1", "715", "551124201000", "17", 830, 16.65),
    ("織機", "21", "2026092907", "Q9-A-5", "716", "551124202000", "17", 830, 16.6501),
    ("日野", "07", "2026093002", "Q10-A-24", "443", "631426010000", "1", 1000, 72.916),  # 特例品番
    ("織機", "28", "2026092907", "C15-A-3", "730", "583114214100", "1", 750, 313.7401),
    ("織機", "28", "2026092907", "C15-A-3", "730", "583114214100", "1", 750, 313.7401),
    ("日野", "07", "2026093002", "Q10-B-B", "441", "617756003000", "21", 500, 72.901),
    ("KVC", "B7", "2026100102", "L12-C-5", "719", "537214206090", "1", 515, 194.1301),
    ("KVC", "B7", "2026100102", "L12-D-8", "720", "537224207090", "1", 515, 194.1302),
    ("KVC", "B3", "2026100102", "C15-A-1", "700", "581167801100", "1", 830, 313.7402),
    ("日野", "07", "2026093002", "Q10-B-3", "439", "617756002000", "21", 500, 72.906),
    ("日野", "W5", "2026093002", "Q10-A-20", "478", "671466020000", "21", 500, 72.914),
    ("日野", "W5", "2026093002", "Q10-A-20", "478", "671466020000", "21", 500, 72.914),
    ("日野", "W5", "2026093002", "Q10-A-22", "477", "671456020000", "21", 500, 72.915),
    ("日野", "07", "2026093002", "Q10-D-25", "437", "617416014000", "1", 750, 62.1901),
    ("日野", "07", "2026093002", "Q10-B-7", "431", "616236014000", "1", 500, 72.908),
    ("日野", "06", "2026093002", "Q10-A-10", "193", "486216006000", "1", 750, 72.910),
    ("日野", "07", "2026093002", "Q10-A-27", "250", "5831160F4000", "5", 600, 72.917),
    ("日野", "07", "2026093002", "Q10-B-23", "248", "5831160F1000", "5", 600, 72.918),
    ("日野", "06", "2026093002", "Q10-A-11", "194", "486226006000", "1", 750, 72.911),
    ("日野", "06", "2026093002", "Q10-A-12", "195", "486236006000", "1", 750, 72.912),
    ("日野", "06", "2026093002", "Q10-A-13", "196", "486246006000", "1", 750, 72.913),
    ("高岡", "K5", "2026092905", "L12-C-5", "719", "537214206000", "1", 515, 194.1301),
    ("高岡", "K5", "2026092905", "C15-A-3", "730", "583114214100", "1", 750, 313.7401),
    ("高岡", "K5", "2026092905", "Q9-A-1", "715", "551124201000", "17", 830, 16.65),
    ("高岡", "K5", "2026092905", "Q9-A-1", "715", "551124201000", "17", 830, 16.65),
    ("KVC", "B7", "2026100101", "L12-D-8", "720", "537224207090", "1", 515, 194.1302),
    ("KVC", "B7", "2026100101", "C15-A-1", "700", "581167801100", "1", 830, 313.7402),
]
_SIZE, _HEIGHT = 6, 7


def _pallet_row(vendor, ukeire, nonyuhibin, store, sebango, hinban, size, height, move):
    return {
        "HINBAN": hinban,
        "サイズ種類": size,
        "NONYUHIBIN": nonyuhibin,
        "納入先": vendor,
        "SYUKKASAKI": vendor,
        "UKEIRE": ukeire,
        "ストア": store,
        "SEBANGO": sebango,
        "高さ": height,
        "移動工数": move,
        "PLANKANBANSU": 1,
    }


def _run():
    shipments = pd.DataFrame([_pallet_row(*p) for p in _PALLETS])
    _, _, _, group_details, _, size1_details = run_pipeline(
        _StubDataManager(shipments),
        selections=None,
        height_cap=DEFAULT_HEIGHT_CAP,
        mixing_key="UKEIRE",
        master_df=_master(),
    )
    return group_details, size1_details


def _pallet_key(row):
    return (
        str(row["納入先"]).strip(),
        str(row["UKEIRE"]).strip(),
        str(row["NONYUHIBIN"]).strip()[-2:],
        str(row["ストア"]).strip(),
    )


def _yamas(df, keys):
    """山ごとのパレット構成（並び替え済みタプル）を数える。"""
    if df is None or df.empty:
        return Counter()
    return Counter(
        tuple(sorted(_pallet_key(r) for _, r in g.iterrows()))
        for _, g in df.groupby(keys, sort=False, dropna=False)
    )


def _group_keys(df):
    # 入車時間ごとにグループ番号が振り直される場合でも区別できるようにする
    return ["グループ番号"] + (["入車時間"] if "入車時間" in df.columns else [])


def _other_size_yamas(group_details):
    total = Counter()
    for size, df in group_details.items():
        if str(size) in ("1", "21") or df is None or df.empty:
            continue
        total += _yamas(df, _group_keys(df))
    return total


def _fmt(sig):
    return " + ".join(f"{v}{u}-{b} {s}" for v, u, b, s in sig)


def _explain(actual, expected):
    lines = ["作業者の手組みと一致しません。"]
    lines += [f"  出なかった山: {_fmt(s)}" for s in (expected - actual).elements()]
    lines += [f"  余計な山    : {_fmt(s)}" for s in (actual - expected).elements()]
    return "\n".join(lines)


def _yama(*pallets):
    return tuple(sorted(pallets))


_EXPECTED_SIZE1_21 = Counter([
    # 余り同士をエリアまたぎでまとめる（特例品番を含むので上限2,500）
    _yama(("日野", "07", "02", "Q10-A-24"),
          ("織機", "28", "07", "C15-A-3"), ("織機", "28", "07", "C15-A-3")),
    # Q10-A 列
    _yama(("日野", "W5", "02", "Q10-A-20"), ("日野", "W5", "02", "Q10-A-20"),
          ("日野", "W5", "02", "Q10-A-22"), ("日野", "06", "02", "Q10-A-10")),
    # Q10-B 列 ＋ 余った Q10-D 列
    _yama(("日野", "07", "02", "Q10-B-B"), ("日野", "07", "02", "Q10-B-3"),
          ("日野", "07", "02", "Q10-B-7"), ("日野", "07", "02", "Q10-D-25")),
    # Q10-A 列・同じ受入（06）
    _yama(("日野", "06", "02", "Q10-A-11"), ("日野", "06", "02", "Q10-A-12"),
          ("日野", "06", "02", "Q10-A-13")),
    # L12 エリア・18:46 トラック
    _yama(("KVC", "B7", "02", "L12-C-5"), ("KVC", "B7", "02", "L12-D-8"),
          ("KVC", "B7", "01", "L12-D-8"), ("高岡", "K5", "05", "L12-C-5")),
    # C15-A 列・18:46 トラック
    _yama(("KVC", "B3", "02", "C15-A-1"), ("KVC", "B7", "01", "C15-A-1"),
          ("高岡", "K5", "05", "C15-A-3")),
])

_EXPECTED_OTHER_SIZES = Counter([
    _yama(("織機", "21", "07", "Q9-A-1"), ("織機", "21", "07", "Q9-A-5")),      # サイズ17
    _yama(("高岡", "K5", "05", "Q9-A-1"), ("高岡", "K5", "05", "Q9-A-1")),      # サイズ17
    _yama(("日野", "07", "02", "Q10-A-27"), ("日野", "07", "02", "Q10-B-23")),  # サイズ5
])


def test_size1_21_matches_worker_grouping():
    """A1: サイズ1/21 の21パレットが、作業者の手組みと同じ6山になる。"""
    _, size1_details = _run()
    actual = _yamas(size1_details, ["山通番"])
    assert actual == _EXPECTED_SIZE1_21, _explain(actual, _EXPECTED_SIZE1_21)


def test_yama_count_is_minimum():
    """A1/A2: サイズ1/21 は理論上の最少（6山）、全体は9山になる。"""
    group_details, size1_details = _run()
    total_height = sum(p[_HEIGHT] for p in _PALLETS if p[_SIZE] in ("1", "21"))
    lower_bound = math.ceil(total_height / DEFAULT_HEIGHT_CAP)
    assert total_height == 13720 and lower_bound == 6

    size1_count = size1_details["山通番"].nunique()
    other_count = sum(_other_size_yamas(group_details).values())
    assert size1_count == lower_bound
    assert size1_count + other_count == 9


def test_other_sizes_keep_current_grouping():
    """R8: サイズ17・5 の山は今のまま（回帰防止。main でも通る）。"""
    group_details, _ = _run()
    actual = _other_size_yamas(group_details)
    assert actual == _EXPECTED_OTHER_SIZES, _explain(actual, _EXPECTED_OTHER_SIZES)