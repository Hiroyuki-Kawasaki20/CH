import QtQuick
import QtQuick.Controls

Item {
    id: root
    
    property string timeFrom: "06:00"
    property string timeTo: "16:30"
    property real pixelsPerMin: 2.0
    property string currentShift: "day"

    function timeToMinutes(timeStr) {
        var parts = timeStr.split(":");
        var h = parseInt(parts[0], 10);
        var m = parseInt(parts[1], 10) || 0;
        var total = h * 60 + m;
        if (currentShift === "night" && h < 6) {
            total += 24 * 60;
        }
        return total;
    }

    Rectangle {
        anchors.fill: parent
        color: "#e8e8e8"
        border.color: "#ccc"
        
        // Hour markers
        Repeater {
            id: hourRepeater
            
            property int fromMin: timeToMinutes(timeFrom)
            property int toMin: {
                var t = timeToMinutes(timeTo);
                if (t <= fromMin) t += 24 * 60;
                return t;
            }
            property int totalHours: Math.ceil((toMin - fromMin) / 60) + 1
            
            model: totalHours
            
            Item {
                property int hourMin: hourRepeater.fromMin + index * 60
                property int snappedMin: Math.floor(hourMin / 60) * 60
                property real xPos: (snappedMin - hourRepeater.fromMin) * pixelsPerMin
                
                visible: xPos >= 0 && xPos < root.width
                
                // Hour line
                Rectangle {
                    x: parent.xPos
                    y: 0
                    width: 2
                    height: root.height
                    color: "#999"
                }
                
                // Hour label
                Label {
                    x: parent.xPos + 4
                    y: root.height / 2 - height / 2
                    text: {
                        var h = Math.floor(parent.snappedMin / 60) % 24;
                        return ("0" + h).slice(-2) + ":00";
                    }
                    font.pixelSize: 11
                    font.bold: true
                    color: "#333"
                }
            }
        }
        
        // 30-min markers (lighter)
        Repeater {
            property int fromMin: timeToMinutes(timeFrom)
            property int toMin: {
                var t = timeToMinutes(timeTo);
                if (t <= fromMin) t += 24 * 60;
                return t;
            }
            property int totalSlots: Math.ceil((toMin - fromMin) / 30)
            
            model: totalSlots
            
            Rectangle {
                property int slotMin: parent.fromMin + index * 30
                property real xPos: (slotMin - parent.fromMin) * pixelsPerMin
                
                x: xPos
                y: root.height - 15
                width: 1
                height: 15
                color: (index % 2 === 0) ? "#999" : "#bbb"
                visible: xPos > 0 && (slotMin % 60) !== 0
            }
        }
    }
}
