"""
Qt Models for QML data binding
"""
from typing import List, Dict, Any, Optional
from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot, QObject
)


class TileListModel(QAbstractListModel):
    """Model for tile data - exposed to QML"""
    
    # Role names for QML access
    IdRole = Qt.UserRole + 1
    ProcessRole = Qt.UserRole + 2
    VendorRole = Qt.UserRole + 3
    Bin2Role = Qt.UserRole + 4
    StartRole = Qt.UserRole + 5
    WorkSecRole = Qt.UserRole + 6
    PalletsRole = Qt.UserRole + 7
    HeightSumRole = Qt.UserRole + 8
    ViolationRole = Qt.UserRole + 9
    ViolationReasonRole = Qt.UserRole + 10
    
    tilesChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tiles: List[dict] = []
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._tiles)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._tiles):
            return None
        
        tile = self._tiles[index.row()]
        
        role_map = {
            self.IdRole: "id",
            self.ProcessRole: "process",
            self.VendorRole: "vendor",
            self.Bin2Role: "bin2",
            self.StartRole: "start",
            self.WorkSecRole: "work_sec",
            self.PalletsRole: "pallets",
            self.HeightSumRole: "height_sum",
            self.ViolationRole: "violation",
            self.ViolationReasonRole: "violation_reason",
        }
        
        if role in role_map:
            return tile.get(role_map[role], "")
        
        return None
    
    def roleNames(self) -> Dict[int, bytes]:
        return {
            self.IdRole: b"tileId",
            self.ProcessRole: b"process",
            self.VendorRole: b"vendor",
            self.Bin2Role: b"bin2",
            self.StartRole: b"start",
            self.WorkSecRole: b"workSec",
            self.PalletsRole: b"pallets",
            self.HeightSumRole: b"heightSum",
            self.ViolationRole: b"violation",
            self.ViolationReasonRole: b"violationReason",
        }
    
    def set_tiles(self, tiles: List[dict]):
        """Replace all tiles"""
        self.beginResetModel()
        self._tiles = tiles.copy()
        self.endResetModel()
        self.tilesChanged.emit()
    
    @Slot(int, result="QVariant")
    def get(self, index: int) -> dict:
        """Get tile at index"""
        if 0 <= index < len(self._tiles):
            return self._tiles[index]
        return {}


class LaneListModel(QAbstractListModel):
    """Model for lane/process data with gauge info"""
    
    ProcessRole = Qt.UserRole + 1
    HeightSumRole = Qt.UserRole + 2
    HeightCapRole = Qt.UserRole + 3
    CountRole = Qt.UserRole + 4
    MaxCountRole = Qt.UserRole + 5
    OverflowRole = Qt.UserRole + 6
    
    lanesChanged = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lanes: List[dict] = []
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._lanes)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._lanes):
            return None
        
        lane = self._lanes[index.row()]
        
        role_map = {
            self.ProcessRole: "process",
            self.HeightSumRole: "heightSum",
            self.HeightCapRole: "heightCap",
            self.CountRole: "count",
            self.MaxCountRole: "maxCount",
            self.OverflowRole: "overflow",
        }
        
        if role in role_map:
            return lane.get(role_map[role], "")
        
        return None
    
    def roleNames(self) -> Dict[int, bytes]:
        return {
            self.ProcessRole: b"process",
            self.HeightSumRole: b"heightSum",
            self.HeightCapRole: b"heightCap",
            self.CountRole: b"count",
            self.MaxCountRole: b"maxCount",
            self.OverflowRole: b"overflow",
        }
    
    def set_lanes(self, lanes: List[str], stats: Dict[str, dict]):
        """Set lanes with statistics"""
        self.beginResetModel()
        self._lanes = []
        for proc in lanes:
            lane_data = {"process": proc}
            if proc in stats:
                lane_data.update(stats[proc])
            else:
                lane_data.update({
                    "heightSum": 0, "heightCap": 2450,
                    "count": 0, "maxCount": 8, "overflow": False
                })
            self._lanes.append(lane_data)
        self.endResetModel()
        self.lanesChanged.emit()
