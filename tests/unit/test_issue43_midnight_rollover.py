"""Issue #43: 深夜0時跨ぎ便(日野8便)の表記混在・山採番逆行の回帰テスト

修正前は赤(失敗)になることを確認してから修正する(#36の教訓)。
test_serializer_does_not_wrap_start_time_by_one_day はソース検査型のガード。
_serialize_lanes_final がネスト関数で外部から呼べないための代替手段である。
"""
from pathlib import Path

import pandas as pd
import pytest

from src.services.exporter import build_spo_export_df

ROOT = Path(__file__).resolve().parents[2]


def _make_proc_details(yamas):
    rows = []
    for y in yamas:
        rows.append({
            "山通番": int(y),
            "移動工数": 100.0,
            "納入先": "日野",
            "NONYUHIBIN": "2026072808",
            "UKEIRE": "1",
            "SEBANGO": "S%d" % int(y),
            "ストア": "A",
        })
    return pd.DataFrame(rows)


def _title_by_yama(spo_df):
    return {int(r["グループ番号"]): str(r["タイトル"]) for _, r in spo_df.iterrows()}


def _pick_by_yama(spo_df):
    return {int(r["グループ番号"]): int(r["引取工数"]) for _, r in spo_df.iterrows()}


def test_yama_title_follows_start_time_ascending():
    """山Nは開始時刻の昇順で採番されること(山通番順ではない)。"""
    df = _make_proc_details([1, 2, 3])
    start_times = {1: "25:00", 2: "24:00", 3: "24:30"}
    spo = build_spo_export_df(df, {}, start_times)
    titles = _title_by_yama(spo)
    assert titles[2] == "山1", titles
    assert titles[3] == "山2", titles
    assert titles[1] == "山3", titles


def test_inspection_delay_180_attaches_to_time_predecessor_with_mixed_notation():
    """0:00表記と24:00表記が混在しても照合180秒は正しい直前の山に付くこと。"""
    df = _make_proc_details([1, 2, 3])
    start_times = {1: "24:00", 2: "00:18", 3: "24:30"}
    spo = build_spo_export_df(
        df, {}, start_times, inspection_delay_map={3: True}
    )
    picks = _pick_by_yama(spo)
    base = min(picks.values())
    assert picks[2] == base + 180, picks
    assert picks[1] == base, picks
    assert picks[3] == base, picks


@pytest.mark.xfail(reason="Issue #44: HH:MM文字列では 00:10 と 24:10 が区別できず、_start_secs 導入まで mod 86400 を外せない", strict=True)
def test_serializer_does_not_wrap_start_time_by_one_day():
    """_serialize_lanes_final が出力時に mod 86400 で巻き戻さないこと。"""
    src = (ROOT / "src" / "services" / "process_assigner.py").read_text(encoding="utf-8")
    assert "% 86400" not in src, "mod 86400 が残っている(24:00表記が00:00へ巻き戻る)"
