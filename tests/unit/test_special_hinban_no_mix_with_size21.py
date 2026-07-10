# -*- coding: utf-8 -*-
"""
631426010000（サイズ1）がサイズ21と同一山に混載されないことを検証するテスト
（Fail先行テスト：修正なしで fail、修正ありで pass）
"""

import pytest
import pandas as pd
from src.services.sorter import _build_size1_mixed
from src.models.constants import SPECIAL_HINBAN, DEFAULT_HEIGHT_CAP


def test_special_hinban_not_mixed_with_size21_in_layer3():
    """
    Layer3(3山混載)経路で、SPECIAL_HINBAN と size21 が分離されることを検証。

    データ設計:
    - g1: size21(高さ900)
    - g2: size1通常品(高さ800)
    - g3: SPECIAL_HINBAN(高さ700)

    高さ的には 900 + 800 + 700 = 2400 で3山混載が可能なため、
    Layer3フィルタが無効なら size21 と SPECIAL_HINBAN が同一山になる圧力がある。
    """
    size1_21_records = [
        {
            'HINBAN': '888888888888',
            'サイズ種類': '21',
            'NONYUHIBIN': '07',
            '納入先': '店A',
            'SYUKKASAKI': '店A',
            '高さ': 900,
            '移動工数': 1,
            'PLANKANBANSU': 1,
        },
        {
            'HINBAN': '111111111111',
            'サイズ種類': '1',
            'NONYUHIBIN': '08',
            '納入先': '店B',
            'SYUKKASAKI': '店B',
            '高さ': 800,
            '移動工数': 1,
            'PLANKANBANSU': 1,
        },
        {
            'HINBAN': SPECIAL_HINBAN,
            'サイズ種類': '1',
            'NONYUHIBIN': '09',
            '納入先': '店C',
            'SYUKKASAKI': '店C',
            '高さ': 700,
            '移動工数': 1,
            'PLANKANBANSU': 1,
        },
    ]

    expanded = pd.DataFrame(size1_21_records)

    print("\n" + "="*80)
    print("【Layer3検証 - 入力データ】")
    print("="*80)
    print(expanded[['HINBAN', 'サイズ種類', 'NONYUHIBIN', '高さ']])
    print()

    summary, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)

    print("="*80)
    print("【Layer3検証 - 出力サマリ（summary）】")
    print("="*80)
    print(summary)
    print()

    print("="*80)
    print("【Layer3検証 - 詳細データ（details）】")
    print("="*80)
    print(details[['HINBAN', 'サイズ種類', '高さ', '山通番', '_has_special_hinban']])
    print()

    groupby_yama = details.groupby('山通番').agg({
        'HINBAN': 'unique',
        '高さ': 'sum',
        'サイズ種類': 'unique',
    }).reset_index()

    print("="*80)
    print("【Layer3検証 - 山別集約】")
    print("="*80)
    print(groupby_yama)
    print()

    special_hinban_details = details[details['HINBAN'] == SPECIAL_HINBAN]
    size21_details = details[details['サイズ種類'] == '21']

    if special_hinban_details.empty or size21_details.empty:
        pytest.fail(
            f"【テストデータエラー】{SPECIAL_HINBAN} または size21 が details に見つかりません。" \
            f"special_hinban_details={len(special_hinban_details)}, size21_details={len(size21_details)}"
        )

    special_yama = special_hinban_details['山通番'].iloc[0]
    size21_yama = size21_details['山通番'].iloc[0]

    print(f"{SPECIAL_HINBAN} が属する山: {special_yama}")
    print(f"サイズ21 が属する山: {size21_yama}")
    print()

    assert special_yama != size21_yama, (
        f"【期待】Layer3経路でも {SPECIAL_HINBAN} と size21 は別山。"
        f"しかし山{special_yama}に同一混載されています。"
    )


def test_special_hinban_passes_with_filter():
    """
    【Pass確認テスト：フィルタあり（有効化）で PASS する】
    
    フィルタが有効化されている状態で、631426010000 と size21 が
    異なる山に分離されることを確認。
    
    テストデータは test_special_hinban_fails_without_filter と同じだが、
    フィルタが有効なので結果が異なる。
    """
    # テストデータ（同じ、NONYUHIBIN 統一）
    size1_21_records = [
        {'HINBAN': SPECIAL_HINBAN, 'サイズ種類': '1', 'NONYUHIBIN': '07', '納入先': '店A', 'SYUKKASAKI': '店A', '高さ': 1000, '移動工数': 1, 'PLANKANBANSU': 1},
        {'HINBAN': '888888888888', 'サイズ種類': '21', 'NONYUHIBIN': '07', '納入先': '店A', 'SYUKKASAKI': '店A', '高さ': 1400, '移動工数': 1, 'PLANKANBANSU': 1},
    ]
    
    expanded = pd.DataFrame(size1_21_records)
    
    print("\n" + "="*80)
    print("【フィルタ有効時 - 入力データ】")
    print("="*80)
    print(expanded[['HINBAN', 'サイズ種類', 'NONYUHIBIN', '高さ']])
    print()
    
    summary, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)
    
    print("="*80)
    print("【フィルタ有効時 - 出力サマリ（summary）】")
    print("="*80)
    print(summary)
    print()
    
    print("="*80)
    print("【フィルタ有効時 - 詳細データ（details）】")
    print("="*80)
    print(details[['HINBAN', 'サイズ種類', '高さ', '山通番', '_has_special_hinban']])
    print()
    
    groupby_yama = details.groupby('山通番').agg({
        'HINBAN': 'unique',
        '高さ': 'sum',
        'サイズ種類': 'unique',
    }).reset_index()
    
    print("="*80)
    print("【フィルタ有効時 - 山別集約】")
    print("="*80)
    print(groupby_yama)
    print()
    
    special_hinban_details = details[details['HINBAN'] == SPECIAL_HINBAN]
    size21_details = details[details['サイズ種類'] == '21']
    
    if special_hinban_details.empty or size21_details.empty:
        pytest.fail(
            f"【テストデータエラー】631426010000 または size21 が details に見つかりません。"
        )
    
    special_yama = special_hinban_details['山通番'].iloc[0]
    size21_yama = size21_details['山通番'].iloc[0]
    
    print(f"631426010000 が属する山: {special_yama}")
    print(f"サイズ21 が属する山: {size21_yama}")
    print()
    
    if special_yama != size21_yama:
        print(f"✓ 【分離成功】631426010000 と size21 が山{special_yama}と山{size21_yama}に分離")
        # テストが PASS する = フィルタが有効に機能
        pass
    else:
        pytest.fail(
            f"【期待：631426010000 と size21 は別山】" \
            f"しかし山{special_yama}に同一混載されています。" \
            f"フィルタが無効の可能性。"
        )


def test_special_hinban_can_mix_with_other_size1():
    """
    【後方互換性テスト】
    631426010000 以外のサイズ1品番同士は、従来通り混載できることを確認。
    """
    # サイズ1 + 1（異なる品番）、size21なし
    size1_records = [
        {'HINBAN': SPECIAL_HINBAN, 'サイズ種類': '1', 'NONYUHIBIN': '07', '納入先': '店A', 'SYUKKASAKI': '店A', '高さ': 1500, '移動工数': 1, 'PLANKANBANSU': 1},
        {'HINBAN': '111111111111', 'サイズ種類': '1', 'NONYUHIBIN': '07', '納入先': '店A', 'SYUKKASAKI': '店A', '高さ': 900, '移動工数': 1, 'PLANKANBANSU': 1},
    ]
    
    expanded = pd.DataFrame(size1_records)
    
    print("\n" + "="*80)
    print("【後方互換性テスト - 入力データ】")
    print("="*80)
    print(expanded[['HINBAN', 'サイズ種類', '高さ']])
    print()
    
    summary, details = _build_size1_mixed(expanded, DEFAULT_HEIGHT_CAP, mixing_key=None)
    
    print("="*80)
    print("【後方互換性テスト - 詳細データ（details）】")
    print("="*80)
    print(details)
    print()
    
    groupby_yama = details.groupby('山通番').agg({
        'HINBAN': 'unique',
        '高さ': 'sum',
    }).reset_index()
    
    print("="*80)
    print("【後方互換性テスト - 山別集約】")
    print("="*80)
    print(groupby_yama)
    print()
    
    # 631426010000 と 111111111111 が同一山に属しているか確認
    unique_yama_ids = details['山通番'].nunique()
    
    print(f"異なる山通番数: {unique_yama_ids}")
    print()
    
    if unique_yama_ids == 1:
        print(f"✓ 【後方互換性確認】異なるサイズ1品番同士が混載される（1つの山にまとめられている）")
        pass
    else:
        pytest.fail(
            f"【後方互換性喪失】異なるサイズ1品番同士が別山に分離されています。" \
            f"unique_yama_ids={unique_yama_ids}。631426010000 が他のsize1を除外してしまっている可能性。"
        )
