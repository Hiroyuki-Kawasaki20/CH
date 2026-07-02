# -*- coding: utf-8 -*-
"""DataManager 表示経路メソッドの UKEIRE 分離テスト"""

import pandas as pd

from src.services.data_loader import DataManager


def _build_manager() -> DataManager:
    # KVC-B7 / KVC-B3 で同一オーダー(01)が存在するデータ
    df_shipments = pd.DataFrame(
        [
            {
                "SSYUKKA": "S1",
                "納入先コード": "100",
                "SYUKKAKOKU": "N1",
                "UKEIRE": "B7",
                "NONYUHIBIN": "01",
                "納入先": "KVC",
            },
            {
                "SSYUKKA": "S1",
                "納入先コード": "100",
                "SYUKKAKOKU": "N1",
                "UKEIRE": "B3",
                "NONYUHIBIN": "01",
                "納入先": "KVC",
            },
            {
                "SSYUKKA": "S1",
                "納入先コード": "100",
                "SYUKKAKOKU": "N1",
                "UKEIRE": "B7",
                "NONYUHIBIN": "07",
                "納入先": "KVC",
            },
            {
                "SSYUKKA": "S1",
                "納入先コード": "100",
                "SYUKKAKOKU": "N1",
                "UKEIRE": "B3",
                "NONYUHIBIN": "03",
                "納入先": "KVC",
            },
            {
                "SSYUKKA": "H1",
                "納入先コード": "200",
                "SYUKKAKOKU": "H2",
                "UKEIRE": "A",
                "NONYUHIBIN": "10",
                "納入先": "日野",
            },
        ]
    )

    df_places = pd.DataFrame(
        [
            {
                "便名": "KVC",
                "受入": "B7",
                "仕入先工区": "S1",
                "納入先コード": "100",
                "納入先工区": "N1",
            },
            {
                "便名": "KVC",
                "受入": "B3",
                "仕入先工区": "S1",
                "納入先コード": "100",
                "納入先工区": "N1",
            },
            {
                "便名": "日野",
                "受入": "A",
                "仕入先工区": "H1",
                "納入先コード": "200",
                "納入先工区": "H2",
            },
        ]
    )

    return DataManager(df_shipments=df_shipments, df_places=df_places)


def test_get_orders_for_route_splits_b7_b3_even_with_same_order_number():
    mgr = _build_manager()

    b7_orders = mgr.get_orders_for_route("KVC", ukeire="B7")
    b3_orders = mgr.get_orders_for_route("KVC", ukeire="B3")

    assert set(b7_orders) == {"01", "07"}
    assert set(b3_orders) == {"01", "03"}
    assert "03" not in b7_orders
    assert "07" not in b3_orders


def test_get_orders_for_route_receipt_keeps_ukeire_filter_on_each_step():
    mgr = _build_manager()

    b7_orders = mgr.get_orders_for_route_receipt("KVC", "B7", ukeire="B7")
    b3_orders = mgr.get_orders_for_route_receipt("KVC", "B3", ukeire="B3")

    assert set(b7_orders) == {"01", "07"}
    assert set(b3_orders) == {"01", "03"}
    assert "03" not in b7_orders
    assert "07" not in b3_orders


def test_get_receipts_for_route_and_order_are_separated_by_ukeire():
    mgr = _build_manager()

    receipts_b7 = mgr.get_receipts_for_route("KVC", ukeire="B7")
    receipts_b3 = mgr.get_receipts_for_route("KVC", ukeire="B3")

    assert receipts_b7 == ["B7"]
    assert receipts_b3 == ["B3"]

    # 同一オーダー番号(01)でも ukeire ごとに受入が分離されること
    assert mgr.get_receipts_for_route_order("KVC", "01", ukeire="B7") == ["B7"]
    assert mgr.get_receipts_for_route_order("KVC", "01", ukeire="B3") == ["B3"]


def test_non_kvc_compatibility_ukeire_none_keeps_previous_behavior():
    mgr = _build_manager()

    with_none = mgr.get_orders_for_route("日野", ukeire=None)
    without_arg = mgr.get_orders_for_route("日野")

    assert len(with_none) == len(without_arg)
    assert set(with_none) == set(without_arg)
