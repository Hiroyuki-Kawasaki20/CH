import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    
    property int tileId: 0
    property string process: "1"
    property string vendor: ""
    property string bin2: ""
    property string startTime: "00:00"
    property int workSec: 0
    property int pallets: 0
    property int heightSum: 0
    
    signal dragFinished(real newX, real newY)
    
    // Colors per process
    readonly property var processColors: ({
        "1": "#1976D2",  // Blue
        "2": "#388E3C",  // Green
        "3": "#F57C00",  // Orange
        "4": "#7B1FA2"   // Purple
    })
    
    color: processColors[process] || "#666"
    radius: 4
    border.width: 1
    border.color: Qt.darker(color, 1.3)
    
    // Drag handling
    Drag.active: dragArea.drag.active
    Drag.hotSpot.x: width / 2
    Drag.hotSpot.y: height / 2
    
    // Store original position for drag
    property real origX: 0
    property real origY: 0
    
    MouseArea {
        id: dragArea
        anchors.fill: parent
        drag.target: parent
        hoverEnabled: true
        cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        
        onPressed: {
            root.origX = root.x;
            root.origY = root.y;
            root.z = 100;  // Bring to front
        }
        
        onReleased: {
            root.z = 1;
            root.dragFinished(root.x, root.y);
        }
        
    }
    
    // Content layout
    Column {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 2
        clip: true
        
        // Title row
        Row {
            spacing: 4
            
            Label {
                text: "山" + tileId
                font.pixelSize: 12
                font.bold: true
                color: "white"
                elide: Text.ElideRight
                width: parent.width
            }
        }
        
        // Vendor/bin info
        Label {
            text: vendor + " [" + bin2 + "]"
            font.pixelSize: 10
            color: Qt.rgba(1, 1, 1, 0.9)
            elide: Text.ElideRight
            width: parent.width
            visible: root.width > 80
        }
        
        // Time
        Label {
            text: startTime
            font.pixelSize: 10
            color: Qt.rgba(1, 1, 1, 0.8)
            visible: root.width > 60
        }
        
        // Work time
        Label {
            text: Math.round(workSec / 60) + "分"
            font.pixelSize: 9
            color: Qt.rgba(1, 1, 1, 0.7)
            visible: root.width > 50
        }
    }
}
