# -*- coding: utf-8 -*-
"""リリーフ工程の空き窓への前詰め救済 診断ツール（読み取り専用）。

usage:
  python scripts\\check_relief_diag.py
  python scripts\\check_relief_diag.py --spo <spo.xlsx> --master <master.xlsx>

既定では tests/fixtures/issue97 の実データスナップショットを使う。
ファイルへの書き込みは一切行わない。
"""
from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services import process_assigner as pa
from src.services.data_loader import load_pickup_time_master_xlsx

try:
    from tests.unit.test_relief_earliest_start import (
        _build_detail_rows_from_spo_vendor_aware as _build_details,
    )
except Exception:
    import importlib.util

    _p = ROOT / "tests" / "unit" / "test_relief_earliest_start.py"
    _spec = importlib.util.spec_from_file_location("_relief_helper", _p)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _build_details = _mod._build_detail_rows_from_spo_vendor_aware

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "issue97"
BAR = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser(description="relief idle-gap front-pack diagnostics")
    ap.add_argument("--spo", default=str(FIXTURE_DIR / "spo_upload_snapshot.xlsx"))
    ap.add_argument("--master", default=str(FIXTURE_DIR / "nyusha_master_snapshot.xlsx"))
    args = ap.parse_args()

    spo_path, master_path = Path(args.spo), Path(args.master)
    for p in (spo_path, master_path):
        if not p.exists():
            print(f"[ERROR] file not found: {p}")
            return 2

    print(BAR)
    print("[INPUT] spo    :", spo_path)
    print("[INPUT] master :", master_path)

    spo_df = pd.read_excel(spo_path, engine="openpyxl")
    master_df = load_pickup_time_master_xlsx(master_path)
    details_df = _build_details(spo_df, master_df)
    proc_details = pa.compute_proc_details(details_df)

    diag: list = []
    kwargs = {"previous_lane_end_times": None}
    if "front_pack_diag" in inspect.signature(pa.assign_processes_by_arrival_time).parameters:
        kwargs["front_pack_diag"] = diag
    else:
        print("[WARN] front_pack_diag parameter not found; diag will be empty")

    output = pa.assign_processes_by_arrival_time(proc_details, master_df, **kwargs)

    uniq = output[["山通番", "山工程", "実開始時間", "実終了時間"]].drop_duplicates("山通番")

    dest, hbin = {}, {}
    for y in uniq["山通番"]:
        rows = details_df.loc[details_df["山通番"] == y]
        if rows.empty:
            continue
        dest[int(y)] = pa._normalize_dest_name(str(rows["納入先"].iloc[0]))
        hbin[int(y)] = str(rows["NONYUHIBIN"].iloc[0]).strip()[-2:]

    print(BAR)
    print("[SUMMARY] 工程別の山数")
    for lane, rows in uniq.groupby("山工程"):
        print(f"  {lane:<10} : {len(rows):>3} 山")

    print(BAR)
    print("[DETAIL] リリーフ / あふれ 工程の明細")
    for lane, rows in uniq.groupby("山工程"):
        if ("リリーフ" not in str(lane)) and ("あふれ" not in str(lane)):
            continue
        print(f"--- {lane} ---")
        for _, r in rows.sort_values("実開始時間").iterrows():
            y = int(r["山通番"])
            print(
                f"  山{y:>3}  {r['実開始時間']} - {r['実終了時間']}  "
                f"{dest.get(y, '?')}/{hbin.get(y, '?')}便"
            )

    print(BAR)
    print(f"[DIAG] front_pack_diag records: {len(diag)}")
    for i, e in enumerate(diag, 1):
        print(f"  {i:>3}. {e!r}")

    hino_recs = [e for e in diag if "日野" in repr(e)]
    print(f"[DIAG] 日野 を含む記録: {len(hino_recs)}")
    for e in hino_recs:
        print("   *", repr(e))

    print(BAR)
    if any("日野除外" in repr(e) for e in diag):
        print("[NG] 「日野除外」の記録が残っています（Patch B が効いていない可能性）")
        return 1
    print("[OK] 「日野除外」の記録なし（Issue #117 の期待どおり）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())