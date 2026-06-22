// file: qt_setboard/qml/Setboard.qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: root
    visible: true
    width: 1400
    height: 700
    title: "セットボード タイムライン"
    color: "#f5f5f5"

    // ─────────────────────────────────────────────
    // Properties
    // ─────────────────────────────────────────────
    property real pixelsPerMin: backend.pixelsPerMin
    property string timeFrom: backend.timeFrom
    property string timeTo: backend.timeTo
    property string currentShift: backend.shift
    
    property int laneHeight: 120
    property int headerHeight: 50
    property int labelWidth: 80
    property int gaugeWidth: 60

    // ─────────────────────────────────────────────
    // Helper functions
    // ─────────────────────────────────────────────
    function timeToMinutes(timeStr) {
        var parts = timeStr.split(":");
        var h = parseInt(parts[0], 10);
        var m = parseInt(parts[1], 10) || 0;
        var total = h * 60 + m;
        // Night shift: times < 06:00 are next day
        if (currentShift === "night" && h < 6) {
            total += 24 * 60;
        }
        return total;
    }
    
    function minutesToTime(minutes) {
        if (minutes >= 24 * 60) minutes -= 24 * 60;
        var h = Math.floor(minutes / 60) % 24;
        var m = minutes % 60;
        return ("0" + h).slice(-2) + ":" + ("0" + m).slice(-2);
    }
    
    function timeToX(timeStr) {
        var fromMin = timeToMinutes(timeFrom);
        var tileMin = timeToMinutes(timeStr);
        return (tileMin - fromMin) * pixelsPerMin;
    }
    
    function xToTime(x) {
        var fromMin = timeToMinutes(timeFrom);
        var minutes = fromMin + x / pixelsPerMin;
        // Snap to 30 min
        minutes = Math.round(minutes / 30) * 30;
        return minutesToTime(minutes);
    }
    
    function getTimelineWidth() {
        var fromMin = timeToMinutes(timeFrom);
        var toMin = timeToMinutes(timeTo);
        if (toMin <= fromMin) toMin += 24 * 60;  // Day crossing
        return (toMin - fromMin) * pixelsPerMin;
    }
    
    function processToLaneIndex(proc) {
        var procs = ["1", "2", "3", "4"];
        return procs.indexOf(proc);
    }
    
    function laneIndexToProcess(idx) {
        var procs = ["1", "2", "3", "4"];
        return procs[idx] || "1";
    }

    // ─────────────────────────────────────────────
    // Layout
    // ─────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Toolbar
        ToolBar {
            Layout.fillWidth: true
            height: 50
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 16

                Label {
                    text: "セットボード"
                    font.pixelSize: 18
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                // Shift toggle
                ButtonGroup { id: shiftGroup }
                
                Button {
                    text: "1直"
                    checkable: true
                    checked: currentShift === "day"
                    ButtonGroup.group: shiftGroup
                    onClicked: backend.setShift("day")
                }
                
                Button {
                    text: "2直"
                    checkable: true
                    checked: currentShift === "night"
                    ButtonGroup.group: shiftGroup
                    onClicked: backend.setShift("night")
                }

                Rectangle { width: 1; height: 30; color: "#ccc" }

                // Zoom
                Button {
                    text: "−"
                    width: 40
                    onClicked: backend.zoomOut()
                }
                
                Label {
                    text: "x" + pixelsPerMin.toFixed(1)
                    width: 50
                    horizontalAlignment: Text.AlignHCenter
                }
                
                Button {
                    text: "+"
                    width: 40
                    onClicked: backend.zoomIn()
                }

                Rectangle { width: 1; height: 30; color: "#ccc" }

                Button {
                    text: "SPO出力"
                    onClicked: backend.exportSpo()
                }
            }
        }

        // Main content area
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#ffffff"
            clip: true

            Flickable {
                id: flickable
                anchors.fill: parent
                contentWidth: labelWidth + getTimelineWidth() + gaugeWidth + 20
                contentHeight: headerHeight + laneHeight * 4 + 20
                boundsBehavior: Flickable.StopAtBounds
                
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                // Container for all content
                Item {
                    width: flickable.contentWidth
                    height: flickable.contentHeight

                    // ─────────────────────────────────────────────
                    // Time Scale (Header)
                    // ─────────────────────────────────────────────
                    TimeScale {
                        id: timeScale
                        x: labelWidth
                        y: 0
                        width: getTimelineWidth()
                        height: headerHeight
                        timeFrom: root.timeFrom
                        timeTo: root.timeTo
                        pixelsPerMin: root.pixelsPerMin
                        currentShift: root.currentShift
                    }

                    // ─────────────────────────────────────────────
                    // Lane Labels (Left side)
                    // ─────────────────────────────────────────────
                    Column {
                        x: 0
                        y: headerHeight
                        
                        Repeater {
                            model: backend.laneModel
                            
                            Rectangle {
                                width: labelWidth
                                height: laneHeight
                                color: index % 2 === 0 ? "#fafafa" : "#f0f0f0"
                                border.color: "#ddd"
                                border.width: 1
                                
                                Label {
                                    anchors.centerIn: parent
                                    text: process + "工程"
                                    font.pixelSize: 14
                                    font.bold: true
                                    color: ["#1976D2", "#388E3C", "#F57C00", "#7B1FA2"][index] || "#333"
                                }
                            }
                        }
                    }

                    // ─────────────────────────────────────────────
                    // Lane Backgrounds with Grid
                    // ─────────────────────────────────────────────
                    Column {
                        x: labelWidth
                        y: headerHeight
                        
                        Repeater {
                            model: 4
                            
                            Rectangle {
                                width: getTimelineWidth()
                                height: laneHeight
                                color: index % 2 === 0 ? "#fafafa" : "#f0f0f0"
                                border.color: "#ddd"
                                border.width: 1
                                
                                // 30-min grid lines
                                Repeater {
                                    model: Math.ceil(getTimelineWidth() / (30 * pixelsPerMin))
                                    
                                    Rectangle {
                                        x: index * 30 * pixelsPerMin
                                        y: 0
                                        width: 1
                                        height: laneHeight
                                        color: (index % 2 === 0) ? "#ccc" : "#e8e8e8"
                                    }
                                }
                            }
                        }
                    }

                    // ─────────────────────────────────────────────
                    // Tiles
                    // ─────────────────────────────────────────────
                    Repeater {
                        model: backend.tileModel
                        
                        Tile {
                            id: tile
                            
                            property int laneIdx: processToLaneIndex(process)
                            property real tileX: timeToX(start)
                            property real tileWidth: Math.max(40, (workSec / 60) * pixelsPerMin)
                            
                            x: labelWidth + tileX
                            y: headerHeight + laneIdx * laneHeight + 10
                            width: tileWidth
                            height: laneHeight - 20
                            
                            tileId: model.tileId
                            process: model.process
                            vendor: model.vendor
                            bin2: model.bin2
                            startTime: model.start
                            workSec: model.workSec
                            pallets: model.pallets
                            heightSum: model.heightSum
                            
                            onDragFinished: function(newX, newY) {
                                // Calculate new process from Y
                                var relY = newY - headerHeight;
                                var newLaneIdx = Math.floor(relY / laneHeight);
                                newLaneIdx = Math.max(0, Math.min(3, newLaneIdx));
                                var newProcess = laneIndexToProcess(newLaneIdx);
                                
                                // Calculate new start time from X
                                var relX = newX - labelWidth;
                                var newStart = xToTime(relX);
                                
                                backend.reassign(tileId, newProcess, newStart);
                            }
                        }
                    }

                    // ─────────────────────────────────────────────
                    // Gauges (Right side)
                    // ─────────────────────────────────────────────
                    Column {
                        x: labelWidth + getTimelineWidth()
                        y: headerHeight
                        
                        Repeater {
                            model: backend.laneModel
                            
                            Gauge {
                                width: gaugeWidth
                                height: laneHeight
                                currentValue: heightSum
                                maxValue: heightCap
                                count: model.count
                                maxCount: model.maxCount
                            }
                        }
                    }
                }
            }
        }

        // Status bar
        Rectangle {
            Layout.fillWidth: true
            height: 30
            color: "#e0e0e0"
            
            Label {
                id: statusLabel
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 10
                text: "Ready"
                font.pixelSize: 12
            }
            
            Connections {
                target: backend
                function onStatusMessage(msg) {
                    statusLabel.text = msg;
                }
            }
        }
    }
}
