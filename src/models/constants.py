# -*- coding: utf-8 -*-
"""CHかんばんセット — 定数・工数計算式"""


# ===== 仕分け定数 =====
DEFAULT_MIXING_KEY = "UKEIRE"           # 混載キーのデフォルト列名
DEFAULT_HEIGHT_CAP = 2450               # 高さ上限（mm）
# 2026/08 高さ特例（2165mm）は解除済み（Kawasaki指示）。
# Issue #79: 特例品番を含む山はSPECIAL_HINBAN_HEIGHT_CAP(2500mm)まで許容し、
# それ以外の通常山はDEFAULT_HEIGHT_CAP(2450mm)のまま（#78のDEFAULT一律2500案は不採用）。
SPECIAL_HINBAN = "631426010000"         # 種類1の特例対象品番
SPECIAL_HINBAN_HEIGHT_CAP = 2500         # 特例品番を1件でも含む山の高さ上限（mm）
BASE_ONE_TIME = 187.64                  # 基礎一回工数
MIDDLE_WORK = 3.247                     # 中間作業工数
BASE_PER_PAL = 52                       # パレット単位工数

# 日野便の特例: 日野系同士の1×21段積みは同一納入先かつ同一便(NONYUHIBIN一致)のみ許可。
# 納入先名の前方一致で判定（「日野」「日野EH」が対象）。片方だけ日野系なら条件なし。
# 2026/08 Kawasaki氏指示（解釈B）。
HINO_VENDOR_PREFIX = "日野"

# サイズ17特例: 全出荷先で高さ2500まで積載可（最大3パレット）。
# 通常の高さ上限DEFAULT_HEIGHT_CAP(2450)に対する特例。
# 複数出荷先が共通でサイズ17パレットを引き取るため。2026/06 Kawasaki氏確認。
SIZE17_MERGE_HEIGHT_CAP = 2500.0
SIZE17_TYPE = "17"

# サイズ5特例: 1山最大2枚に制限。
# 高さが収まっても3〜4枚積めないようにする職場ルール。2026/08 Kawasaki氏指示。
SIZE5_TYPE = "5"
SIZE5_MAX_PALLETS_PER_YAMA = 2

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
LOCAL_OUTPUT_DIR = r"C:\Users\1588386\DIG_Project\CHかんばんセット"
SPO_EXPORT_REQUIRED_COLUMNS = (
    "タイトル", "工程", "groupdata", "GroupedData", "パレット数", "グループ番号",
)

# ===== 休憩時間（秒単位） =====
# ===== 短休憩（2026-09-24 現場合意：仕分け猶予 20分→10分） =====
SHORT_BREAK_PURE_SECS = 10 * 60      # 純休憩（リリーフはこの10分だけを休憩として扱う）
SHORT_BREAK_SORTING_SECS = 10 * 60   # 仕分け猶予（旧 20分）
SHORT_BREAK_TOTAL_SECS = SHORT_BREAK_PURE_SECS + SHORT_BREAK_SORTING_SECS  # 引取できない時間 20分（旧 30分）
BREAK_TIMES = [
    # 1直
    (8 * 3600 + 30 * 60, 8 * 3600 + 30 * 60 + SHORT_BREAK_TOTAL_SECS),    # 8:30~8:50
    (10 * 3600 + 40 * 60, 11 * 3600 + 25 * 60),                           # 10:40~11:25（食事・変更なし）
    (12 * 3600 + 55 * 60, 12 * 3600 + 55 * 60 + SHORT_BREAK_TOTAL_SECS),  # 12:55~13:15
    # 2直
    (18 * 3600 + 45 * 60, 18 * 3600 + 45 * 60 + SHORT_BREAK_TOTAL_SECS),  # 18:45~19:05
    (20 * 3600 + 55 * 60, 21 * 3600 + 40 * 60),                           # 20:55~21:40（食事・変更なし）
    (23 * 3600 + 10 * 60, 23 * 3600 + 10 * 60 + SHORT_BREAK_TOTAL_SECS),  # 23:10~23:30
]

# ===== 時間バッファ（秒単位） =====
# 朝一・昼明けの作業開始バッファの内訳（2026-09-24 現場合意: 35分 → 25分）
#   移動15分 + 仕分け10分（旧: 仕分け20分）
START_MOVE_SECS = 15 * 60
START_SORTING_SECS = 10 * 60

# 各直1便目の引取開始バッファ（直開始時刻 + この時間）
SHIFT_FIRST_TRIP_BUFFER_SECS = START_MOVE_SECS + START_SORTING_SECS
# 1便目クラスターの解禁バッファ（その便の入車時刻 + この時間）
FIRST_BIN_RELEASE_BUFFER_SECS = START_MOVE_SECS + START_SORTING_SECS
# 長休憩（昼休憩）前: 休憩開始の何分前までに山を完了させるか
LUNCH_PRE_MARGIN_SECS = 10 * 60
# 長休憩後: 作業再開までのバッファ
LUNCH_POST_RESUME_SECS = START_MOVE_SECS + START_SORTING_SECS
# 長休憩後: 新しい山の開始をロックする時間
LUNCH_POST_LOCK_SECS = START_MOVE_SECS + START_SORTING_SECS

# 集荷完了の締切: 各便の入車時刻の何分前までに山を完了させるか
#   2026-09-24 現場合意: 20分 → 10分（1工程で引き取れる幅を広げるため）
#   ※ ARRIVAL_BUFFER_SECS（前便入車+10分の開始下限）と同じ10分だが、意味が別なので1つにまとめない
PICKUP_DEADLINE_BUFFER_SECS = 10 * 60
# EDF比較の下限値。実運用データに 15 山ケースがあるため 15 に緩和するが、
# 15 山の通常ビーム探索経路では既存の安定動作を優先し、EDF比較は 16 山以上でのみ適用する。
EDF_COMPARE_MIN_YAMAS = 15
# EDFの休憩境界スワップ探索上限
EDF_SWAP_MAX_ITERATIONS = 200

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

# 受入コード単位で便を分割して仕分け・照合する納入先。
# マスタ側の行名は f"{納入先}-{UKEIRE}"（例: KVC-B7, 元町-1W, 織機-61）で登録される。
# 織機は61/28/21の3受入で3分割（2026/09 Kawasaki氏指示）。マスタ(出荷場一覧・入車時間)に
# 織機-61, 織機-21, 織機-28 の3行の事前登録が必須（未登録だと当該受入の荷物が仕分け対象外になる）。
SPLIT_UKEIRE_ROUTES = frozenset({"KVC", "元町", "織機"})


# 仮想山判定の共通関数。
# 山通番が -1（仮想山）かどうかを判定する。
# None/文字列などが来ても安全に False を返し、呼び出し側での例外を防ぐ。
def is_virtual_yama(yama) -> bool:
    """仮想山かどうかを判定する（現在は山通番=-1）。"""
    try:
        return int(yama) == VIRTUAL_YAMA_NO
    except (TypeError, ValueError):
        return False
# ── C-7: メイン工程の前倒し採用の範囲（docs/仕分け・割り振りルール.md §4.4 2項） ──
# False: 従来どおり。主対象の締切を守れれば、締切の遅い山も先に割り込める
# True : 締切が違う山の前倒しは「主対象が待たされている時間」に収まる場合だけ許可
#        （同じ締切＝同じ便どうしの入れ替えは従来どおり）
# 実データでの検証と現場の合意が済むまでは False のまま運用する。
MAIN_PREFETCH_GAP_ONLY: bool = False
