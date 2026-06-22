import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    
    color: "#ffffff"
    border.color: "#ddd"
    radius: 4
    
    readonly property var processColors: ({
        "1": "#1976D2",
        "2": "#388E3C", 
        "3": "#F57C00",
        "4": "#7B1FA2"
    })
    
    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 16
        
        Label {
            text: "凡例:"
            font.bold: true
        }
        
        Repeater {
            model: ["1", "2", "3", "4"]
            
            Row {
                spacing: 4
                
                Rectangle {
                    width: 16
                    height: 16
                    radius: 2
                    color: processColors[modelData]
                }
                
                Label {
                    text: modelData + "工程"
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
        
        Rectangle { width: 1; height: 20; color: "#ccc" }
        
        Row {
            spacing: 4
            
            Rectangle {
                width: 16
                height: 16
                radius: 2
                color: "#666"
                border.width: 2
                border.color: "#D32F2F"
            }
            
            Label {
                text: "違反"
                font.pixelSize: 12
                color: "#D32F2F"
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        
        Item { Layout.fillWidth: true }
    }
}
