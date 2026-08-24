# -*- coding: utf-8 -*-
"""CHかんばんセット — 仕分けロジック（グループ化・混載・山統合）"""

import logging
from typing import Optional, Dict
import pandas as pd
import numpy as np

from ..models.constants import (
    DEFAULT_HEIGHT_CAP, DEFAULT_MIXING_KEY,
    SPECIAL_HINBAN, SPECIAL_HINBAN_HEIGHT_CAP,
    BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL,
    SIZE5_TYPE, SIZE5_MAX_PALLETS_PER_YAMA,
    SPLIT_UKEIRE_ROUTES, HINO_VENDOR_PREFIX,
)
from ..utils.normalizer import (
    _normalize_dest_name, _normalize_hhmm, _ZEN2HAN_DIGIT_COLON,
)
from .bin_time_rules import build_bin_time_map, attach_unit_time_bounds


logger = logging.getLogger(__name__)


DEBUG_TARGET_VENDOR = "高岡"
DEBUG_TARGET_NONYUHIBIN = "2026062503"
TAKAOKA_TARGET_UKEIRE = "K5"
# サイズ種類17は全出荷先で高さ2500まで積載可（最大3パレット）。
# 通常の高さ上限DEFAULT_HEIGHT_CAP(2450)に対する特例。
# 複数出荷先が共通でサイズ17パレットを引き取るため。2026/06 Kawasaki氏確認。
SIZE17_MERGE_HEIGHT_CAP = 2500.0
SIZE17_TYPE = "17"
MERGE_BY_ARRIVAL_VENDORS = ("KVC", "元町")


def _target_takaoka_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    idx = df.index
    vendor_src = (
        df["納入先"] if "納入先" in df.columns
        else (df["SYUKKASAKI"] if "SYUKKASAKI" in df.columns else pd.Series("", index=idx))
    )
    vendor_norm = vendor_src.astype(str).map(_normalize_dest_name)
    nony = (
        df["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
        if "NONYUHIBIN" in df.columns else pd.Series("", index=idx)
    )
    ukeire = df["UKEIRE"].astype(str).str.strip() if "UKEIRE" in df.columns else pd.Series("", index=idx)
    return (
        vendor_norm.eq(DEBUG_TARGET_VENDOR)
        & nony.eq(DEBUG_TARGET_NONYUHIBIN)
        & ukeire.eq(TAKAOKA_TARGET_UKEIRE)
    )


# ===== 入車時間列の付与 =====
def _add_arrival_time_column(df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    if master_df is None or master_df.empty:
        df["入車時間"] = ""
        return df
    master = master_df.copy()
    master["OData_納入先"] = master["OData_納入先"].astype(str).str.strip().apply(_normalize_dest_name)
    master["NONYUHIBIN"] = master["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
    master["入車時間"] = master["入車時間"].astype(str).str.strip()
    master_map = {(r["OData_納入先"], r["NONYUHIBIN"]): r["入車時間"] for _, r in master.iterrows()}

    def _lookup(row):
        vendor = _normalize_dest_name(str(row.get("納入先", row.get("SYUKKASAKI", ""))))
        # 分割対象拠点は UKEIRE を連結したマスタキーで照合する。
        if vendor in SPLIT_UKEIRE_ROUTES:
            ukeire = str(row.get("UKEIRE", "")).strip()
            if ukeire:
                vendor = f"{vendor}-{ukeire}"
        nony = str(row.get("NONYUHIBIN", "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
        order2 = nony[-2:] if len(nony) >= 2 else ""
        return master_map.get((vendor, order2), "")

    df["入車時間"] = df.apply(_lookup, axis=1)
    return df


# ===== グループ分け（上から順に積む: ファーストフィット） =====
def _normalize_hinban_text(value) -> str:
    return str(value).strip()


def assign_groups_sequential(heights: pd.Series, cap: float, max_pallets: Optional[int] = None) -> list:
    """グループを連続割当（ファーストフィット）。

    Args:
        heights: 高さのSeries
        cap: 高さ上限
        max_pallets: 1山最大パレット数。Noneなら高さのみで判定（従来動作）。

    Returns:
        グループ番号のリスト
    """
    cur_g, cur_h = 1, 0.0
    cur_pallet_count = 0  # 現在の山のパレット数
    out = []
    heights_list = heights.astype(float).to_list()

    for h in heights_list:
        # 判定: 高さ制約 AND パレット数制約
        height_ok = cur_h + h <= cap
        pallet_ok = max_pallets is None or cur_pallet_count < max_pallets

        if height_ok and pallet_ok:
            # 現在の山に追加
            out.append(cur_g)
            cur_h += h
            cur_pallet_count += 1
        else:
            # 新しい山を開始
            cur_g += 1
            cur_h = h
            cur_pallet_count = 1
            out.append(cur_g)
    return out


def _build_size1_stack_units(size1_packed: pd.DataFrame, mixing_key: str) -> pd.DataFrame:
    """サイズ1/21のローカル山から、混載判定用ユニット表を生成する。"""
    group_cols = ["NONYUHIBIN", "_role_class", "ローカルグループ番号"]
    if "納入先コード" in size1_packed.columns:
        idx = group_cols.index("_role_class")
        group_cols.insert(idx, "納入先コード")

    aggs = {
        "高さ合計": ("高さ", "sum"),
        "Max移動工数": ("移動工数", "max"),
        "_has_size1": ("_is_size1", "any"),
        "_has_size21": ("_is_size21", "any"),
        "_has_special_hinban": ("_has_special_hinban", "any"),
    }
    if mixing_key in size1_packed.columns:
        aggs[mixing_key] = (mixing_key, "first")
    aggs["納入先"] = ("納入先", "first")
    if "入車時間" in size1_packed.columns:
        aggs["入車時間"] = ("入車時間", "first")

    units = size1_packed.groupby(group_cols).agg(**aggs).reset_index()
    if units.empty:
        units["山ID"] = pd.Series(dtype=int)
        return units

    units["_has_size1"] = units["_has_size1"].astype(bool)
    units["_has_size21"] = units["_has_size21"].astype(bool)
    units["_has_special_hinban"] = units["_has_special_hinban"].astype(bool)
    units["山ID"] = np.arange(1, len(units) + 1)
    return units


def _match_units_with_layer_rules(units: pd.DataFrame, height_cap: float) -> dict:
    """層役割と既存条件で2山/3山混載を判定し、山IDの代表マップを返す。"""
    if units is None or units.empty:
        return {}

    used, id_map = set(), {}
    all_true = pd.Series(True, index=units.index)
    special_hinban_mask = units.get("_has_special_hinban", pd.Series(False, index=units.index)).astype(bool)
    has_time_cols = {"_床秒", "_締切秒"}.issubset(units.columns)

    def _time_feasible(base_floor: float, base_deadline: float, candidates: pd.DataFrame) -> pd.Series:
        if not has_time_cols:
            return pd.Series(True, index=candidates.index)
        merged_floor = np.maximum(candidates["_床秒"].astype(float), float(base_floor))
        merged_deadline = np.minimum(candidates["_締切秒"].astype(float), float(base_deadline))
        return pd.Series(merged_floor <= merged_deadline, index=candidates.index)

    def _cap_for_merge(base_has_special: bool, candidates: pd.DataFrame, normal_cap: float):
        """統合対象(g1やg1+g2)または候補が特例品番を含むならSPECIAL_HINBAN_HEIGHT_CAP、それ以外は通常capを返す（候補ごとのSeries）。"""
        combined = candidates.get("_has_special_hinban", pd.Series(False, index=candidates.index)).astype(bool) | bool(base_has_special)
        return np.where(combined, float(SPECIAL_HINBAN_HEIGHT_CAP), float(normal_cap))

    def _cross_role_allowed(base_row: pd.Series, candidate_units: pd.DataFrame) -> pd.Series:
        """base_row と candidate_units のペアが 1×21 のクロス統合として許可されるかを返す。"""
        base_has1 = bool(base_row.get("_has_size1", False))
        base_has21 = bool(base_row.get("_has_size21", False))
        base_vendor = str(base_row.get("納入先", "")).strip()
        base_bin = str(base_row.get("NONYUHIBIN", "")).strip()
        units_vendor = candidate_units["納入先"].astype(str).str.strip()
        units_bin = candidate_units["NONYUHIBIN"].astype(str).str.strip()

        cross = ((base_has1 & candidate_units["_has_size21"]) | (base_has21 & candidate_units["_has_size1"]))
        hino_both = units_vendor.str.startswith(HINO_VENDOR_PREFIX) & base_vendor.startswith(HINO_VENDOR_PREFIX)
        same_vendor_same_bin = units_vendor.eq(base_vendor) & units_bin.eq(base_bin)
        return (~cross) | (~hino_both) | same_vendor_same_bin

    def _forbidden_same_vendor_diff_bin(base_row: pd.Series) -> pd.Series:
        base_vendor = str(base_row.get("納入先", "")).strip()
        base_bin = str(base_row.get("NONYUHIBIN", "")).strip()
        base_arrival = str(base_row.get("入車時間", "")).strip()

        units_vendor = units["納入先"].astype(str).str.strip()
        units_bin = units["NONYUHIBIN"].astype(str).str.strip()
        if "入車時間" in units.columns:
            units_arrival = units["入車時間"].astype(str).str.strip()
        else:
            units_arrival = pd.Series("", index=units.index, dtype=str)

        same_vendor = units_vendor.eq(base_vendor)
        diff_bin = units_bin.ne(base_bin)

        # 例外: KVC/元町（先頭一致）かつ入車時間一致なら便違いでも混載許可
        allow_vendor = units_vendor.str.startswith(MERGE_BY_ARRIVAL_VENDORS) & bool(
            base_vendor.startswith(MERGE_BY_ARRIVAL_VENDORS)
        )
        allow_by_arrival = allow_vendor & (base_arrival != "") & units_arrival.eq(base_arrival)

        return same_vendor & diff_bin & (~allow_by_arrival)

    for _, g1 in units.sort_values("高さ合計", ascending=False).iterrows():
        id1 = int(g1["山ID"])
        if id1 in used:
            continue

        has21_g1 = bool(g1.get("_has_size21", False))
        has1_g1 = bool(g1.get("_has_size1", False))
        has_special_g1 = bool(g1.get("_has_special_hinban", False))
        margin2 = _cap_for_merge(has_special_g1, units, height_cap) - float(g1["高さ合計"])
        cond_same_dest_diff_bin = _forbidden_same_vendor_diff_bin(g1)
        cond_mix2 = ~cond_same_dest_diff_bin

        cond_layer2 = _cross_role_allowed(g1, units)
        if has21_g1:
            # 維持ルール: 特例品番631426010000はsize21山に載せない
            cond_layer2 &= ~special_hinban_mask
        if has_special_g1:
            # 維持ルール: 特例品番入り山にsize21を載せない
            cond_layer2 &= ~units["_has_size21"]
        g1_floor = float(g1["_床秒"]) if has_time_cols else 0.0
        g1_deadline = float(g1["_締切秒"]) if has_time_cols else float("inf")
        cond_mix2_final = cond_mix2 & cond_layer2 & _time_feasible(g1_floor, g1_deadline, units)

        cand2 = units[
            (~units["山ID"].isin(used))
            & (units["山ID"] != id1)
            & cond_mix2_final
            & (units["高さ合計"] <= margin2)
        ].sort_values("高さ合計", ascending=False)

        if cand2.empty:
            continue

        g2 = cand2.iloc[0]
        id2 = int(g2["山ID"])

        # 【特例品番フィルタ：層3用】g1 + g2 の統合フラグで判定
        has21_g1 = bool(g1.get("_has_size21", False))
        has21_g2 = bool(g2.get("_has_size21", False))
        has21_merged = has21_g1 | has21_g2
        
        has_special_g1 = bool(g1.get("_has_special_hinban", False))
        has_special_g2 = bool(g2.get("_has_special_hinban", False))
        has_special_merged = has_special_g1 | has_special_g2

        margin3 = _cap_for_merge(has_special_merged, units, height_cap) - float(g1["高さ合計"]) - float(g2["高さ合計"])
        cond_mix3_1 = ~_forbidden_same_vendor_diff_bin(g1)
        cond_mix3_2 = ~_forbidden_same_vendor_diff_bin(g2)

        cond_layer3 = _cross_role_allowed(g1, units) & _cross_role_allowed(g2, units)
        if has21_merged:
            cond_layer3 &= ~special_hinban_mask
        if has_special_merged:
            cond_layer3 &= ~units["_has_size21"]
        g2_floor = float(g2["_床秒"]) if has_time_cols else 0.0
        g2_deadline = float(g2["_締切秒"]) if has_time_cols else float("inf")
        cond_mix3_final = (
            cond_mix3_1 & cond_mix3_2 & cond_layer3
            & _time_feasible(max(g1_floor, g2_floor), min(g1_deadline, g2_deadline), units)
        )

        cand3 = units[
            (~units["山ID"].isin(used))
            & (~units["山ID"].isin([id1, id2]))
            & cond_mix3_final
            & (units["高さ合計"] <= margin3)
        ].sort_values("高さ合計", ascending=False)

        used.update({id1, id2})
        id_map[id2] = id1
        if not cand3.empty:
            id3 = int(cand3.iloc[0]["山ID"])
            used.add(id3)
            id_map[id3] = id1

    return id_map


# ===== メインパイプライン =====
def run_pipeline(
    data_manager,
    selections,
    height_cap,
    mixing_key,
    master_df=None,
    previous_lane_end_times: Optional[Dict[str, int]] = None,
    return_lane_end_times: bool = False,
):
    """
    仕分けパイプライン: フィルタリング→展開→グループ化→混載
    data_manager: DataManagerインスタンス
    """
    filtered = data_manager.filter_shipments(selections)

    # パレット単位に展開
    if filtered.empty:
        expanded = filtered.copy()
    else:
        counts = filtered["PLANKANBANSU"].where(filtered["PLANKANBANSU"] >= 1, 1)
        idx = np.repeat(filtered.index.to_numpy(), counts.to_numpy())
        expanded = filtered.loc[idx].reset_index(drop=True)

    # 入車時間列を付与
    expanded = _add_arrival_time_column(expanded, master_df)
    target_mask_expanded = _target_takaoka_mask(expanded)
    if target_mask_expanded.any():
        arrivals = sorted(expanded.loc[target_mask_expanded, "入車時間"].astype(str).unique().tolist()) if "入車時間" in expanded.columns else []
        sizes = sorted(expanded.loc[target_mask_expanded, "サイズ種類"].astype(str).unique().tolist()) if "サイズ種類" in expanded.columns else []
        logger.debug(
            "DEBUG 高岡2026062503/K5: _add_arrival_time_column後 入車時間=%s サイズ種類=%s 件数=%d",
            arrivals,
            sizes,
            int(target_mask_expanded.sum()),
        )

    # 基本グループ（全サイズ種類）
    group_results, group_details = {}, {}
    if not expanded.empty:
        for size_type in expanded["サイズ種類"].astype(str).unique():
            df_sub = expanded.loc[expanded["サイズ種類"].astype(str) == str(size_type)].copy()
            sort_cols = (["移動工数", "NONYUHIBIN"] if str(size_type) == "4"
                         else ["移動工数", "SYUKKASAKI"])
            sort_asc = ([False, True] if str(size_type) == "4"
                        else [False, True])
            df_sorted = df_sub.sort_values(by=sort_cols, ascending=sort_asc).copy()

            has_arrival = "入車時間" in df_sorted.columns and df_sorted["入車時間"].ne("").any()
            if has_arrival:
                group_numbers = pd.Series(0, index=df_sorted.index, dtype=int)
                base_group = 0
                for _, part in df_sorted.groupby("入車時間", sort=True):
                    target_mask_part = _target_takaoka_mask(part)
                    if target_mask_part.any():
                        hsum = pd.to_numeric(part.loc[target_mask_part, "高さ"], errors="coerce").fillna(0).sum() if "高さ" in part.columns else 0.0
                    if str(size_type) == "1":
                        part_groups = assign_groups_sequential(part["高さ"], cap=height_cap)
                    elif str(size_type) == SIZE5_TYPE:
                        part_groups = assign_groups_sequential(part["高さ"], cap=height_cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA)
                    else:
                        part_groups = assign_groups_sequential(part["高さ"], cap=height_cap)
                    group_numbers.loc[part.index] = [g + base_group for g in part_groups]
                    if part_groups:
                        base_group += max(part_groups)
                df_sorted["グループ番号"] = group_numbers.astype(int)
            else:
                if str(size_type) == "1":
                    df_sorted["グループ番号"] = assign_groups_sequential(
                        df_sorted["高さ"], cap=height_cap
                    )
                elif str(size_type) == SIZE5_TYPE:
                    df_sorted["グループ番号"] = assign_groups_sequential(
                        df_sorted["高さ"], cap=height_cap, max_pallets=SIZE5_MAX_PALLETS_PER_YAMA
                    )
                else:
                    df_sorted["グループ番号"] = assign_groups_sequential(df_sorted["高さ"], cap=height_cap)

            grp = df_sorted.groupby("グループ番号").agg(
                パレット数=("グループ番号", "count"),
                Max移動工数=("移動工数", "max"),
            ).reset_index()
            grp["引取工数"] = np.round(
                grp["Max移動工数"] + BASE_ONE_TIME + ((grp["パレット数"] - 1) * MIDDLE_WORK) + (grp["パレット数"] * BASE_PER_PAL), 0
            ).astype(int)
            group_results[str(size_type)] = grp
            group_details[str(size_type)] = df_sorted

    # 種類1/21の混載
    size1_mixed_summary, size1_mixed_details = None, None
    if not expanded.empty and expanded["サイズ種類"].astype(str).str.strip().isin(["1", "21"]).any():
        size1_mixed_summary, size1_mixed_details = _build_size1_mixed(
            expanded, height_cap, mixing_key, master_df
        )

    lane_end_times = dict(previous_lane_end_times or {})
    if return_lane_end_times:
        return (
            filtered,
            expanded,
            group_results,
            group_details,
            size1_mixed_summary,
            size1_mixed_details,
            lane_end_times,
        )

    return filtered, expanded, group_results, group_details, size1_mixed_summary, size1_mixed_details


def _build_size1_mixed(expanded, height_cap, mixing_key, master_df=None):
    """種類1/21の混載処理（1/21以外は対象外）。"""
    stype = expanded["サイズ種類"].astype(str).str.strip()
    size1_df = expanded.loc[stype.isin(["1", "21"])].copy()
    if size1_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    stype_sub = size1_df["サイズ種類"].astype(str).str.strip()
    size1_df["_is_size1"] = stype_sub.eq("1")
    size1_df["_is_size21"] = stype_sub.eq("21")
    size1_df["_role_class"] = np.where(size1_df["_is_size21"], "21", "1")

    # SPECIAL_HINBAN (631426010000) フラグを追加
    hinban_normalized = size1_df.get("HINBAN", pd.Series("", index=size1_df.index)).astype(str).str.strip()
    size1_df["_has_special_hinban"] = hinban_normalized.eq(_normalize_hinban_text(SPECIAL_HINBAN))

    if "納入先" not in size1_df.columns or not size1_df["納入先"].astype(str).str.strip().ne("").any():
        # 納入先コード → OData_納入先 → SYUKKASAKI の優先順で補完
        if "納入先コード" in size1_df.columns and size1_df["納入先コード"].astype(str).str.strip().ne("").any():
            size1_df["納入先"] = size1_df["納入先コード"].astype(str).str.strip().map(_normalize_dest_name)
        elif "OData_納入先" in size1_df.columns and size1_df["OData_納入先"].astype(str).str.strip().ne("").any():
            size1_df["納入先"] = size1_df["OData_納入先"].astype(str).str.strip().map(_normalize_dest_name)
        elif "SYUKKASAKI" in size1_df.columns:
            size1_df["納入先"] = size1_df["SYUKKASAKI"].astype(str).str.strip().map(_normalize_dest_name)
        else:
            size1_df["納入先"] = ""
    else:
        size1_df["納入先"] = size1_df["納入先"].astype(str).str.strip().map(_normalize_dest_name)
    if "NONYUHIBIN" not in size1_df.columns:
        size1_df["NONYUHIBIN"] = ""
    size1_df["NONYUHIBIN"] = size1_df["NONYUHIBIN"].astype(str).str.strip()
    if "入車時間" not in size1_df.columns:
        size1_df["入車時間"] = ""
    size1_df["入車時間"] = size1_df["入車時間"].astype(str).str.strip()

    # まずは便単位×層役割（1/21）で高さ積みしてローカル山を作る。
    local_group_cols = ["NONYUHIBIN", "_role_class"]

    packed_list = []
    for _, sub in size1_df.groupby(local_group_cols, sort=False):
        # 特例品番(SPECIAL_HINBAN)行は通常行と分けて別capで積む（山に混在すればcap=2500になるのは後段の統合判定で処理）。
        sub_special = sub[sub["_has_special_hinban"]].sort_values(by=["移動工数"], ascending=[False]).copy()
        sub_normal = sub[~sub["_has_special_hinban"]].sort_values(by=["移動工数"], ascending=[False]).copy()
        base_group = 0
        parts = []
        if not sub_special.empty:
            special_groups = assign_groups_sequential(sub_special["高さ"], cap=float(SPECIAL_HINBAN_HEIGHT_CAP))
            sub_special["ローカルグループ番号"] = [g + base_group for g in special_groups]
            parts.append(sub_special)
            base_group += max(special_groups)
        if not sub_normal.empty:
            normal_groups = assign_groups_sequential(sub_normal["高さ"], cap=height_cap)
            sub_normal["ローカルグループ番号"] = [g + base_group for g in normal_groups]
            parts.append(sub_normal)
        sub_sorted = pd.concat(parts, axis=0) if parts else sub.iloc[0:0].copy()
        packed_list.append(sub_sorted)
    size1_packed = pd.concat(packed_list, axis=0).reset_index(drop=True) if packed_list else size1_df.copy()

    group_table = _build_size1_stack_units(size1_packed, mixing_key)
    # Issue #96: マスタから床・締切を計算してユニットへ付与（混載判定の予防チェック用）
    group_table = attach_unit_time_bounds(group_table, build_bin_time_map(master_df))
    group_cols = ["NONYUHIBIN", "_role_class", "ローカルグループ番号"]
    if "納入先コード" in size1_packed.columns:
        idx = group_cols.index("_role_class")
        group_cols.insert(idx, "納入先コード")

    id_map = _match_units_with_layer_rules(group_table, float(height_cap))

    def repr_id(x: int) -> int:
        while x in id_map:
            x = id_map[x]
        return x

    group_table["代表山ID"] = group_table["山ID"].apply(repr_id)
    rep_map = {old: i + 1 for i, old in enumerate(sorted(group_table["代表山ID"].unique()))}
    group_table["山通番"] = group_table["代表山ID"].map(rep_map).astype(int)

    size1_with_mountain = size1_packed.merge(
        group_table[group_cols + ["山通番"]],
        on=group_cols, how="left"
    )

    def _timeline_secs(hhmm_text: str) -> Optional[int]:
        t = _normalize_hhmm(hhmm_text)
        if not t:
            return None
        try:
            hh, mm = t.split(":", 1)
            secs = int(hh) * 3600 + int(mm) * 60
            # 00:00〜06:24 は業務日の翌日帯へ寄せる
            if secs < (6 * 3600 + 25 * 60):
                secs += 24 * 3600
            return secs
        except Exception:
            return None

    def _rescue_split_conflict_vendor(df_with_mountain: pd.DataFrame) -> pd.DataFrame:
        if df_with_mountain.empty:
            return df_with_mountain
        if "山通番" not in df_with_mountain.columns:
            return df_with_mountain
        if "入車時間" not in df_with_mountain.columns:
            return df_with_mountain

        out = df_with_mountain.copy()
        out["納入先"] = out.get("納入先", "").astype(str).map(_normalize_dest_name)
        nony = out.get("NONYUHIBIN", "").astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
        out["_order2"] = nony.str[-2:]

        # 納入先×便の入車時刻辞書
        vendor_bin_time: Dict[tuple, Optional[int]] = {}
        for _, rr in out.iterrows():
            key = (str(rr.get("納入先", "")).strip(), str(rr.get("_order2", "")).strip())
            if key not in vendor_bin_time:
                vendor_bin_time[key] = _timeline_secs(str(rr.get("入車時間", "")).strip())

        next_yama = int(pd.to_numeric(out["山通番"], errors="coerce").fillna(0).max()) + 1
        for yama in sorted(pd.to_numeric(out["山通番"], errors="coerce").fillna(0).astype(int).unique()):
            sub_idx = out.index[pd.to_numeric(out["山通番"], errors="coerce").fillna(0).astype(int) == int(yama)]
            if len(sub_idx) <= 1:
                continue
            sub = out.loc[sub_idx]

            min_deadline = None
            max_floor = 0
            for _, rr in sub.iterrows():
                vendor = str(rr.get("納入先", "")).strip()
                order2 = str(rr.get("_order2", "")).strip()
                if not vendor or not order2:
                    continue
                pickup_secs = vendor_bin_time.get((vendor, order2))
                if pickup_secs is not None:
                    deadline = max(0, int(pickup_secs) - 10 * 60)
                    min_deadline = deadline if min_deadline is None else min(min_deadline, deadline)
                try:
                    b = int(order2)
                    if b > 1:
                        prev_key = (vendor, f"{b-1:02d}")
                        prev_secs = vendor_bin_time.get(prev_key)
                        if prev_secs is not None:
                            max_floor = max(max_floor, int(prev_secs) + 10 * 60)
                except Exception:
                    pass

            if min_deadline is None:
                continue
            if min_deadline >= max_floor:
                continue

            # 山内で最も締切が厳しい納入先を単独山へ分離して救済する。
            vendor_deadline: Dict[str, int] = {}
            for _, rr in sub.iterrows():
                vendor = str(rr.get("納入先", "")).strip()
                order2 = str(rr.get("_order2", "")).strip()
                if not vendor or not order2:
                    continue
                pickup_secs = vendor_bin_time.get((vendor, order2))
                if pickup_secs is None:
                    continue
                d = max(0, int(pickup_secs) - 10 * 60)
                if vendor not in vendor_deadline or d < vendor_deadline[vendor]:
                    vendor_deadline[vendor] = d

            if not vendor_deadline:
                continue

            target_vendor = sorted(vendor_deadline.items(), key=lambda x: (x[1], x[0]))[0][0]
            split_mask = sub["納入先"].astype(str) == str(target_vendor)
            if not split_mask.any() or split_mask.all():
                continue

            split_idx = sub.loc[split_mask].index
            out.loc[split_idx, "山通番"] = int(next_yama)
            next_yama += 1

        return out.drop(columns=["_order2"], errors="ignore")

    size1_with_mountain = _rescue_split_conflict_vendor(size1_with_mountain)
    size1_with_mountain = size1_with_mountain.drop(
        columns=["_is_size1", "_is_size21", "_role_class", "_床秒", "_締切秒"],
        errors="ignore",
    )

    size1_mixed_summary = size1_with_mountain.groupby("山通番").agg(
        パレット数=("山通番", "count"),
        Max移動工数=("移動工数", "max")
    ).reset_index()
    size1_mixed_summary["引取工数"] = np.round(
        size1_mixed_summary["Max移動工数"] + BASE_ONE_TIME +
        ((size1_mixed_summary["パレット数"] - 1) * MIDDLE_WORK) +
        (size1_mixed_summary["パレット数"] * BASE_PER_PAL), 0
    ).astype(int)

    if mixing_key in size1_with_mountain.columns:
        mix_list_map = {yama: "/".join(sorted(set(vals)))
                        for yama, vals in size1_with_mountain.groupby("山通番")[mixing_key]}
        size1_mixed_summary["混載キー一覧"] = size1_mixed_summary["山通番"].map(mix_list_map)
        size1_mixed_summary["混載キー種類数"] = size1_mixed_summary["混載キー一覧"].apply(
            lambda s: len(s.split("/")) if isinstance(s, str) and s else 0)
        size1_mixed_summary["混載フラグ"] = size1_mixed_summary["混載キー種類数"].ge(2)
    else:
        size1_mixed_summary["混載キー一覧"] = ""
        size1_mixed_summary["混載キー種類数"] = 0
        size1_mixed_summary["混載フラグ"] = False

    stack_order = size1_with_mountain["サイズ種類"].astype(str).str.strip().eq("21").astype(int)
    size1_mixed_details = (
        size1_with_mountain.assign(_stack_order=stack_order)
        .sort_values(by=["山通番", "_stack_order", "移動工数"], ascending=[True, True, False])
        .drop(columns=["_stack_order"])
    )
    return size1_mixed_summary, size1_mixed_details


def _merge_adjacent_size17_mountains(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df is None or all_df.empty:
        return all_df
    needed = {"山通番", "NONYUHIBIN", "サイズ種類", "高さ", "入車時間"}
    if not needed.issubset(set(all_df.columns)):
        return all_df

    work = all_df.copy()
    work["山通番"] = pd.to_numeric(work["山通番"], errors="coerce").fillna(0).astype(int)
    work["_nony"] = work["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
    work["_stype"] = work["サイズ種類"].astype(str).str.strip()
    work["_arrival"] = work["入車時間"].astype(str).str.strip()
    work["高さ"] = pd.to_numeric(work["高さ"], errors="coerce").fillna(0.0)

    stats = {}
    for yama, sub in work.groupby("山通番", sort=True):
        nony_set = {str(v).strip() for v in sub["_nony"].tolist() if str(v).strip()}
        arrival_set = {str(v).strip() for v in sub["_arrival"].tolist() if str(v).strip()}
        stype_set = {str(v).strip() for v in sub["_stype"].tolist() if str(v).strip()}
        stats[int(yama)] = {
            "height": float(sub["高さ"].sum()),
            "nony": (next(iter(nony_set)) if len(nony_set) == 1 else ""),
            "arrival": (next(iter(arrival_set)) if len(arrival_set) == 1 else ""),
            "stype": (next(iter(stype_set)) if len(stype_set) == 1 else ""),
            "eligible": (
                len(stype_set) == 1
                and next(iter(stype_set), "") == SIZE17_TYPE
                and len(nony_set) == 1
                and len(arrival_set) == 1
            ),
        }

    merge_map = {}
    yamas = sorted(stats.keys())
    i = 0
    while i < len(yamas) - 1:
        cur = int(yamas[i])
        nxt = int(yamas[i + 1])
        cs = stats[cur]
        ns = stats[nxt]
        can_merge = (
            cs["eligible"]
            and ns["eligible"]
            and cs["nony"]
            and cs["nony"] == ns["nony"]
            and cs["arrival"]
            and cs["arrival"] == ns["arrival"]
            and (cs["height"] + ns["height"]) <= float(SIZE17_MERGE_HEIGHT_CAP)
        )
        if can_merge:
            merge_map[nxt] = cur
            cs["height"] += ns["height"]
            stats[cur] = cs
        i += 1

    if not merge_map:
        return all_df

    logger.debug(
        "DEBUG サイズ17隣接山統合: merge_map=%s cap=%.1f",
        merge_map,
        float(SIZE17_MERGE_HEIGHT_CAP),
    )
    work["山通番"] = work["山通番"].map(lambda y: int(merge_map.get(int(y), int(y))))
    new_order = sorted(work["山通番"].unique().tolist())
    renum_map = {int(old): i + 1 for i, old in enumerate(new_order)}
    work["山通番"] = work["山通番"].map(renum_map).astype(int)

    return work.drop(columns=["_nony", "_stype", "_arrival"], errors="ignore")


# ===== 全サイズの山を統合 =====
def build_all_mountain_details(group_details: dict, size1_mixed_details: pd.DataFrame) -> pd.DataFrame:
    frames = []
    max_id = 0

    if size1_mixed_details is not None and not size1_mixed_details.empty and ("山通番" in size1_mixed_details.columns):
        df1 = size1_mixed_details.copy()
        df1["山通番"] = pd.to_numeric(df1["山通番"], errors="coerce").fillna(0).astype(int)
        max_id = int(df1["山通番"].max()) if not df1["山通番"].empty else 0
        frames.append(df1)

    next_id = max_id + 1

    def _num(v):
        try:
            return float(v)
        except Exception:
            return 0.0

    if group_details:
        for stype, det in group_details.items():
            stype_str = str(stype)
            if stype_str in ("1", "21"):
                continue
            if det is None or det.empty:
                continue
            det2 = det.copy()
            for c in ("グループ番号", "グルーピング番号", "NONYUHIBIN", "移動工数", "高さ", "納入先",
                       "サイズ種類", "ストア", "SYUKKASAKI", "UKEIRE"):
                if c not in det2.columns:
                    if c in ("納入先", "サイズ種類", "ストア", "SYUKKASAKI", "UKEIRE", "NONYUHIBIN"):
                        det2[c] = ""
                    elif c in ("移動工数", "高さ"):
                        det2[c] = np.nan
                    else:
                        det2[c] = ""
            det2["移動工数"] = pd.to_numeric(det2["移動工数"], errors="coerce")
            det2["高さ"] = pd.to_numeric(det2["高さ"], errors="coerce").fillna(0.0)

            if stype_str == "4":
                has_arrival_s4 = "入車時間" in det2.columns and det2["入車時間"].ne("").any()
                if has_arrival_s4:
                    det2 = det2.sort_values(by=["入車時間", "NONYUHIBIN", "移動工数"], ascending=[True, True, False])
                    group_key_s4 = "入車時間"
                else:
                    det2["NONYUHIBIN"] = det2["NONYUHIBIN"].astype(str).str.strip()
                    det2 = det2.sort_values(by=["NONYUHIBIN", "移動工数"], ascending=[True, False])
                    group_key_s4 = "NONYUHIBIN"
                rows = []
                cap = DEFAULT_HEIGHT_CAP
                for key_val, grp in det2.groupby(group_key_s4, sort=False):
                    current_h = 0.0
                    current_yama_id = next_id
                    for _, r in grp.iterrows():
                        h = _num(r.get("高さ", 0.0))
                        if current_h + h > cap and current_h > 0:
                            next_id += 1
                            current_yama_id = next_id
                            current_h = 0.0
                        current_h += h
                        rr = r.copy()
                        rr["山通番"] = current_yama_id
                        rows.append(rr)
                    next_id += 1
                if rows:
                    frames.append(pd.DataFrame(rows))
            else:
                col_g = ("グループ番号" if "グループ番号" in det2.columns
                         else ("グルーピング番号" if "グルーピング番号" in det2.columns else None))
                if col_g is None:
                    continue
                det2[col_g] = pd.to_numeric(det2[col_g], errors="coerce").fillna(0).astype(int)
                det2 = det2.sort_values(by=["移動工数", "納入先"], ascending=[False, True])
                rows = []
                for gno, sub in det2.groupby(col_g, sort=True):
                    sub2 = sub.copy()
                    sub2["山通番"] = next_id
                    next_id += 1
                    rows.append(sub2)
                if rows:
                    frames.append(pd.concat(rows, axis=0, ignore_index=True))

    if not frames:
        return pd.DataFrame()
    all_df = pd.concat(frames, axis=0, ignore_index=True)
    for c in ("納入先", "山通番", "移動工数", "高さ", "サイズ種類", "UKEIRE", "ストア", "NONYUHIBIN", "SYUKKASAKI", "ローカルグループ番号"):
        if c not in all_df.columns:
            if c in ("納入先", "サイズ種類", "UKEIRE", "ストア", "NONYUHIBIN", "SYUKKASAKI"):
                all_df[c] = ""
            elif c in ("移動工数", "高さ"):
                all_df[c] = np.nan
            else:
                all_df[c] = ""
    all_df["納入先"] = all_df["納入先"].astype(str).str.strip()
    all_df["サイズ種類"] = all_df["サイズ種類"].astype(str).str.strip()
    all_df["NONYUHIBIN"] = all_df["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)
    all_df = _merge_adjacent_size17_mountains(all_df)
    if "山通番" in all_df.columns and not all_df.empty:
        work = all_df.copy()
        work["山通番"] = pd.to_numeric(work["山通番"], errors="coerce").fillna(0).astype(int)
        work["NONYUHIBIN"] = work["NONYUHIBIN"].astype(str).str.strip().str.translate(_ZEN2HAN_DIGIT_COLON)

        def _order_tail_key(s: str) -> int:
            t = str(s).strip()
            if len(t) >= 2 and t[-2:].isdigit():
                return int(t[-2:])
            return 99

        def _size_key(s: str) -> tuple:
            t = str(s).strip()
            if t.isdigit():
                return (0, int(t), t)
            return (1, 999, t)

        yama_keys = {}
        for yama, sub in work.groupby("山通番", sort=False):
            tails = [_order_tail_key(v) for v in sub["NONYUHIBIN"].tolist()]
            sizes = [_size_key(v) for v in sub["サイズ種類"].tolist()]
            order_key = min(tails) if tails else 99
            size_order_key = min(sizes) if sizes else (1, 999, "")
            yama_keys[int(yama)] = (order_key, size_order_key, int(yama))

        old_yamas_sorted = sorted(yama_keys.keys(), key=lambda y: yama_keys[y])
        renum_map = {int(old): i + 1 for i, old in enumerate(old_yamas_sorted)}
        all_df["山通番"] = all_df["山通番"].map(renum_map).astype(int)

    if {"山通番", "移動工数", "サイズ種類"}.issubset(all_df.columns):
        all_df["移動工数"] = pd.to_numeric(all_df["移動工数"], errors="coerce")
        stack_order = all_df["サイズ種類"].astype(str).str.strip().eq("21").astype(int)
        all_df = (
            all_df.assign(_stack_order=stack_order)
            .sort_values(["山通番", "_stack_order", "移動工数"], ascending=[True, True, False])
            .drop(columns=["_stack_order"])
            .reset_index(drop=True)
        )
    return all_df


# ===== バッテリー交換の仮想山（特別部品） =====
def create_battery_change_mountain() -> pd.DataFrame:
    """【特別な関数】バッテリー交換の仮想山を1行作成する。
    
    ★ 重要：この関数は process_assigner を通さず、最初から「完成品」の仮想山を返す。
    
    設計の根拠：
    - バッテリー交換は「固定10分＝600秒」の作業時間を持つ
    - この値が「移動工数」から計算されるべきではなく、最初から指定される
    - scheduler.insert_virtual_mountain_into_lane() は virtual_row から
      「引取工数_秒」を直接読むため、こちらで完成品を用意する必要がある
    - 後ろの process_assigner では計算されないので、工数が消えてしまう危険がない
    
    列の説明：
    - 山通番=-1        : 仮想山の識別子（既存山は1,2,3...なので負数で区別）
    - 引取工数_秒=600  : スケジューラで使用する作業時間（秒単位）
    - 締め切り_秒=None : 「その日のうちに必ず処理」（後回しにしない）ため締切なし
    - 開始時間_秒=0    : 開始時間の下限なし
    - 納入先='〔バッテリー交換〕': UI表示用の識別子
    - その他の列       : build_all_mountain_details() の出力と同じ列構成を持つため
                        NaN/空文字で埋める（pd.concat 時に列のズレを防ぐ）
    
    Parameters
    ----------
    （なし）
    
    Returns
    -------
    pd.DataFrame
        1行の仮想山。build_all_mountain_details() の出力と同じ列構成。
    """
    # ★ スケジューラで使う必須列
    battery_row = {
        '山通番': -1,                       # 仮想山の識別子
        '引取工数_秒': 600,                 # 10分＝600秒（process_assigner 計算済み）
        '締め切り_秒': None,                # 後回しにしない仕様
        '開始時間_秒': 0,                   # 開始下限なし
        
        # ★ build_all_mountain_details() の保証列（既存山と統合するため）
        '移動工数': 0,                      # ダミー（process_assigner 非適用）
        '高さ': 0,                         # ダミー
        '納入先': '〔バッテリー交換〕',     # UI表示用
        'NONYUHIBIN': '',                 # 表示用オプション
        'UKEIRE': '',                     # 表示用オプション
        'ストア': '',                      # 表示用オプション
        'SYUKKASAKI': '',                 # 表示用オプション
        'サイズ種類': '',                  # 表示用オプション
        'ローカルグループ番号': 0,         # グループ識別子（仮想山なので0）
    }
    
    # 辞書を1行の DataFrame に変換
    return pd.DataFrame([battery_row])


# ===== 集計ユーティリティ =====
def get_dest_list_for_group(det_g: pd.DataFrame) -> list:
    if "納入先" in det_g.columns and det_g["納入先"].notna().any():
        col = "納入先"
    elif "納入先コード" in det_g.columns and det_g["納入先コード"].notna().any():
        col = "納入先コード"
    elif "SYUKKASAKI" in det_g.columns and det_g["SYUKKASAKI"].notna().any():
        col = "SYUKKASAKI"
    else:
        return []
    return sorted(set(map(str, det_g[col].tolist())))


def compute_basic_groups(group_details: dict, group_results: dict, height_cap: int) -> pd.DataFrame:
    rows = []
    if not group_details or not group_results:
        return pd.DataFrame(columns=["サイズ種類", "グループ番号", "パレット数", "Max移動工数", "引取工数", "高さ合計", "納入先一覧", "混載"])
    for stype, det in group_details.items():
        res = group_results.get(stype)
        if det is None or det.empty or res is None or res.empty:
            continue
        for _, g in res.iterrows():
            gno = g["グループ番号"]
            det_g = det.loc[det["グループ番号"] == gno]
            hsum = float(det_g["高さ"].astype(float).sum()) if "高さ" in det_g.columns else 0.0
            dests = get_dest_list_for_group(det_g)
            rows.append({
                "サイズ種類": str(stype), "グループ番号": int(gno),
                "パレット数": int(g["パレット数"]), "Max移動工数": float(g["Max移動工数"]),
                "引取工数": int(g["引取工数"]), "高さ合計": int(round(hsum)),
                "納入先一覧": "/".join(dests), "混載": "★" if len(dests) >= 2 else ""
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["サイズ種類", "グループ番号", "パレット数", "Max移動工数", "引取工数", "高さ合計", "納入先一覧", "混載"])
    return df.sort_values(by=["サイズ種類", "グループ番号"]).reset_index(drop=True)


def compute_mixed_groups(size1_mixed_summary, size1_mixed_details, height_cap: int) -> pd.DataFrame:
    if size1_mixed_summary is None or size1_mixed_details is None or size1_mixed_summary.empty or size1_mixed_details.empty:
        return pd.DataFrame(columns=["山通番", "パレット数", "Max移動工数", "引取工数", "total工数", "高さ合計", "混載キー種類数", "混載フラグ", "混載キー一覧"])
    hsum_map = (size1_mixed_details.assign(_h=size1_mixed_details["高さ"].astype(float))
                .groupby("山通番")["_h"].sum().to_dict())
    rows = []
    for _, s in size1_mixed_summary.sort_values("山通番").iterrows():
        yama = int(s["山通番"])
        hsum = float(hsum_map.get(yama, 0.0))
        max_cost = float(s["Max移動工数"])
        pick_cost = float(s["引取工数"])
        total_cost = max_cost + pick_cost
        rows.append({
            "山通番": yama, "パレット数": int(s["パレット数"]),
            "Max移動工数": max_cost, "引取工数": int(pick_cost),
            "total工数": round(total_cost, 3), "高さ合計": int(round(hsum)),
            "混載キー種類数": int(s.get("混載キー種類数", 0)),
            "混載フラグ": bool(s.get("混載フラグ", False)),
            "混載キー一覧": s.get("混載キー一覧", "")
        })
    return pd.DataFrame(rows)


def compute_dest_by_mountain(size1_mixed_details, size1_mixed_summary, height_cap: int) -> pd.DataFrame:
    if size1_mixed_summary is None or size1_mixed_details is None or size1_mixed_summary.empty or size1_mixed_details.empty:
        return pd.DataFrame(columns=["山通番", "納入先数", "納入先一覧", "パレット数", "高さ合計"])
    hsum_map = (size1_mixed_details.assign(_h=size1_mixed_details["高さ"].astype(float))
                .groupby("山通番")["_h"].sum().to_dict())
    dest_map = (size1_mixed_details.groupby("山通番")["納入先"]
                .apply(lambda s: sorted(set(map(str, s)))).to_dict())
    rows = []
    for _, s in size1_mixed_summary.iterrows():
        yama = int(s["山通番"])
        dests = dest_map.get(yama, [])
        hsum = float(hsum_map.get(yama, 0.0))
        rows.append({
            "山通番": yama, "納入先数": len(dests),
            "納入先一覧": "/".join(dests), "パレット数": int(s["パレット数"]),
            "高さ合計": int(round(hsum)),
        })
    return pd.DataFrame(rows).sort_values("山通番").reset_index(drop=True)
