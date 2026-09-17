# tools/run_trace_135.py
"""Issue #135 フェーズ2: TRACE#135 ログ採取 ＋ 挙動不変（OFF/ON）検証。

読み取り専用。既存モジュールは一切変更しない。
  1) sorter の import より前に CH_TRACE_135=1 を設定する（TRACE_MIX は import 時に確定するため）
  2) src.services.sorter ロガーだけ DEBUG + FileHandler。ルートロガーには触らない
  3) 同一プロセスで トレースOFF → トレースON の2回パイプラインを回し、
     「山通番ごとのパレット構成」が完全一致することを SHA-256 で証明する
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

# ---- (1) sorter の import より前にトレースを有効化する。この順序が本質 ----
os.environ["CH_TRACE_135"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from src.models.constants import LOCAL_OUTPUT_DIR  # noqa: E402
from src.services import sorter  # noqa: E402  TRACE_MIX を明示切替するため module 参照で持つ
from src.services.data_loader import (  # noqa: E402
    DataManager,
    _resolve_shipments_path,
    get_master_path,
    load_config,
    load_pickup_time_master_xlsx,
)
from src.services.exporter import build_spo_export_df  # noqa: E402
from src.services.scheduler import cluster_by_store  # noqa: E402
from src.services.sorter import build_all_mountain_details, run_pipeline  # noqa: E402
from src.utils.csv_utils import read_csv_ja  # noqa: E402
from tools.measure_p1_bundle_key_impact import _build_selections  # noqa: E402

TRACE_LOGGER_NAME = "src.services.sorter"
# 山通番ごとの「パレット構成」を比べるための列（存在するものだけ使う）
COMPOSITION_COLS = (
    "納入先", "NONYUHIBIN", "UKEIRE", "ストア", "HINBAN",
    "サイズ種類", "高さ", "移動工数",
)


def setup_trace_logging(log_path: Path) -> logging.FileHandler:
    """sorter ロガーだけを DEBUG にしてファイルへ出す。ルートロガーは変更しない。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    lg = logging.getLogger(TRACE_LOGGER_NAME)
    lg.setLevel(logging.DEBUG)   # ← root には触らない
    lg.addHandler(handler)
    lg.propagate = False         # ← 既存のコンソール出力を汚さない

    # to_string() が省略されないようにする（表示設定のみ・ロジック非影響）
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 400)
    pd.set_option("display.max_colwidth", 200)
    return handler


def load_inputs(base_dir: Path):
    shipments = read_csv_ja(_resolve_shipments_path(base_dir))
    places = read_csv_ja(base_dir / "出荷場一覧.csv")
    manager = DataManager(shipments, places)
    master_path = get_master_path()
    master = load_pickup_time_master_xlsx(master_path) if master_path.exists() else pd.DataFrame()
    return manager, master


def filter_selections(selections: list, route: str | None, ukeire: str | None, nonyuhibin_prefix: str | None) -> list:
    """Beforeベースラインとスコープを合わせるための subset（_build_selections の戻り値のみに作用、src/ は不使用）。"""
    out = selections
    if route:
        routes = {r.strip() for r in route.split(",") if r.strip()}
        out = [s for s in out if str(s.get("便名", "")).strip() in routes]
    if ukeire:
        ukeires = {u.strip() for u in ukeire.split(",") if u.strip()}
        out = [s for s in out if str(s.get("受入", s.get("ukeire", ""))).strip() in ukeires]
    if nonyuhibin_prefix:
        prefixes = tuple(p.strip() for p in nonyuhibin_prefix.split(",") if p.strip())
        out = [s for s in out if str(s.get("オーダー", "")).strip().startswith(prefixes)]
    return out


def build_details(base_dir: Path, height_cap: int, trace: bool, scope: dict | None = None) -> pd.DataFrame:
    """トレース ON/OFF を切り替えて 1 回パイプラインを回し、全山の明細を返す。"""
    sorter.TRACE_MIX = bool(trace)
    manager, master = load_inputs(base_dir)          # 状態持ち越しを避けて毎回作り直す
    selections = _build_selections(manager)
    if scope:
        selections = filter_selections(selections, scope.get("route"), scope.get("ukeire"), scope.get("nonyuhibin_prefix"))
    _, _, _, group_details, _, size1_details, _ = run_pipeline(
        manager,
        selections,
        int(height_cap),
        "UKEIRE",
        master_df=master,
        return_lane_end_times=True,
    )
    return build_all_mountain_details(group_details, size1_details)


def yama_composition(details: pd.DataFrame) -> pd.DataFrame:
    """山通番 → パレット構成（順不同で正規化した文字列）。挙動不変の判定に使う。"""
    if details is None or details.empty:
        return pd.DataFrame(columns=["山通番", "パレット数", "構成"])
    cols = [c for c in COMPOSITION_COLS if c in details.columns]
    work = details.copy()
    work["山通番"] = pd.to_numeric(work["山通番"], errors="coerce").fillna(0).astype(int)
    for c in cols:
        work[c] = work[c].astype(str).str.strip()
    work["_item"] = work[cols].agg("|".join, axis=1)
    cnt = work.groupby("山通番")["_item"].size().rename("パレット数")
    comp = work.groupby("山通番")["_item"].apply(lambda s: "; ".join(sorted(s))).rename("構成")
    return pd.concat([cnt, comp], axis=1).reset_index()


def fingerprint(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Issue #135 TRACE#135 ログ採取")
    parser.add_argument("--base-dir", type=Path, default=None, help="入力CSVのフォルダ（省略時 config の base_dir）")
    parser.add_argument("--log", type=Path, default=REPO_ROOT / "trace_135.log", help="トレースログ出力先")
    parser.add_argument("--outdir", type=Path, default=Path(LOCAL_OUTPUT_DIR), help="CSV出力先")
    parser.add_argument("--height-cap", type=int, default=None, help="高さ上限（省略時 config→2450）")
    parser.add_argument("--no-selfcheck", action="store_true", help="OFF実行を省略して ON のみ回す")
    parser.add_argument("--spo", action="store_true", help="Beforeベースライン比較用に SPO形式CSV も出力")
    parser.add_argument("--route", type=str, default=None, help="便名で絞り込む（カンマ区切りで複数指定可）")
    parser.add_argument("--ukeire", type=str, default=None, help="受入で絞り込む（カンマ区切りで複数指定可）")
    parser.add_argument("--nonyuhibin-prefix", type=str, default=None, help="NONYUHIBIN(オーダー)の前方一致で絞り込む（カンマ区切りで複数指定可）")
    args = parser.parse_args(argv)

    config = load_config()
    base_dir = args.base_dir or Path(str(config.get("base_dir", "")))
    if not str(base_dir):
        raise SystemExit("base_dir を指定してください（--base-dir）")
    height_cap = args.height_cap or int(config.get("height_cap", 2450))
    args.outdir.mkdir(parents=True, exist_ok=True)
    scope = {"route": args.route, "ukeire": args.ukeire, "nonyuhibin_prefix": args.nonyuhibin_prefix}

    handler = setup_trace_logging(args.log)
    try:
        # ---- (A) トレースOFF（＝現行挙動のベースライン。ログは1行も出ない） ----
        off_comp = None
        if not args.no_selfcheck:
            details_off = build_details(base_dir, height_cap, trace=False, scope=scope)
            off_comp = yama_composition(details_off)
            off_comp.to_csv(args.outdir / "trace135_composition_off.csv", index=False, encoding="utf-8-sig")
            details_off.to_csv(args.outdir / "trace135_details_off.csv", index=False, encoding="utf-8-sig")

        # ---- (B) トレースON（ログ採取本番） ----
        details_on = build_details(base_dir, height_cap, trace=True, scope=scope)
        on_comp = yama_composition(details_on)
        on_comp.to_csv(args.outdir / "trace135_composition_on.csv", index=False, encoding="utf-8-sig")
        details_on.to_csv(args.outdir / "trace135_details_on.csv", index=False, encoding="utf-8-sig")

        if args.spo:
            clustered = pd.DataFrame(cluster_by_store(details_on.to_dict(orient="records")))
            build_spo_export_df(clustered, {}, {}).to_csv(
                args.outdir / "trace135_spo_on.csv", index=False, encoding="utf-8-sig"
            )
    finally:
        handler.close()
        logging.getLogger(TRACE_LOGGER_NAME).removeHandler(handler)

    # ---- (C) 挙動不変の判定 ----
    print(f"[入力]   base_dir={base_dir}  height_cap={height_cap}")
    print(f"[ログ]   {args.log}  ({args.log.stat().st_size:,} bytes)" if args.log.exists() else "[ログ] 未生成")
    print(f"[CSV]    {args.outdir}")
    print(f"[ON]     山数={len(on_comp)}  パレット総数={int(on_comp['パレット数'].sum())}  sha256={fingerprint(on_comp)[:16]}")
    if off_comp is None:
        print("[判定]   selfcheck 省略（--no-selfcheck）。Beforeベースラインとの外部 diff を行ってください")
        return 0

    print(f"[OFF]    山数={len(off_comp)}  パレット総数={int(off_comp['パレット数'].sum())}  sha256={fingerprint(off_comp)[:16]}")
    if fingerprint(off_comp) == fingerprint(on_comp):
        print("[判定]   ✅ 挙動不変：山通番ごとのパレット構成が完全一致（SHA-256 一致）")
        return 0

    merged = off_comp.merge(on_comp, on="山通番", how="outer", suffixes=("_OFF", "_ON"), indicator=True)
    ng = merged[(merged["_merge"] != "both") | (merged["構成_OFF"] != merged["構成_ON"])]
    ng_path = args.outdir / "trace135_composition_diff.csv"
    ng.to_csv(ng_path, index=False, encoding="utf-8-sig")
    print(f"[判定]   ❌ 不一致 {len(ng)} 山。差分: {ng_path}")
    print(f"[不一致山通番] {sorted(ng['山通番'].tolist())[:50]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
