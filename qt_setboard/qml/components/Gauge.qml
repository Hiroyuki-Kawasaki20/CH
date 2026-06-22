import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    
    property int currentValue: 0
    property int maxValue: 2450
    property int count: 0
    property int maxCount: 8
    
    color: "#f5f5f5"
    border.color: "#ddd"
    border.width: 1
    
    Column {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 4
        
        // Height gauge
        Rectangle {
            width: parent.width
            height: (parent.height - 40) * 0.6
            color: "#e0e0e0"
            radius: 2
            
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: Math.min(parent.height, parent.height * (currentValue / maxValue))
                radius: 2
                color: (currentValue > maxValue) ? "#D32F2F" : (currentValue / maxValue > 0.8 ? "#FFA000" : "#4CAF50")
                
                Behavior on height {
                    NumberAnimation { duration: 200 }
                }
            }
        }
        
        // Height label
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: currentValue + "/" + maxValue
            font.pixelSize: 8
            color: (currentValue > maxValue) ? "#D32F2F" : "#666"
        }
        
        // Count indicator
        Row {
            width: parent.width
            spacing: 2
            
            Repeater {
                model: maxCount
                
                Rectangle {
                    width: (parent.width - (maxCount - 1) * 2) / maxCount
                    height: 8
                    radius: 1
                    color: index < count ? 
                           (count > maxCount ? "#D32F2F" : "#2196F3") : 
                           "#e0e0e0"
                }
            }
        }
        
        // Count label
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: count + "/" + maxCount + "山"
            font.pixelSize: 8
            color: count > maxCount ? "#D32F2F" : "#666"
        }
    }
}
