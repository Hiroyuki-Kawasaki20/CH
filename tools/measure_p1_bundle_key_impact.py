"""P1の束ねキー変更影響を読み取り専用で計測する。"""

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.constants import LOCAL_OUTPUT_DIR, PROC_MAIN
from src.services.data_loader import DataManager, get_master_path, load_pickup_time_master_xlsx, load_config, _resolve_shipments_path
from src.services.exporter import build_spo_export_df
from src.services.scheduler import cluster_by_store
from src.services.sorter import build_all_mountain_details, run_pipeline
from src.utils.csv_utils import read_csv_ja


def _new_key_cluster(rows):
    """P1候補キーで束ねるローカル比較実装。cluster_by_store本体は変更しない。"""
    groups = {}
    for row in rows:
        key = (
            row.get("山通番", ""), row.get("ストア", row.get("SYUKKASAKI", "")),
            row.get("NONYUHIBIN", ""), row.get("UKEIRE", ""), row.get("納入先", ""),
        )
        groups.setdefault(key, []).append(row)
    result = []
    for group in groups.values():
        hinbans = {str(row.get("HINBAN", "")).strip() for row in group}
        if len(hinbans) <= 1:
            result.extend(group)
            continue
        merged = dict(group[0])
        merged["_merged_rows"] = [dict(row) for row in group]
        result.append(merged)
    return result


def _build_selections(data_manager):
    selections = []
    for _, place in data_manager.df_places.iterrows():
        route = str(place.get("便名", "")).strip()
        receipt = str(place.get("受入", "")).strip()
        for order in data_manager.get_orders_for_route(route, ukeire=receipt):
            selections.append({"便名": route, "受入": receipt, "オーダー": order, "ukeire": receipt})
    return selections


def measure(base_dir: Path, output_path: Path) -> dict:
    shipment_path = _resolve_shipments_path(base_dir)
    places_path = base_dir / "出荷場一覧.csv"
    shipments = read_csv_ja(shipment_path)
    places = read_csv_ja(places_path)
    manager = DataManager(shipments, places)
    config = load_config()
    master_path = get_master_path()
    master = load_pickup_time_master_xlsx(master_path) if master_path.exists() else pd.DataFrame()
    selections = _build_selections(manager)
    _, _, _, group_details, _, size1_details, _ = run_pipeline(
        manager, selections, int(config.get("height_cap", 2450)), "UKEIRE", master_df=master,
        return_lane_end_times=True,
    )
    details = build_all_mountain_details(group_details, size1_details)
    current = pd.DataFrame(cluster_by_store(details.to_dict(orient="records")))
    proposed = pd.DataFrame(_new_key_cluster(details.to_dict(orient="records")))
    current_counts = current.groupby("山通番").size().to_dict()
    proposed_counts = proposed.groupby("山通番").size().to_dict()
    current_spo = build_spo_export_df(current, {}, {})
    proposed_spo = build_spo_export_df(proposed, {}, {})
    current_cost = current_spo.set_index("グループ番号")["引取工数"].to_dict()
    proposed_cost = proposed_spo.set_index("グループ番号")["引取工数"].to_dict()
    rows = []
    for yama, new_count in proposed_counts.items():
        old_count = int(current_counts.get(yama, 0))
        if new_count <= old_count:
            continue
        sub = details[details["山通番"] == yama].iloc[0]
        rows.append({
            "山通番": int(yama), "タイトル": f"山{int(yama)}", "工程": PROC_MAIN,
            "NONYUHIBIN": sub.get("NONYUHIBIN", ""), "UKEIRE": sub.get("UKEIRE", ""),
            "納入先": sub.get("納入先", ""), "ストア": sub.get("ストア", ""),
            "現行パレット数": old_count, "新パレット数": int(new_count),
            "パレット数増分": int(new_count - old_count),
            "引取工数の増分": int(proposed_cost.get(yama, 0) - current_cost.get(yama, 0)),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False, encoding="utf-8-sig")
    return {"rows": rows, "output": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    config = load_config()
    base_dir = args.base_dir or Path(config.get("base_dir", ""))
    if not base_dir:
        raise SystemExit("base_dirを指定してください")
    result = measure(base_dir, Path(LOCAL_OUTPUT_DIR) / "p1_bundle_key_impact_audit.csv")
    rows = result["rows"]
    print(f"束ねが解ける行数の合計: {sum(row['パレット数増分'] for row in rows)}")
    print(f"影響する山通番とタイトル: {[(row['山通番'], row['タイトル']) for row in rows]}")
    print(f"影響する便: {sorted({str(row['NONYUHIBIN']) for row in rows})}")
    print(f"引取工数の増分合計: {sum(row['引取工数の増分'] for row in rows)}")
    print(f"CSV: {result['output']}")


if __name__ == "__main__":
    main()
