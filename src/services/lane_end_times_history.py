# -*- coding: utf-8 -*-
"""CHかんばんセット — 前回仕分け終了時刻の履歴管理

レーン毎の仕分け終了時刻を最大2件まで履歴保持し、ドロップダウン選択で過去の時刻に巻き戻す。
TDD fail先行で実装した純粋関数。副作用なし、tkinter 依存なし。
"""

MAX_HISTORY = 2


def push_lane_end_times(history: list, new_times: dict) -> list:
    """新しい終了時刻を履歴の先頭に追加する（FIFO・最大2件保持）
    
    入力 history と new_times は破壊しない（防御的コピー）。
    3件目以降の push では最古を自動破棄。
    
    Args:
        history: 既存の履歴（list[dict]）。空でも可。
        new_times: 新しい終了時刻（dict）。e.g. {"山1": "08:30", "山2": "09:15"}
    
    Returns:
        新しい履歴（list[dict]）。先頭 = 最新。最大 MAX_HISTORY 件。
        入力は非破壊。返り値内の dict も防御的コピー。
    
    Example:
        >>> history = []
        >>> history = push_lane_end_times(history, {"山1": "08:00"})
        >>> len(history)
        1
        >>> history[0]
        {"山1": "08:00"}
        
        >>> history = push_lane_end_times(history, {"山1": "08:30"})
        >>> history[0]
        {"山1": "08:30"}
        >>> history[1]
        {"山1": "08:00"}
        
        >>> # 3件目で最古破棄
        >>> history = push_lane_end_times(history, {"山1": "09:00"})
        >>> len(history)
        2
        >>> history[0]
        {"山1": "09:00"}
        >>> history[1]
        {"山1": "08:30"}
    """
    # 新規 dict の防御的コピーを先頭に追加
    new_entry = dict(new_times)
    result = [new_entry] + history
    
    # 最大 MAX_HISTORY 件で切り詰め（末尾 = 最古を破棄）
    result = result[:MAX_HISTORY]
    
    return result


def select_lane_end_times(history: list, choice: str) -> dict:
    """ドロップダウン選択に基づいて、履歴から終了時刻を取得する
    
    choice="最新" なら index[0]、choice="1つ前" なら index[1] を返す。
    該当要素がない場合は空 dict {} を返す。
    未知の choice は「最新」扱い。
    
    返り値は防御的コピー（呼び出し側で編集しても元の履歴不変）。
    
    Args:
        history: 履歴（list[dict]）。先頭 = 最新。
        choice: ドロップダウン選択値（str）。"最新", "1つ前", その他（→最新扱い）
    
    Returns:
        選択した終了時刻（dict）。該当なしなら {}。
        返り値は防御的コピー。
    
    Example:
        >>> history = [{"山1": "08:30"}, {"山1": "08:00"}]
        >>> select_lane_end_times(history, "最新")
        {"山1": "08:30"}
        
        >>> select_lane_end_times(history, "1つ前")
        {"山1": "08:00"}
        
        >>> select_lane_end_times([], "最新")
        {}
        
        >>> select_lane_end_times([{"山1": "08:00"}], "1つ前")
        {}
        
        >>> select_lane_end_times(history, "未知の値")  # 最新扱い
        {"山1": "08:30"}
    """
    # choice の正規化。未知値は「最新」扱い
    if choice == "1つ前":
        index = 1
    else:
        # "最新" その他の値も「最新」扱い
        index = 0
    
    # index が範囲内なら、防御的コピーを返す
    if 0 <= index < len(history):
        return dict(history[index])
    
    # 範囲外なら空 dict
    return {}


# ============================================================================
# UI 表現層: ドロップダウンラベル生成と選択肢正規化
# ============================================================================

def generate_lane_end_times_label(history: list, choice: str) -> str:
    """履歴からドロップダウン用ラベルを生成する
    
    Example:
        "最新 (メイン 12:24 / リリーフ 12:10)"
        "1つ前 (未計算)"
    
    Args:
        history: 履歴（list[dict]）。値は秒（int）。
        choice: "最新" or "1つ前"
    
    Returns:
        ドロップダウン用ラベル（str）
    """
    from src.utils.time_formatter import seconds_to_hhMM
    
    # 該当する履歴を取得
    selected = select_lane_end_times(history, choice)
    
    # 空なら「未計算」
    if not selected:
        return f"{choice} (未計算)"
    
    # 歴史にある値から "メイン" と "リリーフ" を取得（ない場合は 0）
    # ※ 秒は int 型
    main_secs = selected.get("メイン", 0)
    relief_secs = selected.get("リリーフ", 0)
    
    # 秒 → "HH:MM" に変換
    main_hhMM = seconds_to_hhMM(main_secs)
    relief_hhMM = seconds_to_hhMM(relief_secs)
    
    return f"{choice} (メイン {main_hhMM} / リリーフ {relief_hhMM})"


def normalize_choice_label(label: str) -> str:
    """ドロップダウン表示ラベルから「最新」「1つ前」を抽出する
    
    ラベルが "最新 (メイン 12:00 / ...)" 形式の場合、
    括弧の前の部分（"最新"）を抽出して返す。
    
    既に "最新" や "1つ前" のみの場合はそのまま返す。
    
    Args:
        label: ドロップダウンラベル or 選択値（str）
    
    Returns:
        正規化された選択値（"最新" or "1つ前"）
    
    Example:
        >>> normalize_choice_label("最新 (メイン 12:00 / リリーフ 11:45)")
        "最新"
        
        >>> normalize_choice_label("1つ前 (未計算)")
        "1つ前"
        
        >>> normalize_choice_label("最新")
        "最新"
    """
    # 括弧があれば、その前の部分を抽出
    if "(" in label:
        return label.split("(")[0].strip()
    
    # 括弧がなければそのまま
    return label


import json as _json
import os as _os
import sys as _sys
import tempfile as _tempfile
from datetime import datetime as _datetime
from pathlib import Path as _Path

HISTORY_FILENAME = "lane_end_times_history.json"
HISTORY_FORMAT_VERSION = 1


def get_history_path() -> _Path:
    """履歴ファイルの保存先を返す（既存 get_config_path と同じ流儀）。"""
    if getattr(_sys, 'frozen', False):
        return _Path(_sys.executable).parent / HISTORY_FILENAME
    return _Path(__file__).resolve().parents[2] / "config" / HISTORY_FILENAME


def save_lane_end_times_history(history: list, path=None) -> bool:
    """履歴をJSONファイルへ原子的に保存する。

    書き込み中にプロセスが落ちても前回のファイルを壊さないよう、
    一時ファイルへ書き切ってから os.replace で置き換える。

    Args:
        history: 保存する履歴（list[dict]）。空リストも可。
        path: 保存先。None の場合 get_history_path() を使用。

    Returns:
        成功時 True、失敗時 False（例外は投げない＝GUIを止めない）。
    """
    try:
        target = _Path(path) if path is not None else get_history_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": HISTORY_FORMAT_VERSION,
            "saved_at": _datetime.now().isoformat(timespec="seconds"),
            "history": list(history) if history else [],
        }
        fd, tmp_name = _tempfile.mkstemp(
            prefix=".tmp_", suffix=".json", dir=str(target.parent)
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                _json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                _os.fsync(f.fileno())
            _os.replace(tmp_name, str(target))
        except Exception:
            try:
                if _os.path.exists(tmp_name):
                    _os.remove(tmp_name)
            except Exception:
                pass
            raise
        return True
    except Exception:
        return False


def load_lane_end_times_history(path=None) -> list:
    """履歴をJSONファイルから読み込む。

    ファイルが無い・壊れている・構造が違う場合は空リストを返し、
    GUIの起動を妨げない。

    Args:
        path: 読込元。None の場合 get_history_path() を使用。

    Returns:
        履歴（list[dict]）。読めない場合は []。
    """
    try:
        target = _Path(path) if path is not None else get_history_path()
        if not target.exists():
            return []
        with open(target, "r", encoding="utf-8") as f:
            payload = _json.load(f)
        if not isinstance(payload, dict):
            return []
        history = payload.get("history")
        if not isinstance(history, list):
            return []
        cleaned = [dict(item) for item in history if isinstance(item, dict)]
        return cleaned[:MAX_HISTORY]
    except Exception:
        return []
