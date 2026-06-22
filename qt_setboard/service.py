"""
Service layer - Adapter for existing logic and data management
"""
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

import pandas as pd

# Add parent directory to path for importing existing modules
PARENT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PARENT_DIR))

from schedule import ForwardScheduler, SNAP_MINUTES

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
TIME_RANGE = {
    "day": ("06:00", "16:30"),
    "night": ("16:00", "02:30")
}

PIXELS_PER_MIN = 2

MAX_MOUNTAINS_PER_PROCESS = {"1": 8, "2": 8, "3": 6, "4": 6}
HEIGHT_CAP_PER_PROCESS = {"1": 2450, "2": 2450, "3": 2450, "4": 2450}

PROCESS_LIST = ["1", "2", "3", "4"]


class SetboardService:
    """
    Service class that bridges UI with existing logic.
    Manages tile data and scheduling.
    """
    
    def __init__(self):
        self._tiles: Dict[int, dict] = {}  # id -> tile data
        self._shift = "day"
        self._scheduler = ForwardScheduler()
        self._arrival_master: Dict[tuple, str] = {}  # (vendor, bin2) -> arrival time
        self._export_dir = "exports"
        
        # Try to load existing data from parent app context
        self._load_initial_data()
    
    def _load_initial_data(self):
        """Load initial data - placeholder for integration with existing code"""
        # In real integration, this would call:
        # - run_pipeline()
        # - build_per_process_mountain_rows()
        # etc.
        
        # For prototype, create sample data
        self._create_sample_data()
    
    def _create_sample_data(self):
        """Create sample tiles for demonstration"""
        sample_tiles = [
            # Process 1
            {"id": 1, "process": "1", "vendor": "納入先A", "bin2": "01", 
             "start": "06:30", "work_sec": 1800, "pallets": 6, "height_sum": 1800},
            {"id": 2, "process": "1", "vendor": "納入先A", "bin2": "01",
             "start": "07:00", "work_sec": 2400, "pallets": 8, "height_sum": 2100},
            {"id": 3, "process": "1", "vendor": "納入先B", "bin2": "02",
             "start": "09:00", "work_sec": 1200, "pallets": 4, "height_sum": 1200},
            
            # Process 2
            {"id": 4, "process": "2", "vendor": "納入先A", "bin2": "01",
             "start": "06:30", "work_sec": 2100, "pallets": 7, "height_sum": 1900},
            {"id": 5, "process": "2", "vendor": "納入先C", "bin2": "03",
             "start": "10:00", "work_sec": 1500, "pallets": 5, "height_sum": 1500},
            
            # Process 3
            {"id": 6, "process": "3", "vendor": "納入先A", "bin2": "01",
             "start": "06:30", "work_sec": 1800, "pallets": 6, "height_sum": 2000},
            {"id": 7, "process": "3", "vendor": "納入先B", "bin2": "02",
             "start": "08:30", "work_sec": 2700, "pallets": 9, "height_sum": 2400},
            
            # Process 4
            {"id": 8, "process": "4", "vendor": "納入先A", "bin2": "01",
             "start": "07:00", "work_sec": 1200, "pallets": 4, "height_sum": 1100},
            {"id": 9, "process": "4", "vendor": "納入先D", "bin2": "04",
             "start": "11:00", "work_sec": 3600, "pallets": 12, "height_sum": 2600},  # Will be violation
        ]
        
        # Sample arrival master
        self._arrival_master = {
            ("納入先A", "01"): "08:30",
            ("納入先A", "02"): "11:00",
            ("納入先B", "02"): "10:00",
            ("納入先C", "03"): "12:00",
            ("納入先D", "04"): "12:00",
        }
        
        for tile in sample_tiles:
            tile["violation"] = False
            tile["violation_reason"] = ""
            self._tiles[tile["id"]] = tile
        
        # Run initial scheduling
        self._run_scheduling()
    
    def _run_scheduling(self):
        """Run forward scheduling and violation detection"""
        tiles_list = list(self._tiles.values())
        updated_tiles = self._scheduler.schedule_all(
            tiles_list, 
            self._arrival_master, 
            self._shift
        )
        for tile in updated_tiles:
            self._tiles[tile["id"]] = tile
    
    def load_board(self, shift: str = "day") -> dict:
        """Load board state for given shift"""
        self._shift = shift
        time_range = TIME_RANGE[shift]
        
        # Filter tiles for current shift (simplified - show all for now)
        tiles = list(self._tiles.values())
        
        # Calculate lane statistics
        lane_stats = self._calc_lane_stats(tiles)
        
        return {
            "shift": shift,
            "lanes": PROCESS_LIST,
            "timeRange": {"from": time_range[0], "to": time_range[1]},
            "pixelsPerMin": PIXELS_PER_MIN,
            "tiles": tiles,
            "laneStats": lane_stats
        }
    
    def _calc_lane_stats(self, tiles: List[dict]) -> Dict[str, dict]:
        """Calculate statistics per lane for gauge display"""
        stats = {}
        for proc in PROCESS_LIST:
            proc_tiles = [t for t in tiles if t["process"] == proc]
            height_sum = sum(t.get("height_sum", 0) for t in proc_tiles)
            count = len(proc_tiles)
            cap = HEIGHT_CAP_PER_PROCESS.get(proc, 2450)
            max_count = MAX_MOUNTAINS_PER_PROCESS.get(proc, 8)
            
            stats[proc] = {
                "heightSum": height_sum,
                "heightCap": cap,
                "count": count,
                "maxCount": max_count,
                "overflow": height_sum > cap or count > max_count
            }
        return stats
    
    def reassign(self, tile_id: int, new_process: str, new_start: str) -> dict:
        """
        Reassign a tile to new process and/or start time.
        Triggers rescheduling for affected vendor/bin group.
        """
        if tile_id not in self._tiles:
            return self.load_board(self._shift)
        
        tile = self._tiles[tile_id]
        old_process = tile["process"]
        old_vendor = tile["vendor"]
        old_bin2 = tile["bin2"]
        
        # Update tile
        tile["process"] = new_process
        tile["start"] = self._snap_time(new_start)
        
        # Reschedule all tiles for same vendor/bin across all processes
        self._reschedule_group(old_vendor, old_bin2)
        
        return self.load_board(self._shift)
    
    def _reschedule_group(self, vendor: str, bin2: str):
        """Reschedule all tiles for a vendor/bin group"""
        # Get all tiles for this vendor/bin
        group_tiles = [t for t in self._tiles.values() 
                       if t["vendor"] == vendor and t["bin2"] == bin2]
        
        if not group_tiles:
            return
        
        # Run scheduling on this group
        updated = self._scheduler.schedule_group(
            group_tiles,
            vendor,
            bin2,
            self._arrival_master,
            self._shift
        )
        
        for tile in updated:
            self._tiles[tile["id"]] = tile
    
    def _snap_time(self, time_str: str) -> str:
        """Snap time to 30-minute grid"""
        try:
            parts = time_str.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            
            total_min = hours * 60 + minutes
            snapped = round(total_min / SNAP_MINUTES) * SNAP_MINUTES
            
            h = (snapped // 60) % 24
            m = snapped % 60
            return f"{h:02d}:{m:02d}"
        except:
            return time_str
    
    def get_tile_tooltip(self, tile_id: int) -> str:
        """Get detailed tooltip for a tile"""
        if tile_id not in self._tiles:
            return ""
        
        t = self._tiles[tile_id]
        lines = [
            f"山通番: {t['id']}",
            f"工程: {t['process']}工程",
            f"納入先: {t['vendor']}",
            f"便: {t['bin2']}",
            f"開始: {t['start']}",
            f"工数: {t['work_sec']}秒 ({t['work_sec']//60}分)",
            f"パレット: {t['pallets']}",
            f"高さ計: {t['height_sum']}mm",
        ]
        
        if t.get("violation"):
            lines.append(f"⚠ {t.get('violation_reason', '違反')}")
        
        return "\n".join(lines)
    
    def export_spo(self) -> str:
        """Export SPO file - placeholder for integration"""
        os.makedirs(self._export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._export_dir, f"SPO_{timestamp}.xlsx")
        
        # Create DataFrame from tiles
        df = pd.DataFrame(list(self._tiles.values()))
        df.to_excel(path, index=False)
        
        return path


# ─────────────────────────────────────────────
# Legacy API wrappers (for compatibility)
# ─────────────────────────────────────────────
def attach_pickup_start_time_wrapper(df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """Wrapper for existing attach_pickup_start_time - now uses forward scheduling"""
    # This would integrate with the existing function
    # For now, return as-is
    return df


def adjust_pickup_time_for_same_bin_wrapper(df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """Wrapper for existing adjust_pickup_time_for_same_bin"""
    return df
