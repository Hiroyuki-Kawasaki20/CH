# -*- coding: utf-8 -*-
"""Issue #57: 日野別便同士の入れ込み禁止のユニットテスト

テスト対象:
  - _pick_next_main_mountain(): 日野別便の前倒し採用を禁止
  - _try_front_pack_to_main_idle_gap(): 日野別便を隣接する空き窓への差し込みを禁止
  - 非日野（武部等）の入れ込みは従来通り許可
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import pytest

from src.services.process_assigner import (
    assign_processes_by_arrival_time,
    compute_proc_details,
    _time_to_seconds,
)
from src.models.constants import PROC_MAIN, PROC_RELIEF


def _run(detail_rows: list, master_rows: list) -> pd.DataFrame:
    details = pd.DataFrame(detail_rows)
    master_df = pd.DataFrame(master_rows)
    return assign_processes_by_arrival_time(compute_proc_details(details), master_df)


def _proc(result: pd.DataFrame) -> dict:
    return {int(r["山通番"]): str(r["山工程"]) for _, r in result.iterrows()}


def _start(result: pd.DataFrame, yama: int) -> str:
    return str(result.loc[result["山通番"] == yama, "実開始時間"].iloc[0])


# ─────────────────────────────────────────────────────────────────────────────
# テスト1: 日野02 の待ち隙間に 日野03 が前倒し採用「されない」
# ─────────────────────────────────────────────────────────────────────────────
class TestHinoNoBinInterleave:
    """前倒し採用（_pick_next_main_mountain）での日野別便ガード"""

    def test_hino_different_bins_are_not_prefetched(self):
        """日野03山が、日野02山（主対象）の待ち隙間に前倒し採用されないこと。

        設定:
          山1: 日野02 (入車 10:00 → 締切 09:40)  ← 主対象山（締切最速）
          山2: 日野03 (入車 11:00 → 締切 10:40)  ← 後続便; 隙間があれば前倒し候補になりうる

        期待:
          山1 が先に処理され（前倒しなし）、山2 はその後に処理される。
          前倒し採用 is_prefetch = False であること（山順が逆転しない）。
        """
        # 山1: 日野02（締切 09:40 = 10:00 - 20min)
        # 山2: 日野03（締切 10:40 = 11:00 - 20min）
        # 日野02の前便 = 日野00（開始下限 09:10 以降 = 09:00+10min）が設定され
        # 主対象の開始下限 09:10 を待つ隙間がある間に山2の締切が余裕あり → 前倒し候補
        result = _run(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080102", "高さ": 300},
                {"山通番": 2, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080103", "高さ": 300},
            ],
            master_rows=[
                # 日野02: 入車10:00
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "09:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "10:00", "セットありフラグ": ""},
                # 日野03: 入車11:00
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "11:00", "セットありフラグ": ""},
            ],
        )
        proc = _proc(result)
        # 山1（日野02）はメインに割り当てられること
        assert proc.get(1) == PROC_MAIN, f"山1(日野02)はメインであるべき: {proc}"
        # 山2（日野03）もメインに割り当てられること（前倒し禁止でもいずれメインに来る）
        assert proc.get(2) == PROC_MAIN, f"山2(日野03)はメインであるべき: {proc}"
        # 山1 の開始時刻が山2 より早い（または同時）こと（山順が逆転しない）
        s1 = _time_to_seconds(_start(result, 1))
        s2 = _time_to_seconds(_start(result, 2))
        assert s1 is not None and s2 is not None
        assert s1 <= s2, (
            f"日野別便の前倒しにより山2({s2}秒)が山1({s1}秒)より早くなっている（禁止違反）"
        )

    def test_non_hino_can_still_be_prefetched_over_hino(self):
        """非日野（武部）山は日野山の待ち隙間に前倒し採用できること（従来動作維持）。

        設定:
          山1: 日野02 (入車 10:30 → 締切 10:10)  ← 主対象（締切最速）; 開始下限あり
          山2: 武部01 (入車 09:00 → 締切 08:40)  ← より厳しい締切
          山3: 武部02 (入車 11:00 → 締切 10:40)  ← 後続の緩い締切

        期待:
          武部01は締切が厳しく前倒し「される」か優先される
          （日野×武部の組み合わせは制限なし）
        """
        result = _run(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080102", "高さ": 300},
                {"山通番": 2, "移動工数": 0, "納入先": "武部", "NONYUHIBIN": "2026080101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "09:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "10:30", "セットありフラグ": ""},
                {"OData_納入先": "武部", "NONYUHIBIN": "01", "入車時間": "09:30", "セットありフラグ": ""},
            ],
        )
        proc = _proc(result)
        # 日野と武部はどちらもメインに割り当てられること（組み合わせに制限なし）
        assert PROC_RELIEF not in proc.values(), (
            f"日野×武部の組み合わせは制限なし、全山メインであるべき: {proc}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# テスト2: 日野02山の間のアイドル窓に日野03が前詰め「されない」
# ─────────────────────────────────────────────────────────────────────────────
class TestHinoNoFrontPackIntoIdleGap:
    """空き窓前詰め（_try_front_pack_to_main_idle_gap）での日野別便ガード"""

    def test_hino_bin03_not_packed_into_gap_between_hino_bin02_mountains(self):
        """日野03山が、日野02山の隙間に front-pack されないこと。

        設定:
          山1, 3: 日野02 (入車 10:00, 12:00)
          山2:   日野03 (入車 11:00) ← リリーフで始まる可能性がある
          山1 と 山3 の間にアイドル窓が存在する場合でも、
          山2（日野03）はその窓に差し込まれてはならない。
        """
        # 日野02が多数あり、日野03がリリーフに落ちる状況を作る
        # 山1: 日野02 (締切09:40, 開始下限09:10)
        # 山2: 日野02 (締切11:40, 開始下限11:10) → main, 山1との間に窓ができる
        # 山3: 日野03 (締切10:40, 開始下限9:10) → リリーフに落ちた場合に窓に入れようとする
        result = _run(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080102", "高さ": 300},
                {"山通番": 2, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080102", "高さ": 300},
                {"山通番": 3, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080103", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "09:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "10:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "11:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "12:00", "セットありフラグ": ""},
            ],
        )
        # 結果が得られること（クラッシュなし）
        assert result is not None and not result.empty
        proc = _proc(result)

        # 日野02と日野03が両方メインにいる場合、山3 の開始時刻が
        # 山1 と 山2 の間（= 窓の中）に入っていないことを確認
        if proc.get(3) == PROC_MAIN:
            s1 = _time_to_seconds(_start(result, 1))
            s2 = _time_to_seconds(_start(result, 2))
            s3 = _time_to_seconds(_start(result, 3))
            if s1 is not None and s2 is not None and s3 is not None:
                if s1 < s2:  # 山1, 山2 に明確な順序がある場合
                    assert not (s1 < s3 < s2), (
                        f"日野03（山3）が日野02（山1, 山2）の間の窓に差し込まれた "
                        f"[山1={s1}秒, 山3={s3}秒, 山2={s2}秒]"
                    )

    def test_non_hino_is_packed_into_gap_between_hino_mountains(self):
        """非日野（武部）山は日野山の間の空き窓に front-pack できること（従来動作維持）。

        設定:
          山1, 山2: 日野02 (入車 10:00, 12:00)  → メイン
          山3:    武部01 (入車 09:00) ← リリーフ → 日野の窓に差し込み可能
        """
        result = _run(
            detail_rows=[
                {"山通番": 1, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080102", "高さ": 300},
                {"山通番": 2, "移動工数": 0, "納入先": "日野", "NONYUHIBIN": "2026080104", "高さ": 300},
                {"山通番": 3, "移動工数": 0, "納入先": "武部", "NONYUHIBIN": "2026080101", "高さ": 300},
            ],
            master_rows=[
                {"OData_納入先": "日野", "NONYUHIBIN": "01", "入車時間": "09:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "02", "入車時間": "10:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "03", "入車時間": "11:00", "セットありフラグ": ""},
                {"OData_納入先": "日野", "NONYUHIBIN": "04", "入車時間": "12:00", "セットありフラグ": ""},
                {"OData_納入先": "武部", "NONYUHIBIN": "01", "入車時間": "09:30", "セットありフラグ": ""},
            ],
        )
        # 結果が得られること（クラッシュなし）
        assert result is not None and not result.empty
        # 武部（山3）がメインに割り当てられること（front-pack 対象）
        proc = _proc(result)
        assert proc.get(3) == PROC_MAIN, (
            f"武部（山3）は日野の窓に front-pack されるべき（メイン）: {proc}"
        )
