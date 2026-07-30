# -*- coding: utf-8 -*-
"""CHかんばんセット — 定数・工数計算式"""

# ===== 仕分け定数 =====
DEFAULT_MIXING_KEY = "UKEIRE"           # 混載キーのデフォルト列名
DEFAULT_HEIGHT_CAP = 2450               # 高さ上限（mm）
SPECIAL_HINBAN = "631426010000"         # 種類1の特例対象品番
SPECIAL_HEIGHT_CAP = 2165               # 特例高さ上限（mm）
BASE_ONE_TIME = 187.64                  # 基礎一回工数
MIDDLE_WORK = 3.247                     # 中間作業工数
BASE_PER_PAL = 52                       # パレット単位工数

# ===== 工程定数（CH固有: メイン/リリーフ/あふれの3工程） =====
PROC_MAIN = "メイン"
PROC_RELIEF = "リリーフ"
PROC_OVERFLOW = "あふれ"
PROC_MAIN_LABEL = "メイン工程"
PROC_RELIEF_LABEL = "リリーフ工程"
PROC_OVERFLOW_LABEL = "あふれ工程"

# ===== 仮想山定数 =====
# 表示/出力専用の仮想山を識別する固定番号。
VIRTUAL_YAMA_NO = -1

# ===== ファイル名 =====
CONFIG_FILENAME = "ch_kanban_settings.json"
REASSIGN_LOG_FILENAME = "reassign_log.csv"

# ===== 休憩時間（秒単位） =====
BREAK_TIMES = [
    # 1直
    (8 * 3600 + 30 * 60, 9 * 3600),                # 8:30~9:00
    (10 * 3600 + 40 * 60, 11 * 3600 + 25 * 60),   # 10:40~11:25
    (12 * 3600 + 55 * 60, 13 * 3600 + 25 * 60),   # 12:55~13:25
    # 2直
    (18 * 3600 + 45 * 60, 19 * 3600 + 15 * 60),   # 18:45~19:15
    (20 * 3600 + 55 * 60, 21 * 3600 + 40 * 60),   # 20:55~21:40
    (23 * 3600 + 10 * 60, 23 * 3600 + 40 * 60),   # 23:10~23:40
]

# ===== 時間バッファ（秒単位） =====
# 各直1便目の引取開始バッファ（直開始時刻 + この時間）
SHIFT_FIRST_TRIP_BUFFER_SECS = 35 * 60
# 1便目クラスターの解禁バッファ（その便の入車時刻 + この時間）
FIRST_BIN_RELEASE_BUFFER_SECS = 35 * 60
# 長休憩（昼休憩）前: 休憩開始の何分前までに山を完了させるか
LUNCH_PRE_MARGIN_SECS = 10 * 60
# 長休憩後: 作業再開までのバッファ
LUNCH_POST_RESUME_SECS = 35 * 60
# 長休憩後: 新しい山の開始をロックする時間
LUNCH_POST_LOCK_SECS = 35 * 60

# 集荷完了の締切: 各便の入車時刻の何分前までに山を完了させるか
PICKUP_DEADLINE_BUFFER_SECS = 20 * 60

# ===== 混載ポリシー =====
SIZE_MIXING_POLICY = {
    "1": {"allow_mixing": True, "max_mix_groups": 3, "mixing_key": DEFAULT_MIXING_KEY},
    "4": {"allow_mixing": False},
    "default": {"allow_mixing": False},
}

# ===== セットボード色定義 =====
COLOR_MAIN = "#DFF0FF"      # メイン工程: 薄い青
COLOR_RELIEF = "#FBE1EF"    # リリーフ工程: 薄いピンク
COLOR_OVERFLOW = "#FFF0E0"  # あふれ工程: 薄いオレンジ
COLOR_VIOLATION = "#FF6B6B" # 違反タイル: 赤
COLOR_UNSET = "#FFF6BF"     # 未設定: 薄い黄色

# ===== 配車表の納入先名マッピング =====
HAISHA_VENDOR_MAP = {
    "日野プレス": "日野",
    "日野Eフード": "日野EH",
    "TMK": "KVC",
    "三栄SE": "三栄",
}


# 仮想山判定の共通関数。
# 山通番が -1（仮想山）かどうかを判定する。
# None/文字列などが来ても安全に False を返し、呼び出し側での例外を防ぐ。
def is_virtual_yama(yama) -> bool:
    """仮想山かどうかを判定する（現在は山通番=-1）。"""
    try:
        return int(yama) == VIRTUAL_YAMA_NO
    except (TypeError, ValueError):
        return False