import QtQuick 1.1
import com.victron.velib 1.0

MbPage {
    id: root
    property string bindPrefix
    property string batteryId
    property VBusItem cellMonitorService: VBusItem { bind: "com.victronenergy.battery.cellmonitor" }
    property VBusItem batteryName: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/Name" }
    property VBusItem cellCount: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/CellCount" }
    property VBusItem minVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/MinVoltage" }
    property VBusItem maxVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/MaxVoltage" }
    property VBusItem avgVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/AvgVoltage" }
    property VBusItem voltageSpread: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/VoltageSpread" }
    property VBusItem lastUpdate: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/LastUpdate" }
    property VBusItem cellVoltages: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/CellVoltages" }
    property VBusItem cellBalancing: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Parallel/Battery/" + batteryId + "/Balancing" }

    title: batteryName.valid ? batteryName.value : "Battery " + batteryId

    function parseVoltages() {
        if (!cellVoltages.valid || !cellVoltages.value)
            return []
        
        try {
            return JSON.parse(cellVoltages.value)
        } catch (e) {
            console.log("Error parsing cell voltages:", e)
            return []
        }
    }
    
    function parseBalancing() {
        if (!cellBalancing.valid || !cellBalancing.value)
            return []
        
        try {
            return JSON.parse(cellBalancing.value)
        } catch (e) {
            console.log("Error parsing balancing data:", e)
            return []
        }
    }
    
    model: VisibleItemModel {
        MbItemRow {
            description: qsTr("Battery ID")
            values: [
                MbTextBlock { text: batteryId; width: 220; height: 25 }
            ]
        }
        
        MbItemRow {
            description: qsTr("Cell Statistics")
            values: [
                MbTextBlock { text: qsTr("Min: "); width: 30; height: 25 },
                MbTextBlock { item: minVoltage; width: 80; height: 25 },
                MbTextBlock { text: qsTr("Max: "); width: 30; height: 25 },
                MbTextBlock { item: maxVoltage; width: 80; height: 25 }
            ]
        }
        
        MbItemRow {
            description: qsTr("")
            values: [
                MbTextBlock { text: qsTr("Avg: "); width: 30; height: 25 },
                MbTextBlock { item: avgVoltage; width: 80; height: 25 },
                MbTextBlock { text: qsTr("Diff: "); width: 30; height: 25 },
                MbTextBlock { item: voltageSpread; width: 80; height: 25 }
            ]
        }
        
        MbOK {
            id: cellsContainer
            description: qsTr("Cell Voltages")
            editable: false
            show: cellVoltages.valid
            
            content: Rectangle {
                color: "transparent"
                anchors.fill: parent
                
                Flickable {
                    id: cellsFlickable
                    anchors.fill: parent
                    contentWidth: width
                    contentHeight: cellGrid.height
                    flickableDirection: Flickable.VerticalFlick
                    clip: true
                    
                    Grid {
                        id: cellGrid
                        width: parent.width
                        columns: 2
                        spacing: 10
                        
                        Repeater {
                            model: parseVoltages().length
                            
                            Rectangle {
                                property var voltages: parseVoltages()
                                property var balancing: parseBalancing()
                                width: (cellGrid.width - cellGrid.spacing) / 2
                                height: 40
                                color: {
                                    if (voltages[index] === null) {
                                        return "#444444"
                                    }
                                    
                                    // Color based on voltage level
                                    var voltage = voltages[index]
                                    var min = minVoltage.value !== null ? minVoltage.value * 0.997 : 0 // 0.3% tolerance
                                    var max = maxVoltage.value !== null ? maxVoltage.value * 1.003 : 0 // 0.3% tolerance
                                    
                                    // Red for outliers or balancing cells
                                    if ((balancing.length > index && balancing[index]) || 
                                        (voltage <= min || voltage >= max)) {
                                        return "#e53935"
                                    }
                                    
                                    // Green for balanced cells
                                    return "#43a047"
                                }
                                border.color: "black"
                                border.width: 1
                                radius: 2
                                
                                Column {
                                    anchors.centerIn: parent
                                    spacing: 2
                                    
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: "white"
                                        text: "Cell " + (index + 1)
                                    }
                                    
                                    Text {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        font.pixelSize: 14
                                        color: "white"
                                        text: voltages[index] !== null ? voltages[index].toFixed(3) + "V" : "---"
                                    }
                                }
                                
                                // Balancing indicator
                                Rectangle {
                                    visible: balancing.length > index && balancing[index]
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 2
                                    width: 8
                                    height: 8
                                    radius: 4
                                    color: "orange"
                                }
                            }
                        }
                    }
                    
                    ScrollBar {
                        flickable: cellsFlickable
                    }
                }
            }
        }
    }
    
    // Simple ScrollBar implementation
    Component {
        id: scrollBar
        
        Rectangle {
            id: scrollBarItem
            property Flickable flickable: null
            z: 100
            width: 8
            color: "transparent"
            visible: flickable.contentHeight > flickable.height
            
            anchors {
                top: flickable.top
                right: flickable.right
                bottom: flickable.bottom
            }
            
            Rectangle {
                id: slider
                color: "#666666"
                border.color: "#888888"
                border.width: 1
                radius: 4
                opacity: 0.7
                width: parent.width
                
                y: flickable.contentY * parent.height / flickable.contentHeight
                height: flickable.height * parent.height / flickable.contentHeight
            }
        }
    }
}