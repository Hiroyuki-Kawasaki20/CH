# -*- coding: utf-8 -*-
"""CHかんばんセット — データ読み込み・前処理サービス"""

import sys
import json
import logging
import re
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np
from openpyxl import load_workbook

from ..models.constants import (
    CONFIG_FILENAME, DEFAULT_MIXING_KEY, HAISHA_VENDOR_MAP,
    BASE_ONE_TIME, MIDDLE_WORK, BASE_PER_PAL,
)
from ..utils.normalizer import (
    _normalize_dest_name, _normalize_route_name, _normalize_hhmm,
    _normalize_ukeire, _ZEN2HAN_DIGIT_COLON,
)
from ..utils.csv_utils import read_csv_ja
logger = logging.getLogger(__name__)


_SET_FLAG_TRUTHY_VALUES = {"1", "true", "t", "yes", "y", "on", "〇", "○", "有", "あり", "☑"}


def _is_truthy_set_flag(value) -> bool:
    s = str(value).strip().lower()
    return s in _SET_FLAG_TRUTHY_VALUES


def set_flag_value_to_checkbox_mark(value) -> str:
    """セットありフラグの保存値をTreeview表示用の記号へ変換する。"""
    return "☑" if _is_truthy_set_flag(value) else "☐"


def checkbox_mark_to_set_flag_value(value) -> str:
    """Treeview表示値を保存用セットありフラグへ変換する。"""
    return "1" if _is_truthy_set_flag(value) else ""


# ===== 設定ファイル管理 =====
def get_config_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / CONFIG_FILENAME
    else:
        return Path(__file__).resolve().parents[2] / "config" / CONFIG_FILENAME


def load_config() -> dict:
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config: dict):
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def select_data_folder() -> Optional[Path]:
    from tkinter import filedialog
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(
        title="データフォルダを選択してください（出荷情報_全便_最新版.csv と 出荷場一覧.csv があるフォルダ）"
    )
    root.destroy()
    if folder:
        return Path(folder)
    return None


def get_base_dir() -> Path:
    from tkinter import messagebox
    config = load_config()
    base_dir_str = config.get("base_dir")
    if base_dir_str:
        base_dir = Path(base_dir_str)
        if base_dir.exists():
            return base_dir
    messagebox.showinfo("初期設定", "データフォルダを選択してください。\n（出荷情報_CH_最新版.csv または 出荷情報_全便_最新版.csv と 出荷場一覧.csv があるフォルダ）")
    while True:
        base_dir = select_data_folder()
        if base_dir is None:
            if messagebox.askyesno("確認", "フォルダが選択されていません。終了しますか？"):
                raise SystemExit("フォルダが選択されませんでした")
            continue
        s_path_ch = base_dir / "出荷情報_CH_最新版.csv"
        s_path_all = base_dir / "出荷情報_全便_最新版.csv"
        p_path = base_dir / "出荷場一覧.csv"
        if (not s_path_ch.exists() and not s_path_all.exists()) or not p_path.exists():
            missing = []
            if not s_path_ch.exists() and not s_path_all.exists():
                missing.append("出荷情報_CH_最新版.csv / 出荷情報_全便_最新版.csv")
            if not p_path.exists():
                missing.append("出荷場一覧.csv")
            messagebox.showerror("エラー", f"必要なファイルがありません:\n{', '.join(missing)}")
            continue
        config["base_dir"] = str(base_dir)
        save_config(config)
        return base_dir


def select_export_folder() -> Optional[Path]:
    from tkinter import filedialog
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(
        title="出力先フォルダを選択してください（SPO用Excelを出力するOneDrive共有フォルダ）"
    )
    root.destroy()
    if folder:
        return Path(folder)
    return None


def get_export_dir() -> Path:
    """出力先フォルダを設定ファイルから取得。無い場合はダイアログで選択＆保存"""
    from tkinter import messagebox
    config = load_config()
    export_dir_str = config.get("export_dir")
    if export_dir_str:
        export_dir = Path(export_dir_str)
        if export_dir.exists():
            return export_dir
    messagebox.showinfo("初期設定", "出力先フォルダを選択してください。\n（SPO用Excelを出力するOneDrive共有フォルダ）")
    while True:
        export_dir = select_export_folder()
        if export_dir is None:
            if messagebox.askyesno("確認", "フォルダが選択されていません。終了しますか？"):
                raise SystemExit("出力先フォルダが選択されませんでした")
            continue
        # 出力先の場合は存在確認のみ（書き込み権限は動的にチェック可）
        if not export_dir.is_dir():
            messagebox.showerror("エラー", "指定されたパスはフォルダではありません。")
            continue
        config["export_dir"] = str(export_dir)
        save_config(config)
        return export_dir


def _resolve_shipments_path(base_dir: Path) -> Path:
    """CH版CSVを優先して出荷情報ファイルを決定する"""
    candidates = [
        base_dir / "出荷情報_CH_最新版.csv",
        base_dir / "出荷情報_全便_最新版.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"出荷情報CSVが見つかりません: {candidates[0]} または {candidates[1]}"
    )


def _supplement_sample_columns(df_shipments: pd.DataFrame, raw_move_series: Optional[pd.Series] = None) -> pd.DataFrame:
    """欠損列を補完しつつ、移動工数は入力された実値をそのまま使う。"""
    df = df_shipments.copy()

    # 元移動工数: 補完前の値を保持
    raw_move_num = None
    if raw_move_series is not None:
        raw_move_num = pd.to_numeric(raw_move_series, errors="coerce")

    if "元移動工数" not in df.columns:
        if raw_move_num is not None:
            df["元移動工数"] = raw_move_num
        elif "移動工数" in df.columns:
            df["元移動工数"] = pd.to_numeric(df["移動工数"], errors="coerce")
        else:
            df["元移動工数"] = np.nan

    # サイズ種類: 欠損時はテスト用に 1 を補完
    if "サイズ種類" not in df.columns:
        df["サイズ種類"] = "1"
    else:
        s = df["サイズ種類"].astype(str).str.strip()
        invalid = s.eq("") | s.str.lower().isin(["nan", "none"])
        df["サイズ種類"] = s.mask(invalid, "1")

    # 移動工数: サンプル補完は行わず、入力された実値のみを使用
    if "移動工数" not in df.columns:
        df["移動工数"] = np.nan
    move_num = pd.to_numeric(df["移動工数"], errors="coerce")
    if raw_move_num is not None:
        df["移動工数"] = raw_move_num.astype(float)
    else:
        df["移動工数"] = move_num.astype(float)

    # パレット数は1以上に正規化
    if "PLANKANBANSU" not in df.columns:
        df["PLANKANBANSU"] = 1
    pal = pd.to_numeric(df["PLANKANBANSU"], errors="coerce").fillna(1).clip(lower=1).astype(int)
    df["PLANKANBANSU"] = pal

    # トータル工数: 移動工数がある行のみ計算
    total_cost = np.round(
        df["移動工数"] + BASE_ONE_TIME + ((pal - 1) * MIDDLE_WORK) + (pal * BASE_PER_PAL), 0
    )
    df["トータル工数"] = pd.Series(total_cost, index=df.index)

    return df


def load_data():
    """出荷情報・出荷場一覧CSVの読込と前処理"""
    base_dir = get_base_dir()
    s_path = _resolve_shipments_path(base_dir)
    p_path = base_dir / "出荷場一覧.csv"
    if not s_path.exists() or not p_path.exists():
        raise FileNotFoundError(f"CSVが見つかりません:\n{s_path}\n{p_path}")
    df_shipments = read_csv_ja(s_path)
    df_places = read_csv_ja(p_path)
    raw_move_series = df_shipments["移動工数"].copy() if "移動工数" in df_shipments.columns else None
    # 列名前後スペース除去
    df_shipments.columns = df_shipments.columns.str.strip()
    df_places.columns = df_places.columns.str.strip()
    # 納入先コード補完
    if "納入先コード" not in df_shipments.columns and "SYUKKASAKI" in df_shipments.columns:
        df_shipments["納入先コード"] = df_shipments["SYUKKASAKI"].astype(str)
    # 数値前処理
    for num_col in ["移動工数", "高さ", "PLANKANBANSU"]:
        if num_col in df_shipments.columns:
            if num_col == "PLANKANBANSU":
                df_shipments[num_col] = pd.to_numeric(df_shipments[num_col], errors="coerce").fillna(1).astype(int)
            elif num_col == "移動工数":
                df_shipments[num_col] = pd.to_numeric(df_shipments[num_col], errors="coerce")
            else:
                df_shipments[num_col] = pd.to_numeric(df_shipments[num_col], errors="coerce").fillna(0)

    # テスト用サンプル補完（欠損時のみ）
    df_shipments = _supplement_sample_columns(df_shipments, raw_move_series=raw_move_series)
    # 文字列前処理
    for col in ["SSYUKKA", "SYUKKASAKI", "SYUKKAKOKU", "UKEIRE", "NONYUHIBIN", "サイズ種類", "納入先", "納入先コード"]:
        if col in df_shipments.columns:
            df_shipments[col] = df_shipments[col].astype(str).fillna("")
    for col in ["便名", "受入", "仕入先工区", "納入先コード", "納入先工区"]:
        if col in df_places.columns:
            df_places[col] = df_places[col].astype(str).fillna("")
    # 便名の表記ゆれ補正
    if "便名" in df_places.columns:
        df_places["便名"] = df_places["便名"].map(_normalize_route_name)
    # 出荷場一覧の必須列チェック
    required_places_cols = ["便名", "受入", "仕入先工区", "納入先コード", "納入先工区"]
    missing = [c for c in required_places_cols if c not in df_places.columns]
    if missing:
        if "納入先コード" in missing and "SYUKKASAKI" in df_places.columns:
            df_places["納入先コード"] = df_places["SYUKKASAKI"].astype(str)
            missing = [c for c in required_places_cols if c not in df_places.columns]
        if missing:
            raise ValueError(f"出荷場一覧.csv に必要な列が不足しています: {missing}")
    return df_shipments, df_places


# ===== 候補抽出ユーティリティ =====
class DataManager:
    """出荷情報・出荷場一覧を保持し、フィルタリング・候補抽出を行うクラス"""

    def __init__(self, df_shipments: pd.DataFrame, df_places: pd.DataFrame):
        self.df_shipments = df_shipments
        self.df_places = df_places

    def _fallback_vendor_series(self) -> pd.Series:
        src = self.df_shipments.get("納入先", self.df_shipments.get("SYUKKASAKI", "")).astype(str)
        return src.map(_normalize_dest_name)

    def _fallback_mask(self, route_name: str, receipt: Optional[str] = None, order: Optional[str] = None) -> pd.Series:
        route_norm = _normalize_dest_name(str(route_name))
        vendor_norm = self._fallback_vendor_series()
        mask = (vendor_norm == route_norm)
        if receipt is not None and "UKEIRE" in self.df_shipments.columns:
            shp_u = self.df_shipments["UKEIRE"].apply(_normalize_ukeire)
            mask = mask & (shp_u == _normalize_ukeire(str(receipt)))
        if order is not None and "NONYUHIBIN" in self.df_shipments.columns:
            mask = mask & (self.df_shipments["NONYUHIBIN"].astype(str).str.strip() == str(order).strip())
        return mask

    def get_routes(self) -> list:
        routes = self.df_places["便名"].astype(str).str.strip().unique().tolist()
        # CH運用では日野EH・武部は便名選択対象外
        routes = [r for r in routes if r and r not in {"日野EH", "武部"}]
        return sorted(routes)

    def _ukeire_mask(self, ukeire: Optional[str]) -> Optional[pd.Series]:
        """UKEIRE 列での絞り込みマスク。指定なし／列なしなら None を返す。

        Issue #110 CD-1: 出荷情報の UKEIRE はゼロ埋め（'06'）だが、マスタ側の受入は
        非ゼロ埋め（'6'）という表記ゆれがある。GUI が渡す ukeire は
        gui.refresh_routes() が入車時間マスタ（入車時間マスタ.xlsx の OData_納入先、
        例 '日野-6'）の行名から切り出した値であり、出荷場一覧の受入列（同じく '6'）も
        非ゼロ埋めのため、生文字列比較では日野便が必ず空になる
        （実測: get_receipts_for_route("日野", ukeire="6") -> []）。
        _fallback_mask と同様に両側を _normalize_ukeire で正規化して比較する。
        英数字混在（'B7' 等）は正規化しても値が変わらないため分離は保たれる。
        """
        if not ukeire:
            return None
        if "UKEIRE" not in self.df_shipments.columns:
            return None
        target = _normalize_ukeire(str(ukeire))
        return self.df_shipments["UKEIRE"].apply(_normalize_ukeire) == target

    def _match_mask(
        self,
        route_name: str,
        receipt: Optional[str] = None,
        order: Optional[str] = None,
        ukeire: Optional[str] = None,
    ) -> pd.Series:
        """便名（＋受入・オーダー・UKEIRE）に対応する出荷情報のマスクを生成する。

        Issue #110: 出荷場一覧との厳密突合（strict）は撤去済み。
        """
        mask = self._fallback_mask(route_name, receipt=receipt, order=order)
        um = self._ukeire_mask(ukeire)
        if um is not None:
            mask = mask & um
        return mask

    def get_receipts_for_route(self, route_name: str, ukeire: Optional[str] = None) -> list:
        ps = self.df_places[self.df_places["便名"] == route_name]
        receipts = ps["受入"].unique().tolist()
        if self._ukeire_mask(ukeire) is None:
            return sorted(receipts)
        # Issue #110: 旧実装は strict 突合のみで fallback が無く、常に空リストを返していた
        filtered_receipts = set()
        for receipt in receipts:
            if self._match_mask(route_name, receipt=receipt, ukeire=ukeire).sum() > 0:
                filtered_receipts.add(receipt)
        return sorted(filtered_receipts)

    def get_orders_for_route(self, route_name: str, ukeire: Optional[str] = None) -> list:
        m = self._match_mask(route_name, ukeire=ukeire)
        if m.sum() == 0:
            return []
        orders = self.df_shipments.loc[m, "NONYUHIBIN"].astype(str).unique().tolist()
        return sorted(orders, reverse=True)

    def get_orders_for_route_receipt(self, route_name: str, receipt: str, ukeire: Optional[str] = None) -> list:
        m = self._match_mask(route_name, receipt=receipt, ukeire=ukeire)
        if m.sum() == 0:
            return []
        orders = self.df_shipments.loc[m, "NONYUHIBIN"].astype(str).unique().tolist()
        return sorted(orders, reverse=True)

    def get_receipts_for_route_order(self, route_name: str, order: str, ukeire: Optional[str] = None) -> list:
        ps = self.df_places[self.df_places["便名"] == route_name]
        receipts = set()
        for _, row in ps.iterrows():
            m = self._match_mask(route_name, receipt=row["受入"], order=order, ukeire=ukeire)
            if m.sum() > 0:
                receipts.add(row["受入"])
        # Issue #110: 旧実装は fallback 経路のみ UKEIRE 列の値を返しており値域が不整合だった
        return sorted(receipts)

    def filter_shipments(self, selections: list) -> pd.DataFrame:
        """selections: list of {"便名","受入","オーダー"[,"ukeire"]}"""

        final_mask = None
        for sel in selections:
            m = self._match_mask(
                sel["便名"],
                receipt=sel.get("受入"),
                order=sel.get("オーダー"),
                ukeire=sel.get("ukeire"),
            )
            final_mask = m if final_mask is None else (final_mask | m)
        if final_mask is None:
            return pd.DataFrame()
        return self.df_shipments.loc[final_mask].copy()

    def collect_unreachable_summary(self) -> dict:
        """出荷場一覧に (便名, 受入) 行が無く、どの選択でも割り振れない出荷行を集計する。

        Issue #110 CD-2: strict 撤去後の突合は出荷場一覧の (便名, 受入) に依存する。
        該当行が無い組合せは get_receipts_for_route が空を返すため、オーダーは選べても
        選択が完成せず、無言で割り振り対象外になる
        （実測: KVC/B3 37行/37パレット・織機/21 48行/53パレット = 計 85行/90パレット）。
        判定は既存の _fallback_mask / _ukeire_mask を再利用し、突合ロジックを二重実装しない。
        戻り値: {"rows": int, "pallets": int,
                 "pairs": [{"vendor": str, "ukeire": str, "rows": int, "pallets": int}, ...]}
        """
        empty = {"rows": 0, "pallets": 0, "pairs": []}
        if self.df_shipments is None or len(self.df_shipments) == 0:
            return empty
        if self.df_places is None or len(self.df_places) == 0:
            return empty
        if "便名" not in self.df_places.columns or "受入" not in self.df_places.columns:
            return empty

        reach = pd.Series(False, index=self.df_shipments.index)
        for _, place_row in self.df_places.iterrows():
            mask = self._fallback_mask(str(place_row["便名"]))
            ukeire_mask = self._ukeire_mask(str(place_row["受入"]))
            if ukeire_mask is not None:
                mask = mask & ukeire_mask
            reach = reach | mask
        miss = ~reach
        if not bool(miss.any()):
            return empty

        if "PLANKANBANSU" in self.df_shipments.columns:
            pallet = pd.to_numeric(self.df_shipments["PLANKANBANSU"], errors="coerce").fillna(0).astype(int)
        else:
            pallet = pd.Series([0] * len(self.df_shipments), index=self.df_shipments.index)
        if "UKEIRE" in self.df_shipments.columns:
            ukeire_label = self.df_shipments["UKEIRE"].astype(str)
        else:
            ukeire_label = pd.Series([""] * len(self.df_shipments), index=self.df_shipments.index)
        vendor = self._fallback_vendor_series()

        grouped = pd.DataFrame({
            "vendor": vendor[miss],
            "ukeire": ukeire_label[miss],
            "pallet": pallet[miss],
        }).groupby(["vendor", "ukeire"]).agg(rows=("pallet", "size"), pallets=("pallet", "sum"))
        pairs = []
        for key, row in grouped.iterrows():
            pairs.append({
                "vendor": str(key[0]),
                "ukeire": str(key[1]),
                "rows": int(row["rows"]),
                "pallets": int(row["pallets"]),
            })
        return {"rows": int(miss.sum()), "pallets": int(pallet[miss].sum()), "pairs": pairs}

    def build_unreachable_warning_message(self, max_pairs: int = 20) -> str:
        """collect_unreachable_summary の結果を GUI 警告用の文面に組み立てる。

        Issue #110 CD-2: 文面は scripts/tmp/cd_probe.py [6] が機械生成したものと同一。
        到達不能が無い場合は空文字を返す（呼び出し側はポップアップを出さない）。
        """
        summary = self.collect_unreachable_summary()
        pairs = summary.get("pairs", [])
        if not pairs:
            return ""
        lines = ["出荷場一覧に未登録の組合せがあるため、次のデータは割り振り対象外です。"]
        for pair in pairs[:max_pairs]:
            lines.append(
                "  ・" + str(pair["vendor"]) + "/" + str(pair["ukeire"])
                + " " + str(pair["rows"]) + "行(" + str(pair["pallets"]) + "パレット)"
            )
        rest = len(pairs) - max_pairs
        if rest > 0:
            lines.append("  ... 他 " + str(rest) + " 組")
        lines.append(
            "合計 " + str(summary.get("rows", 0)) + "行 / "
            + str(summary.get("pallets", 0)) + "パレット"
        )
        return "\n".join(lines)


# ===== 入車時間マスタ管理 =====
MASTER_FILENAME = "入車時間マスタ.xlsx"
MASTER_COLUMNS = ["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]
_MASTER_EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")


class MasterFileError(Exception):
    """入車時間マスタの入出力エラー（利用者向けの説明文をそのまま持つ）。"""


class MasterFileLockedError(MasterFileError, PermissionError):
    """Excel等に開かれていて入車時間マスタを読み書きできない。"""


class MasterFileReadError(MasterFileError, ValueError):
    """入車時間マスタを読み取れない（破損・同期競合など）。"""


def get_legacy_master_path() -> Path:
    """従来の入車時間マスタ配置（移行期・異常時のフォールバック先）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / MASTER_FILENAME
    else:
        return Path(__file__).resolve().parents[2] / MASTER_FILENAME


def _to_master_file_path(raw_value) -> Optional[Path]:
    """設定値（ファイル/フォルダのどちらでも可）をマスタのファイルパスへ正規化する。"""
    text = str(raw_value or "").strip()
    if not text:
        return None
    p = Path(text)
    if p.suffix.lower() in _MASTER_EXCEL_SUFFIXES:
        return p
    return p / MASTER_FILENAME


def _resolve_master_path_candidates(config: Optional[dict] = None,
                                    legacy_path: Optional[Path] = None) -> List[Path]:
    """入車時間マスタの候補パスを優先順に返す（_resolve_shipments_path と同じ流儀）。

    1) config["master_path"]（明示指定。フォルダ指定も可。通常は未設定）
    2) config["base_dir"] 直下（SharePoint(OneDrive)同期フォルダ＝通常運用の本命）
    3) 従来位置（frozen: exe同階層 / 開発時: リポジトリ直下）
    """
    if config is None:
        config = load_config()
    if legacy_path is None:
        legacy_path = get_legacy_master_path()

    candidates: List[Path] = []
    for raw_value in (config.get("master_path"), config.get("base_dir")):
        p = _to_master_file_path(raw_value)
        if p is not None and p not in candidates:
            candidates.append(p)
    if legacy_path not in candidates:
        candidates.append(legacy_path)
    return candidates


def _resolve_master_path(config: Optional[dict] = None,
                         legacy_path: Optional[Path] = None) -> Path:
    """候補リストから入車時間マスタのパス（読み書き共通）を決定する。

    - 既に存在する候補があれば、優先順位の高いものを採用する。
    - 1件も存在しない場合は例外にせず、親フォルダにアクセスできる先頭候補を
      「新規作成先」として返す（マスタ未配置でもアプリを起動不能にしない）。
    - どの候補にもアクセスできない場合（NW未接続・OneDrive未同期）は従来位置を返す。
    """
    if config is None:
        config = load_config()
    if legacy_path is None:
        legacy_path = get_legacy_master_path()

    candidates = _resolve_master_path_candidates(config, legacy_path)
    for p in candidates:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    for p in candidates:
        try:
            if p.parent.is_dir():
                return p
        except OSError:
            continue
    return legacy_path


def get_master_path() -> Path:
    return _resolve_master_path()


def find_master_conflict_candidates(master_path: Path) -> List[Path]:
    """OneDrive同期の競合で生まれた「〜のコピー」等の類似ファイルを列挙する。"""
    try:
        master_path = Path(master_path)
        folder = master_path.parent
        if not folder.is_dir():
            return []
        return sorted(
            p for p in folder.glob(f"{master_path.stem}*")
            if p.name != master_path.name
            and not p.name.startswith("~$")
            and p.suffix.lower() in _MASTER_EXCEL_SUFFIXES
        )
    except OSError:
        return []


def _conflict_lines(master_path: Path, max_items: int = 10) -> List[str]:
    conflicts = find_master_conflict_candidates(master_path)
    if not conflicts:
        return []
    lines = ["", "同じフォルダに似た名前のファイルがあります（OneDrive同期の競合の可能性）:"]
    lines += [f"  ・{p.name}" for p in conflicts[:max_items]]
    lines.append(f"正しいものを『{MASTER_FILENAME}』の名前に戻してください。")
    return lines


def build_master_not_found_message(master_path: Path) -> str:
    """マスタが見つからないときの案内文（GUI表示・ログ共用）。"""
    lines = [
        f"入車時間マスタが見つかりません: {master_path}",
        "",
        f"通常は SharePoint(OneDrive) 同期フォルダ（設定の base_dir）直下に『{MASTER_FILENAME}』を置きます。",
        "次を確認してください:",
        "  ・ネットワーク（社内NW/VPN）に接続されているか",
        "  ・OneDriveが起動し、同期が完了しているか（クラウドのみの状態になっていないか）",
        f"  ・ファイル名が『{MASTER_FILENAME}』のままか",
        f"  ・config/{CONFIG_FILENAME} の base_dir が正しいか",
    ]
    lines += _conflict_lines(master_path)
    lines += ["", "マスタが無い場合は空の状態で動作します（保存すると上記の場所へ新規作成されます）。"]
    return "\n".join(lines)


def _master_rescue_dir() -> Path:
    """保存に失敗した編集内容を退避するフォルダ（テストで差し替え可）。"""
    return Path(tempfile.gettempdir())


def _write_master_excel(df_save: pd.DataFrame, master_path: Path) -> None:
    """実際にExcelへ書き出す最小単位（テストで差し替え可）。"""
    df_save.to_excel(master_path, index=False, engine="openpyxl", sheet_name="入車時間マスタ")


def _rescue_master_dataframe(df_save: Optional[pd.DataFrame]) -> Optional[Path]:
    """保存失敗時にデータを失わないよう、編集内容を退避コピーとして書き出す。"""
    if df_save is None:
        return None
    try:
        rescue_dir = _master_rescue_dir()
        rescue_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rescue_path = rescue_dir / f"入車時間マスタ_未保存_{stamp}.xlsx"
        _write_master_excel(df_save, rescue_path)
        return rescue_path
    except Exception:
        return None


def _rescue_lines(rescue_path: Optional[Path]) -> List[str]:
    if rescue_path is None:
        return []
    return ["", "編集内容は次の場所へ退避しました（データは失われていません）:", f"  {rescue_path}"]


def _build_master_locked_message(master_path: Path,
                                 rescue_path: Optional[Path] = None,
                                 action: str = "保存") -> str:
    lines = [
        f"入車時間マスタを{action}できませんでした: {master_path}",
        "",
        "ファイルがExcelで開かれている可能性があります。",
        f"  ・自分または他の人が『{MASTER_FILENAME}』をExcelで開いていないか確認してください。",
        "  ・SharePoint(OneDrive) のブラウザ編集画面も閉じてください。",
        "  ・閉じたあと、もう一度同じ操作をやり直してください。",
        "",
        "画面上の編集内容は残っています（このまま再保存できます）。",
    ]
    lines += _rescue_lines(rescue_path)
    return "\n".join(lines)


def _build_master_folder_missing_message(master_path: Path,
                                         rescue_path: Optional[Path] = None) -> str:
    lines = [
        f"入車時間マスタの保存先フォルダが見つかりません: {Path(master_path).parent}",
        "",
        "SharePoint(OneDrive) の同期フォルダにアクセスできない可能性があります。",
        "  ・ネットワーク（社内NW/VPN）に接続されているか",
        "  ・OneDriveが起動し、同期が有効になっているか",
        f"  ・config/{CONFIG_FILENAME} の base_dir が正しいか",
        "を確認してから、もう一度保存してください。",
        "",
        "画面上の編集内容は残っています（このまま再保存できます）。",
    ]
    lines += _rescue_lines(rescue_path)
    return "\n".join(lines)


def _build_master_save_failed_message(master_path: Path, error: BaseException,
                                      rescue_path: Optional[Path] = None) -> str:
    lines = [
        f"入車時間マスタを保存できませんでした: {master_path}",
        "",
        f"原因: {error}",
        "",
        "ファイルがExcelで開かれている、またはOneDriveの同期中である可能性があります。",
        "少し待ってから、もう一度保存してください。",
        "",
        "画面上の編集内容は残っています（このまま再保存できます）。",
    ]
    lines += _rescue_lines(rescue_path)
    return "\n".join(lines)


def _build_master_read_failed_message(master_path: Path, error: BaseException) -> str:
    lines = [
        f"入車時間マスタを読み込めませんでした: {master_path}",
        "",
        f"原因: {error}",
        "",
        "次を確認してください:",
        "  ・Excelで開いたままになっていないか（開いていれば閉じる）",
        "  ・OneDriveの同期が完了しているか（クラウドのみのファイルはダウンロードが必要）",
        "  ・ファイルが壊れていないか（SharePointのバージョン履歴から復元できます）",
    ]
    lines += _conflict_lines(master_path)
    return "\n".join(lines)


def _raise_if_master_locked(master_path: Path, df_save: Optional[pd.DataFrame] = None) -> None:
    """書き込めない状態なら、既存ファイルに触る前に中断する（データ保全）。"""
    try:
        if not master_path.exists():
            return
    except OSError:
        return
    try:
        with open(master_path, "r+b"):
            return
    except PermissionError as e:
        raise MasterFileLockedError(
            _build_master_locked_message(master_path, _rescue_master_dataframe(df_save))
        ) from e
    except OSError:
        # 同期中などで一時的に判定できない場合は、実際の書き込みで判断する
        return


def load_pickup_time_master_xlsx(master_path: Path) -> pd.DataFrame:
    master_path = Path(master_path)
    try:
        exists = master_path.exists()
    except OSError:
        exists = False
    if not exists:
        logger.warning(build_master_not_found_message(master_path))
        return pd.DataFrame(columns=list(MASTER_COLUMNS))
    try:
        df = pd.read_excel(master_path, sheet_name=0, dtype=str)
    except PermissionError as e:
        raise MasterFileLockedError(
            _build_master_locked_message(master_path, action="読み込み")
        ) from e
    except Exception as e:
        raise MasterFileReadError(_build_master_read_failed_message(master_path, e)) from e
    df.columns = [str(c).strip() for c in df.columns]
    required_cols = ["OData_納入先", "NONYUHIBIN", "入車時間"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        error = ValueError(f"入車時間マスタに必要な列がありません: {', '.join(missing)}")
        raise MasterFileReadError(_build_master_read_failed_message(master_path, error)) from error
    # 任意列: セットありフラグ（未設定時は空文字で扱う）
    if "セットありフラグ" not in df.columns:
        df["セットありフラグ"] = ""
    out_cols = ["OData_納入先", "NONYUHIBIN", "入車時間", "セットありフラグ"]
    df = df[out_cols].copy()
    df["OData_納入先"] = df["OData_納入先"].astype(str).str.strip()
    nony = df["NONYUHIBIN"].astype(str).str.translate(_ZEN2HAN_DIGIT_COLON)
    nony_num = pd.to_numeric(nony.str.extract(r"(\d+)")[0], errors="coerce")
    df["NONYUHIBIN"] = nony_num.apply(lambda n: f"{int(n):02d}" if pd.notna(n) else "")
    df["入車時間"] = df["入車時間"].apply(_normalize_hhmm)
    df["セットありフラグ"] = df["セットありフラグ"].astype(str).str.strip()
    return df


def save_pickup_time_master_xlsx(df: pd.DataFrame, master_path: Path):
    df_save = df.copy()
    expected_cols = list(MASTER_COLUMNS)
    for col in expected_cols:
        if col not in df_save.columns:
            df_save[col] = ""
    df_save = df_save[expected_cols]

    master_path = Path(master_path)
    try:
        parent_ok = master_path.parent.is_dir()
    except OSError:
        parent_ok = False
    if not parent_ok:
        # 勝手にローカルフォルダを作らない（SPO同期フォルダの偽物を生むため）
        raise MasterFileError(
            _build_master_folder_missing_message(master_path, _rescue_master_dataframe(df_save))
        )

    _raise_if_master_locked(master_path, df_save=df_save)
    try:
        _write_master_excel(df_save, master_path)
    except PermissionError as e:
        raise MasterFileLockedError(
            _build_master_locked_message(master_path, _rescue_master_dataframe(df_save))
        ) from e
    except Exception as e:
        raise MasterFileError(
            _build_master_save_failed_message(master_path, e, _rescue_master_dataframe(df_save))
        ) from e


def _normalize_excel_time_value(value) -> str:
    """Excel由来の時刻値を HH:MM に正規化する。"""
    if value is None or pd.isna(value):
        return ""

    if isinstance(value, time):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, datetime):
        return f"{value.hour:02d}:{value.minute:02d}"

    if isinstance(value, (int, float)):
        # Excelシリアル時刻（0.0〜1.0）を分解
        if 0 <= float(value) < 1:
            total_minutes = int(round(float(value) * 24 * 60))
            hh = (total_minutes // 60) % 24
            mm = total_minutes % 60
            return f"{hh:02d}:{mm:02d}"

    s = str(value).strip().translate(_ZEN2HAN_DIGIT_COLON)
    if not s:
        return ""

    normalized = _normalize_hhmm(s)
    if normalized:
        return normalized

    # 例: 830 / 0830 形式も補足
    m = re.fullmatch(r"(\d{1,2})(\d{2})", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 47 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    return ""


def _resolve_column_name(columns: List[str], candidates: List[str]) -> Optional[str]:
    """候補名（表記ゆれ含む）から実列名を解決する。"""
    normalized = {
        re.sub(r"[^0-9a-zA-Z一-龯ぁ-ゔァ-ヴー]+", "", str(c)).lower(): str(c)
        for c in columns
    }
    for cand in candidates:
        key = re.sub(r"[^0-9a-zA-Z一-龯ぁ-ゔァ-ヴー]+", "", str(cand)).lower()
        if key in normalized:
            return normalized[key]
    return None


def _detect_header_row_index(raw_df: pd.DataFrame, max_scan_rows: int = 20) -> int:
    """先頭の説明行を飛ばし、実ヘッダー行の候補インデックスを返す。"""
    vendor_candidates = [
        "OData_納入先", "納入先", "仕入先", "取引先", "ベンダー", "メーカー", "便名",
    ]
    bin_candidates = [
        "NONYUHIBIN", "納入便", "便番号", "便No", "便No.", "便NO", "便NO.", "便",
    ]
    time_candidates = [
        "入車時間", "入車時刻", "入射時間", "納入時間", "到着時間", "到着時刻", "時刻", "時間",
    ]
    receipt_candidates = ["受入", "受入先", "受入コード", "受入CD", "受入区分"]

    def _norm(text: str) -> str:
        return re.sub(r"[^0-9a-zA-Z一-龯ぁ-ゔァ-ヴー]+", "", str(text)).lower()

    groups = [
        {_norm(x) for x in vendor_candidates},
        {_norm(x) for x in bin_candidates},
        {_norm(x) for x in time_candidates},
        {_norm(x) for x in receipt_candidates},
    ]

    best_idx = 0
    best_score = -1
    scan_len = min(max_scan_rows, len(raw_df.index))
    for i in range(scan_len):
        row_vals = [
            _norm(v) for v in raw_df.iloc[i].tolist()
            if v is not None and str(v).strip() != ""
        ]
        if not row_vals:
            continue
        keys = set(row_vals)
        score = sum(1 for g in groups if keys & g)
        if score > best_score:
            best_score = score
            best_idx = i
        # 必須の3要素（納入先/便名, 便No, 時刻）を満たしたら即採用
        if score >= 3:
            return i

    return best_idx


def _expand_ch_master_vendors(raw_vendor: str, vendor_map: Optional[dict]) -> List[str]:
    """CH入車時間マスタ向けの便名変換・展開ルール。"""
    base = str(raw_vendor).strip()
    if not base:
        return []

    normalized = base.upper().replace("ー", "-").replace("－", "-").replace("―", "-")

    # 現場指定の固定変換
    if normalized.endswith("-TP") or normalized == "TP":
        return ["日野"]
    # KVC-B7 / KVC-B3 のようなハイフン区切りKVC受入分割名はそのまま保持する
    if normalized.startswith("KVC-") and normalized not in ("KVC-"):
        return [base]
    if normalized.endswith("-KVC") or normalized == "KVC":
        return ["KVC"]
    if normalized.endswith("-RH") or normalized == "RH":
        return ["元町", "高岡"]
    if base == "三栄本社":
        return ["三栄"]
    if base == "織機成形":
        return ["織機"]

    # まず通常の便名マップ（例: TMK->KVC, 三栄SE->三栄）を適用
    mapped = vendor_map.get(base, base) if vendor_map else base
    return [mapped]


def parse_ukeire_ch_excel(
    file_path: Path,
    sheet_name: str = "全受入_納入便データ",
    vendor_map: Optional[dict] = None,
) -> pd.DataFrame:
    """受入データExcelから、受入=CHの入車時間マスタを抽出する。"""
    if vendor_map is None:
        vendor_map = HAISHA_VENDOR_MAP

    try:
        raw_src = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        raise ValueError(f"シート '{sheet_name}' の読み込みに失敗しました: {e}")

    if raw_src is None or raw_src.empty:
        return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])

    header_idx = _detect_header_row_index(raw_src)
    header_vals = [str(v).strip() if v is not None else "" for v in raw_src.iloc[header_idx].tolist()]

    src = raw_src.iloc[header_idx + 1:].copy()
    src.columns = header_vals
    valid_cols = []
    for c in src.columns:
        s = str(c).strip()
        s_low = s.lower()
        if s == "":
            continue
        if s_low in {"nan", "none"}:
            continue
        if s_low.startswith("unnamed"):
            continue
        valid_cols.append(c)
    src = src.loc[:, valid_cols]
    src = src.dropna(how="all")
    if src.empty:
        return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])

    src.columns = [str(c).strip() for c in src.columns]
    cols = list(src.columns)

    receipt_col = _resolve_column_name(cols, [
        "受入", "受入先", "受入コード", "受入CD", "受入区分",
    ])
    vendor_col = _resolve_column_name(cols, [
        "OData_納入先", "納入先", "仕入先", "取引先", "ベンダー", "メーカー", "便名",
    ])
    bin_col = _resolve_column_name(cols, [
        "NONYUHIBIN", "納入便", "便番号", "便No", "便No.", "便NO", "便NO.", "便",
    ])
    time_col = _resolve_column_name(cols, [
        "入車時間", "入車時刻", "入射時間", "納入時間", "到着時間", "到着時刻", "時刻", "時間",
    ])

    missing = []
    if vendor_col is None:
        missing.append("納入先/便名")
    if bin_col is None:
        missing.append("納入便/便No")
    if time_col is None:
        missing.append("入車時間/到着時間")
    if missing:
        raise ValueError(
            "必要列が見つかりません: " + ", ".join(missing) +
            f"\n検出列: {', '.join(cols)}"
        )

    if receipt_col is None:
        work = src.copy()
    else:
        work = src[src[receipt_col].astype(str).str.strip().str.upper() == "CH"].copy()
    if work.empty:
        return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])

    records: List[dict] = []
    for _, row in work.iterrows():
        raw_vendor = str(row.get(vendor_col, "")).strip()
        raw_bin = str(row.get(bin_col, "")).strip().translate(_ZEN2HAN_DIGIT_COLON)
        raw_time = row.get(time_col, "")

        if not raw_vendor or not raw_bin:
            continue

        time_str = _normalize_excel_time_value(raw_time)
        if not time_str:
            continue

        bin_num = pd.to_numeric(pd.Series([raw_bin]).str.extract(r"(\d+)")[0], errors="coerce").iloc[0]
        if pd.isna(bin_num):
            continue

        vendors = _expand_ch_master_vendors(raw_vendor, vendor_map)
        for vendor in vendors:
            records.append({
                "OData_納入先": vendor,
                "NONYUHIBIN": f"{int(bin_num):02d}",
                "入車時間": time_str,
            })

    if not records:
        return pd.DataFrame(columns=["OData_納入先", "NONYUHIBIN", "入車時間"])

    df = pd.DataFrame(records, columns=["OData_納入先", "NONYUHIBIN", "入車時間"])
    df = df.drop_duplicates(subset=["OData_納入先", "NONYUHIBIN"], keep="first")
    df["_sort_bin"] = pd.to_numeric(df["NONYUHIBIN"], errors="coerce").fillna(0)
    df = df.sort_values(["OData_納入先", "_sort_bin"]).drop(columns=["_sort_bin"]).reset_index(drop=True)
    return df


def parse_haisha_excel(file_path: Path, vendor_map: dict = None) -> pd.DataFrame:
    """配車表Excel（Ｎ８ *.xlsm）から入車時間マスタデータを抽出"""
    if vendor_map is None:
        vendor_map = HAISHA_VENDOR_MAP
    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    data: Dict[tuple, object] = {}
    max_row = ws.max_row or 100
    max_col = ws.max_column or 80
    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col, values_only=False):
        for cell in row:
            if cell.value is not None:
                data[(cell.row, cell.column)] = cell.value
    wb.close()
    results: List[dict] = []
    no_bin_vendors: List[dict] = []
    for r in range(1, max_row + 1):
        c_val = data.get((r, 3), "")
        e_val = data.get((r, 5), "")
        if not c_val or not e_val:
            continue
        if not re.match(r'^\d{2}N$', str(c_val).strip()):
            continue
        raw_vendor = str(e_val).strip()
        vendor = vendor_map.get(raw_vendor, raw_vendor)
        times_row = r - 1
        g_val = data.get((times_row, 7), None)
        try:
            total_trips = int(g_val) if g_val is not None else 0
        except (ValueError, TypeError):
            total_trips = 0
        pairs: List[Tuple[str, str]] = []
        arrival_times_only: List[str] = []
        for col in range(11, max_col + 1):
            time_val = data.get((times_row, col))
            bin_val = data.get((r, col))
            if time_val is None:
                continue
            time_str = str(time_val).strip()
            normalized = _normalize_hhmm(time_str)
            if not normalized:
                continue
            if bin_val is not None:
                bin_str = str(bin_val).strip()
                try:
                    bin_num = int(bin_str)
                    pairs.append((normalized, f"{bin_num:02d}"))
                except (ValueError, TypeError):
                    arrival_times_only.append(normalized)
            else:
                arrival_times_only.append(normalized)
        if pairs:
            for time_s, bin_s in pairs:
                results.append({"OData_納入先": vendor, "NONYUHIBIN": bin_s, "入車時間": time_s})
        elif arrival_times_only and total_trips > 0:
            shift = "2直" if r > 36 else "1直"
            no_bin_vendors.append({"vendor": vendor, "times": arrival_times_only,
                                    "total_trips": total_trips, "shift": shift})
    by_vendor: Dict[str, list] = {}
    for info in no_bin_vendors:
        by_vendor.setdefault(info["vendor"], []).append(info)
    for vendor, infos in by_vendor.items():
        sorted_infos = sorted(infos, key=lambda x: 0 if x["shift"] == "2直" else 1)
        bin_counter = 1
        for info in sorted_infos:
            times = info["times"]
            trips = info["total_trips"]
            num_times = len(times)
            if num_times == 0:
                continue
            base, remainder = divmod(trips, num_times)
            for i, t in enumerate(times):
                count = base + (1 if i < remainder else 0)
                for _ in range(count):
                    results.append({"OData_納入先": vendor, "NONYUHIBIN": f"{bin_counter:02d}", "入車時間": t})
                    bin_counter += 1
    df = pd.DataFrame(results, columns=["OData_納入先", "NONYUHIBIN", "入車時間"])
    df["_sort_bin"] = pd.to_numeric(df["NONYUHIBIN"], errors="coerce").fillna(0)
    df = df.sort_values(["OData_納入先", "_sort_bin"]).drop(columns=["_sort_bin"]).reset_index(drop=True)
    return df
