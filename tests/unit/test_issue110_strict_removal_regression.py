# -*- coding: utf-8 -*-
"""Issue #110 回帰テスト（strict突合の撤去とその後の是正の意図を固定する）。

固定する対象:
  1. strict 突合（SSYUKKA == 仕入先工区 ほか4条件AND）の撤去 … 案C
  2. filter_shipments の OR 合成（選択ごと独立マスク）
  3. ukeire の対称化（受入経路もオーダー経路も同じ絞り込みが効く）
  4. ukeire の表記ゆれ吸収（'6' と '06' を同値に扱う / 別値は混同しない）
  5. 出荷場一覧に未登録のペアの可視化（collect_unreachable_summary / 警告文面）

実データ（出荷情報_CH_最新版.csv・出荷場一覧.csv）は日次で複数回更新され、
マスタ未登録の組合せもあるため、実データ依存のテストは skip されて役に立たない。
このファイルは合成 DataFrame のみを使い、実データを一切参照しない。
"""

import pandas as pd

from src.services.data_loader import DataManager


# 撤去前の strict 突合が「1件も成立しない」値をあえて使う（実データと同じ構図）。
#   出荷情報   : SSYUKKA='02N' / 納入先コード='999' / SYUKKAKOKU='99'
#   出荷場一覧 : 仕入先工区='01N' / 納入先コード='111' / 納入先工区='11'
_SHIP_FIXED = {"SSYUKKA": "02N", "納入先コード": "999", "SYUKKAKOKU": "99"}
_PLACE_FIXED = {"仕入先工区": "01N", "納入先コード": "111", "納入先工区": "11"}

_SIG_COLUMNS = ["納入先", "UKEIRE", "NONYUHIBIN", "PLANKANBANSU"]


def _ship(vendor, ukeire, order, pallet):
    row = {"納入先": vendor, "UKEIRE": ukeire, "NONYUHIBIN": order, "PLANKANBANSU": pallet}
    row.update(_SHIP_FIXED)
    return row


def _place(route, receipt):
    row = {"便名": route, "受入": receipt}
    row.update(_PLACE_FIXED)
    return row


def _shipments_frame():
    # 出荷情報の UKEIRE はゼロ埋め（'06'）で、出荷場一覧の受入は非ゼロ埋め（'6'）。
    return pd.DataFrame(
        [
            _ship("日野", "06", "11", 2),
            _ship("日野", "07", "12", 3),
            _ship("KVC", "B7", "01", 1),
            _ship("KVC", "B3", "02", 5),
            _ship("KVC", "B3", "02", 5),
            _ship("織機", "21", "03", 4),
            _ship("織機", "28", "04", 6),
        ]
    )


def _places_frame():
    # KVC/B3 と 織機/21 は「あえて登録しない」= 到達不能ペア（実データと同じ構図）
    return pd.DataFrame(
        [
            _place("日野", "6"),
            _place("日野", "7"),
            _place("KVC", "B7"),
            _place("織機", "28"),
        ]
    )


def _build_manager():
    return DataManager(df_shipments=_shipments_frame(), df_places=_places_frame())


def _sig(df):
    """index の振り方に依存せず行集合を比較するための署名。"""
    if df is None or len(df) == 0:
        return []
    rows = []
    for _, row in df.iterrows():
        rows.append(tuple(str(row[col]) for col in _SIG_COLUMNS))
    return sorted(rows)


def test_mask_for_place_row_is_removed():
    """strict 突合の本体は撤去済み。復活させる改修が入ったら気付けるようにする。"""
    assert not hasattr(DataManager, "_mask_for_place_row")


def test_fixture_guarantees_strict_match_is_impossible():
    """この回帰テストの前提（strict が1件も成立しない値の組合せ）自体を固定する。"""
    ships = _shipments_frame()
    places = _places_frame()
    assert set(ships["SSYUKKA"]) & set(places["仕入先工区"]) == set()
    assert set(ships["納入先コード"]) & set(places["納入先コード"]) == set()
    assert set(ships["SYUKKAKOKU"]) & set(places["納入先工区"]) == set()


def test_receipts_and_orders_returned_even_when_strict_never_matches():
    """strict が成立しない構図でも、便名+受入の突合で選択肢が返ること（案Cの中核）。"""
    mgr = _build_manager()
    assert sorted(mgr.get_receipts_for_route("日野")) == ["6", "7"]
    assert set(mgr.get_orders_for_route("日野")) == {"11", "12"}
    assert sorted(mgr.get_receipts_for_route("KVC")) == ["B7"]


def test_ukeire_zero_padding_absorbed_on_both_sides():
    """GUI は '6'（非ゼロ埋め）を渡し、出荷情報は '06'（ゼロ埋め）を持つ。両方通ること。"""
    mgr = _build_manager()
    assert mgr.get_receipts_for_route("日野", ukeire="6") == ["6"]
    assert mgr.get_receipts_for_route("日野", ukeire="06") == ["6"]
    assert mgr.get_receipts_for_route("日野", ukeire="7") == ["7"]
    assert mgr.get_receipts_for_route("日野", ukeire="07") == ["7"]


def test_ukeire_does_not_merge_distinct_values():
    """正規化のやり過ぎで別の受入が混ざらないこと。"""
    mgr = _build_manager()
    assert set(mgr.get_orders_for_route("日野", ukeire="6")) == {"11"}
    assert set(mgr.get_orders_for_route("日野", ukeire="06")) == {"11"}
    assert set(mgr.get_orders_for_route("日野", ukeire="7")) == {"12"}
    # 英数字混在は正規化しても値が変わらないため分離が保たれる
    assert mgr.get_receipts_for_route("KVC", ukeire="B7") == ["B7"]
    assert set(mgr.get_orders_for_route("KVC", ukeire="B7")) == {"01"}


def test_ukeire_symmetry_across_display_path_methods():
    """受入経路とオーダー経路の双方に同じ ukeire 絞り込みが効くこと（対称化）。"""
    mgr = _build_manager()
    for value in ("6", "06"):
        assert mgr.get_receipts_for_route("日野", ukeire=value) == ["6"]
        assert set(mgr.get_orders_for_route("日野", ukeire=value)) == {"11"}
        assert set(mgr.get_orders_for_route_receipt("日野", "6", ukeire=value)) == {"11"}
        assert mgr.get_receipts_for_route_order("日野", "11", ukeire=value) == ["6"]


def test_unregistered_pair_has_orders_but_no_receipts():
    """出荷場一覧に無い組合せはオーダーが選べても受入が出ず、選択が完成しない。"""
    mgr = _build_manager()
    assert set(mgr.get_orders_for_route("KVC", ukeire="B3")) == {"02"}
    assert mgr.get_receipts_for_route("KVC", ukeire="B3") == []
    assert set(mgr.get_orders_for_route("織機", ukeire="21")) == {"03"}
    assert mgr.get_receipts_for_route("織機", ukeire="21") == []


def test_filter_shipments_is_or_composition_of_each_selection():
    """複数選択は「選択ごと独立マスクの OR 合成」であること。"""
    mgr = _build_manager()
    sel_hino = {"便名": "日野", "受入": "6", "オーダー": "11", "ukeire": "6"}
    sel_kvc = {"便名": "KVC", "受入": "B7", "オーダー": "01", "ukeire": "B7"}
    only_hino = mgr.filter_shipments([sel_hino])
    only_kvc = mgr.filter_shipments([sel_kvc])
    both = mgr.filter_shipments([sel_hino, sel_kvc])
    assert len(only_hino) == 1
    assert len(only_kvc) == 1
    assert _sig(both) == sorted(_sig(only_hino) + _sig(only_kvc))


def test_filter_shipments_does_not_duplicate_rows_for_same_selection():
    """OR 合成であり連結ではないこと（同じ選択を2つ渡しても行が増えない）。"""
    mgr = _build_manager()
    sel = {"便名": "日野", "受入": "6", "オーダー": "11", "ukeire": "6"}
    assert _sig(mgr.filter_shipments([sel, sel])) == _sig(mgr.filter_shipments([sel]))


def test_collect_unreachable_summary_counts_rows_and_pallets():
    """未登録ペアの行数・パレット数を (便名, 受入) 単位で集計すること。"""
    mgr = _build_manager()
    summary = mgr.collect_unreachable_summary()
    assert summary["rows"] == 3
    assert summary["pallets"] == 14
    by_ukeire = {pair["ukeire"]: (pair["rows"], pair["pallets"]) for pair in summary["pairs"]}
    assert by_ukeire == {"B3": (2, 10), "21": (1, 4)}
    for pair in summary["pairs"]:
        assert str(pair["vendor"]).strip() != ""


def test_build_unreachable_warning_message_format():
    """GUI に出す文面の形式を固定する。"""
    mgr = _build_manager()
    lines = mgr.build_unreachable_warning_message().splitlines()
    assert lines[0] == "出荷場一覧に未登録の組合せがあるため、次のデータは割り振り対象外です。"
    assert lines[-1] == "合計 3行 / 14パレット"
    assert len(lines) == 4
    body = "\n".join(lines[1:-1])
    assert "/B3 2行(10パレット)" in body
    assert "/21 1行(4パレット)" in body
    assert "B7" not in body


def test_build_unreachable_warning_message_truncates_with_max_pairs():
    """組数が上限を超えたら残数にまとめ、合計は全量を出すこと。"""
    mgr = _build_manager()
    lines = mgr.build_unreachable_warning_message(max_pairs=1).splitlines()
    assert len(lines) == 4
    assert "... 他 1 組" in lines[2]
    assert lines[-1] == "合計 3行 / 14パレット"


def test_build_unreachable_warning_message_is_empty_when_all_registered():
    """全ペアが登録済みなら警告を出さない（空文字を返す）。"""
    places = pd.DataFrame(
        [
            _place("日野", "6"),
            _place("日野", "7"),
            _place("KVC", "B7"),
            _place("KVC", "B3"),
            _place("織機", "21"),
            _place("織機", "28"),
        ]
    )
    mgr = DataManager(df_shipments=_shipments_frame(), df_places=places)
    summary = mgr.collect_unreachable_summary()
    assert summary["rows"] == 0
    assert summary["pallets"] == 0
    assert summary["pairs"] == []
    assert mgr.build_unreachable_warning_message() == ""


def test_collect_unreachable_summary_without_plankanbansu_column():
    """PLANKANBANSU 列が無くても例外にせず行数だけ数えること。"""
    ships = _shipments_frame().drop(columns=["PLANKANBANSU"])
    mgr = DataManager(df_shipments=ships, df_places=_places_frame())
    summary = mgr.collect_unreachable_summary()
    assert summary["rows"] == 3
    assert summary["pallets"] == 0
    assert mgr.build_unreachable_warning_message().endswith("合計 3行 / 0パレット")
