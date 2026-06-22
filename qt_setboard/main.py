"""
PySide6/QML Setboard - Main Entry Point
"""
import sys
import os
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType

from models import TileListModel, LaneListModel
from service import SetboardService


class Backend(QObject):
    """Bridge between QML and Python service layer"""
    
    boardChanged = Signal()
    statusMessage = Signal(str)
    
    def __init__(self, service: SetboardService, parent=None):
        super().__init__(parent)
        self._service = service
        self._tile_model = TileListModel()
        self._lane_model = LaneListModel()
        self._shift = "day"
        self._pixels_per_min = 2.0
        self._time_from = "06:00"
        self._time_to = "16:30"
        
    # ─────────────────────────────────────────────
    # Properties exposed to QML
    # ─────────────────────────────────────────────
    @Property(QObject, notify=boardChanged)
    def tileModel(self):
        return self._tile_model
    
    @Property(QObject, notify=boardChanged)
    def laneModel(self):
        return self._lane_model
    
    @Property(str, notify=boardChanged)
    def shift(self):
        return self._shift
    
    @Property(float, notify=boardChanged)
    def pixelsPerMin(self):
        return self._pixels_per_min
    
    @Property(str, notify=boardChanged)
    def timeFrom(self):
        return self._time_from
    
    @Property(str, notify=boardChanged)
    def timeTo(self):
        return self._time_to
    
    # ─────────────────────────────────────────────
    # Slots callable from QML
    # ─────────────────────────────────────────────
    @Slot()
    def loadBoard(self):
        """Load board state for current shift"""
        state = self._service.load_board(self._shift)
        self._apply_state(state)
        self.statusMessage.emit(f"Loaded {self._shift} shift")
    
    @Slot(str)
    def setShift(self, shift: str):
        """Switch between day/night shift"""
        self._shift = shift
        self.loadBoard()
    
    @Slot(int, str, str)
    def reassign(self, tile_id: int, new_process: str, new_start: str):
        """Reassign a tile to new process/start time"""
        state = self._service.reassign(tile_id, new_process, new_start)
        self._apply_state(state)
        self.statusMessage.emit(f"Reassigned tile {tile_id} → {new_process}工程 @ {new_start}")
    
    @Slot(float)
    def setZoom(self, pixels_per_min: float):
        """Change zoom level"""
        self._pixels_per_min = max(0.5, min(10.0, pixels_per_min))
        self.boardChanged.emit()
    
    @Slot()
    def zoomIn(self):
        self.setZoom(self._pixels_per_min * 1.25)
    
    @Slot()
    def zoomOut(self):
        self.setZoom(self._pixels_per_min / 1.25)
    
    @Slot()
    def exportSpo(self):
        """Export SPO file"""
        try:
            path = self._service.export_spo()
            self.statusMessage.emit(f"SPO exported: {path}")
        except Exception as e:
            self.statusMessage.emit(f"Export failed: {e}")
    
    @Slot(int, result=str)
    def getTileTooltip(self, tile_id: int) -> str:
        """Get tooltip text for a tile"""
        return self._service.get_tile_tooltip(tile_id)
    
    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────
    def _apply_state(self, state: dict):
        """Apply BoardState to models"""
        self._shift = state.get("shift", "day")
        tr = state.get("timeRange", {})
        self._time_from = tr.get("from", "06:00")
        self._time_to = tr.get("to", "16:30")
        self._pixels_per_min = state.get("pixelsPerMin", 2.0)
        
        # Update tile model
        tiles = state.get("tiles", [])
        self._tile_model.set_tiles(tiles)
        
        # Update lane model with gauge info
        lanes = state.get("lanes", ["1", "2", "3", "4"])
        lane_stats = state.get("laneStats", {})
        self._lane_model.set_lanes(lanes, lane_stats)
        
        self.boardChanged.emit()


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Setboard Timeline")
    app.setOrganizationName("DIG_Project")
    
    # Create service and backend
    service = SetboardService()
    backend = Backend(service)
    
    # Setup QML engine
    engine = QQmlApplicationEngine()
    
    # Expose backend to QML
    engine.rootContext().setContextProperty("backend", backend)
    
    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    qml_file = qml_dir / "Setboard.qml"
    
    if not qml_file.exists():
        print(f"ERROR: QML file not found: {qml_file}")
        sys.exit(1)
    
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    
    if not engine.rootObjects():
        print("ERROR: Failed to load QML")
        sys.exit(1)
    
    # Initial load
    backend.loadBoard()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
