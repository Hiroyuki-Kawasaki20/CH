"""
Forward Scheduling and Violation Detection Logic

Algorithm:
1. Base start = arrival(vendor, prev_bin) + 10min margin
2. Sequential forward scheduling within each process
3. Deadline = arrival(vendor, bin) - 10min margin
4. Violations marked for mountains exceeding deadline
"""
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
SNAP_MINUTES = 30
MARGIN_MINUTES = 10

TIME_RANGE = {
    "day": ("06:00", "16:30"),
    "night": ("16:00", "02:30")
}

PROCESS_LIST = ["1", "2", "3", "4"]


class ForwardScheduler:
    """
    Forward scheduling engine for setboard tiles.
    
    Schedules tiles based on:
    - Previous bin arrival + margin as base start
    - Sequential placement within each process
    - 30-minute snap grid
    - Violation detection against deadline
    """
    
    def __init__(self):
        pass
    
    def schedule_all(self, tiles: List[dict], arrival_master: Dict[tuple, str], 
                     shift: str = "day") -> List[dict]:
        """
        Schedule all tiles with forward scheduling algorithm.
        
        Args:
            tiles: List of tile dictionaries
            arrival_master: Dict of (vendor, bin2) -> arrival time "HH:MM"
            shift: "day" or "night"
        
        Returns:
            Updated tiles with start times and violation flags
        """
        # Group tiles by (vendor, bin2)
        groups: Dict[tuple, List[dict]] = {}
        for tile in tiles:
            key = (tile["vendor"], tile["bin2"])
            if key not in groups:
                groups[key] = []
            groups[key].append(tile)
        
        result = []
        for (vendor, bin2), group_tiles in groups.items():
            scheduled = self.schedule_group(group_tiles, vendor, bin2, 
                                            arrival_master, shift)
            result.extend(scheduled)
        
        return result
    
    def schedule_group(self, tiles: List[dict], vendor: str, bin2: str,
                       arrival_master: Dict[tuple, str], shift: str) -> List[dict]:
        """
        Schedule tiles for a single (vendor, bin2) group.
        """
        if not tiles:
            return tiles
        
        shift_from, shift_to = TIME_RANGE[shift]
        shift_start_min = self._hhmm_to_minutes(shift_from)
        
        # Get base start time (prev bin arrival + margin)
        base_start_min = self._get_base_start(vendor, bin2, arrival_master, 
                                               shift_start_min, shift)
        
        # Get deadline (current bin arrival - margin)
        deadline_min = self._get_deadline(vendor, bin2, arrival_master, shift)
        
        # Schedule each process independently
        for proc in PROCESS_LIST:
            proc_tiles = [t for t in tiles if t["process"] == proc]
            if not proc_tiles:
                continue
            
            # Sort by current start time to maintain relative order
            proc_tiles.sort(key=lambda t: self._hhmm_to_minutes(t.get("start", "00:00")))
            
            # Forward schedule
            current_min = self._snap_to_grid(base_start_min)
            
            for tile in proc_tiles:
                tile["start"] = self._minutes_to_hhmm(current_min)
                work_min = tile.get("work_sec", 0) / 60
                end_min = current_min + work_min
                
                # Check violation
                tile["violation"] = False
                tile["violation_reason"] = ""
                
                if deadline_min is not None and end_min > deadline_min:
                    tile["violation"] = True
                    over_min = int(end_min - deadline_min)
                    deadline_str = self._minutes_to_hhmm(deadline_min)
                    tile["violation_reason"] = f"締切超過: {deadline_str} を{over_min}分超過"
                
                # Next tile starts after this one (snapped)
                current_min = self._snap_to_grid(end_min)
        
        return tiles
    
    def _get_base_start(self, vendor: str, bin2: str, 
                        arrival_master: Dict[tuple, str],
                        shift_start_min: int, shift: str) -> int:
        """
        Get base start time for scheduling.
        = arrival(vendor, prev_bin) + margin
        If no prev_bin, use shift start time.
        """
        prev_bin2 = self._get_prev_bin(bin2)
        
        if prev_bin2 and (vendor, prev_bin2) in arrival_master:
            arrival_str = arrival_master[(vendor, prev_bin2)]
            arrival_min = self._hhmm_to_minutes(arrival_str, shift)
            return arrival_min + MARGIN_MINUTES
        
        # Fallback: shift start time
        return shift_start_min
    
    def _get_deadline(self, vendor: str, bin2: str,
                      arrival_master: Dict[tuple, str], shift: str) -> Optional[int]:
        """
        Get deadline for scheduling.
        = arrival(vendor, bin) - margin
        Returns None if no arrival data.
        """
        if (vendor, bin2) in arrival_master:
            arrival_str = arrival_master[(vendor, bin2)]
            arrival_min = self._hhmm_to_minutes(arrival_str, shift)
            return arrival_min - MARGIN_MINUTES
        
        return None  # No deadline
    
    def _get_prev_bin(self, bin2: str) -> Optional[str]:
        """Get previous bin number (e.g., "02" -> "01")"""
        try:
            bin_num = int(bin2)
            if bin_num > 1:
                return f"{bin_num - 1:02d}"
        except ValueError:
            pass
        return None
    
    def _snap_to_grid(self, minutes: float) -> int:
        """Snap to 30-minute grid"""
        return round(minutes / SNAP_MINUTES) * SNAP_MINUTES
    
    def _hhmm_to_minutes(self, time_str: str, shift: str = "day") -> int:
        """
        Convert "HH:MM" to minutes from midnight.
        Handles day-crossing for night shift.
        """
        try:
            parts = time_str.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            total = hours * 60 + minutes
            
            # Night shift: times < 06:00 are next day
            if shift == "night" and hours < 6:
                total += 24 * 60
            
            return total
        except:
            return 0
    
    def _minutes_to_hhmm(self, minutes: int) -> str:
        """Convert minutes to "HH:MM" format"""
        minutes = int(minutes)
        # Handle day overflow
        if minutes >= 24 * 60:
            minutes -= 24 * 60
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"


def snap_time(time_str: str) -> str:
    """Utility: snap time string to 30-min grid"""
    scheduler = ForwardScheduler()
    minutes = scheduler._hhmm_to_minutes(time_str)
    snapped = scheduler._snap_to_grid(minutes)
    return scheduler._minutes_to_hhmm(snapped)
