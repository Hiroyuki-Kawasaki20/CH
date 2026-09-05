"""Issue #129の束ねキー分割理由を読み取り専用で検証する。

実測結果: 分割グループ45件 / 行増加145行 /
山通番+NONYUHIBIN:37件、山通番+NONYUHIBIN+UKEIRE:1件、
山通番+NONYUHIBIN+UKEIRE+納入先:7件 /
納入先のみ:0件、NONYUHIBINのみ:0件 /
旧1,351行→新1,496行（期待値との差0）。
"""

from collections import Counter, defaultdict
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.constants import LOCAL_OUTPUT_DIR
from src.services.data_loader import (
    DataManager,
    _resolve_shipments_path,
    get_master_path,
    load_config,
    load_pickup_time_master_xlsx,
)
from src.services.sorter import build_all_mountain_details, run_pipeline
from src.utils.csv_utils import read_csv_ja
from tools.measure_p1_bundle_key_impact import _build_selections


REASON_FIELDS = ("山通番", "NONYUHIBIN", "UKEIRE", "納入先")


def _norm(value) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _new_key(row: dict) -> tuple:
    return (
        _norm(row.get("山通番")),
        _norm(row.get("ストア", row.get("SYUKKASAKI", ""))),
        _norm(row.get("NONYUHIBIN")),
        _norm(row.get("UKEIRE")),
        _norm(row.get("納入先")),
    )


def _old_store_cluster_count(rows: list[dict]) -> int:
    stores = defaultdict(list)
    for row in rows:
        stores[_norm(row.get("ストア", row.get("SYUKKASAKI", "")))].append(row)
    count = 0
    for group in stores.values():
        hinbans = {_norm(row.get("HINBAN")) for row in group}
        count += 1 if len(hinbans) > 1 else len(group)
    return count


def _new_cluster_count(rows: list[dict]) -> int:
    groups = defaultdict(list)
    for row in rows:
        groups[_new_key(row)].append(row)
    count = 0
    for group in groups.values():
        hinbans = {_norm(row.get("HINBAN")) for row in group}
        count += 1 if len(hinbans) > 1 else len(group)
    return count


def _rebuild_details() -> pd.DataFrame:
    config = load_config()
    base_dir = Path(config["base_dir"])
    shipments = read_csv_ja(_resolve_shipments_path(base_dir))
    places = read_csv_ja(base_dir / "出荷場一覧.csv")
    manager = DataManager(shipments, places)
    master_path = get_master_path()
    master = load_pickup_time_master_xlsx(master_path) if master_path.exists() else pd.DataFrame()
    selections = _build_selections(manager)
    _, _, _, group_details, _, size1_details, _ = run_pipeline(
        manager,
        selections,
        int(config.get("height_cap", 2450)),
        "UKEIRE",
        master_df=master,
        return_lane_end_times=True,
    )
    return build_all_mountain_details(group_details, size1_details)


def audit(details: pd.DataFrame) -> tuple[pd.DataFrame, Counter, list[tuple[str, str]]]:
    rows = details.to_dict(orient="records")
    by_store = defaultdict(list)
    for row in rows:
        by_store[_norm(row.get("ストア", row.get("SYUKKASAKI", "")))].append(row)

    records = []
    reason_counts = Counter()
    dest_pairs = set()
    nony_pairs = set()
    total_increase = 0
    for store, group in by_store.items():
        new_keys = {_new_key(row) for row in group}
        if len(new_keys) < 2:
            continue
        varying = tuple(field for field in REASON_FIELDS if len({_norm(row.get(field)) for row in group}) > 1)
        reason_label = "+".join(varying) if varying else "なし"
        reason_counts[reason_label] += 1
        old_count = _old_store_cluster_count(group)
        new_count = _new_cluster_count(group)
        increase = new_count - old_count
        total_increase += increase
        if reason_label == "納入先":
            values = sorted({_norm(row.get("納入先")) for row in group})
            if len(values) >= 2:
                dest_pairs.add((values[0], values[1]))
        if reason_label == "NONYUHIBIN":
            values = sorted({_norm(row.get("NONYUHIBIN")) for row in group})
            if len(values) >= 2:
                nony_pairs.add((values[0], values[1]))
        records.append({
            "ストア": store,
            "山通番": "/".join(sorted({_norm(row.get("山通番")) for row in group})),
            "原因フィールド": reason_label,
            "旧パレット行数": old_count,
            "新パレット行数": new_count,
            "パレット行数増分": increase,
            "NONYUHIBIN": "/".join(sorted({_norm(row.get("NONYUHIBIN")) for row in group})),
            "UKEIRE": "/".join(sorted({_norm(row.get("UKEIRE")) for row in group})),
            "納入先": "/".join(sorted({_norm(row.get("納入先")) for row in group})),
        })
    return pd.DataFrame(records), reason_counts, [("納入先", p) for p in sorted(dest_pairs)] + [("NONYUHIBIN", p) for p in sorted(nony_pairs)]


def main() -> None:
    details = _rebuild_details()
    report, reason_counts, pairs = audit(details)
    output = Path(LOCAL_OUTPUT_DIR) / "bundle_key_split_reason_audit.csv"
    report.to_csv(output, index=False, encoding="utf-8-sig")
    print("原因フィールド別件数（分割グループ単位）")
    for reason, count in sorted(reason_counts.items()):
        print(f"{reason}: {count}件")
    print("\nA/B 値ペア（最大20組）")
    for field in ("納入先", "NONYUHIBIN"):
        print(f"{field} のみが違う:")
        for pair_field, pair in [item for item in pairs if item[0] == field][:20]:
            print(f"  {pair[0]!r} と {pair[1]!r}")
    total_increase = int(report["パレット行数増分"].sum()) if not report.empty else 0
    print(f"\n分割グループ数: {len(report)}")
    print(f"合計行増加数: {total_increase}")
    print(f"前回計測値145との差: {total_increase - 145}")
    print(f"CSV: {output}")


if __name__ == "__main__":
    main()
