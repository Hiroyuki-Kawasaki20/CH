import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from src.services import sorter
from src.services.data_loader import DataManager, _resolve_shipments_path, get_master_path, load_config, load_pickup_time_master_xlsx
from src.services.sorter import run_pipeline
from src.utils.csv_utils import read_csv_ja
from tools.measure_p1_bundle_key_impact import _build_selections

orig_single = sorter._match_units_with_layer_rules_single_pass
calls = []

def wrapped_single(units, height_cap):
    id_map = orig_single(units, height_cap)
    all_ids = set(units["山ID"].astype(int)) if units is not None and not units.empty else set()
    matched_ids = set(id_map.keys()) | set(id_map.values())
    calls.append({
        "unit_count": len(all_ids),
        "id_map_count": len(id_map),
        "leftover_count_after_call": len(all_ids - matched_ids),
        "leftover_ids_after_call": sorted(all_ids - matched_ids)[:20],
    })
    return id_map

sorter._match_units_with_layer_rules_single_pass = wrapped_single

config = load_config()
base_dir = Path(str(config.get("base_dir", "")))
shipments = read_csv_ja(_resolve_shipments_path(base_dir))
places = read_csv_ja(base_dir / "出荷場一覧.csv")
manager = DataManager(shipments, places)
master = load_pickup_time_master_xlsx(get_master_path())
run_pipeline(manager, _build_selections(manager), int(config.get("height_cap", 2450)), "UKEIRE", master_df=master, return_lane_end_times=True)

sorter._match_units_with_layer_rules_single_pass = orig_single

print(f"single_pass call count: {len(calls)}")
for i, call in enumerate(calls, 1):
    print(f"call{i}: unit_count={call['unit_count']} id_map_count={call['id_map_count']} leftover_count_after_call={call['leftover_count_after_call']} sample_leftover_ids={call['leftover_ids_after_call']}")
