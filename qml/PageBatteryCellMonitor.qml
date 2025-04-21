import QtQuick 1.1
import com.victron.velib 1.0

MbPage {
    id: root
    property string bindPrefix
    property VBusItem cellMonitorService: VBusItem { bind: "com.victronenergy.battery.cellmonitor" }
    property VBusItem batteryCount: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/BatteryCount" }
    property VBusItem minVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Statistics/MinVoltage" }
    property VBusItem maxVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Statistics/MaxVoltage" }
    property VBusItem avgVoltage: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Statistics/AvgVoltage" }
    property VBusItem maxSpread: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Statistics/MaxSpread" }
    property VBusItem lastUpdate: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Statistics/LastUpdate" }
    property VBusItem alertCount: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Alerts/Count" }
    property VBusItem latestAlert: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Alerts/Latest" }
    property VBusItem sampleInterval: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Settings/SampleInterval" }
    property VBusItem alertThreshold: VBusItem { bind: "com.victronenergy.battery.cellmonitor/Settings/AlertThreshold" }
    property VBusItem batteryData: VBusItem { bind: "com.victronenergy.battery.cellmonitor/CellMonitor/Data" }

    title: "Battery Cell Monitor"

    Component {
        id: batteryDelegate
        
        Column {
            width: parent.width
            spacing: 2
            
            // Battery header and summary
            Rectangle {
                width: parent.width
                height: 30
                color: "#2d2d2d"
                
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 5
                    font.pixelSize: 16
                    font.bold: true
                    color: "white"
                    text: "Battery " + batteryId
                }
                
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: 5
                    font.pixelSize: 14
                    color: "white"
                    text: {
                        if (minVoltage !== undefined && maxVoltage !== undefined) {
                            return minVoltage.toFixed(3) + "V - " + maxVoltage.toFixed(3) + "V (" + spread.toFixed(3) + "V)"
                        } else {
                            return "No data"
                        }
                    }
                }
            }
            
            // Cell voltage grid
            Grid {
                id: cellGrid
                width: parent.width
                columns: 4
                spacing: 4
                
                Repeater {
                    model: cellVoltages !== undefined ? cellVoltages.length : 0
                    
                    Rectangle {
                        width: (cellGrid.width - (cellGrid.columns - 1) * cellGrid.spacing) / cellGrid.columns
                        height: 40
                        color: {
                            if (cellVoltages[index] === null) {
                                return "#444444"
                            }
                            
                            // Color based on voltage level
                            var voltage = cellVoltages[index]
                            var min = minVoltage * 0.997 // 0.3% tolerance
                            var max = maxVoltage * 1.003 // 0.3% tolerance
                            
                            // Red for outliers or balancing cells
                            if (balancingState[index] || voltage <= min || voltage >= max) {
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
                                text: cellVoltages[index] !== null ? cellVoltages[index].toFixed(3) + "V" : "---"
                            }
                        }
                        
                        // Balancing indicator
                        Rectangle {
                            visible: balancingState[index]
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
            
            // Spacer between batteries
            Rectangle {
                width: parent.width
                height: 10
                color: "transparent"
            }
        }
    }

    model: VisibleItemModel {
        MbItemRow {
            description: qsTr("Status")
            values: [
                MbTextBlock { item: cellMonitorService; width: 220; height: 25 }
            ]
        }
        
        MbItemRow {
            description: qsTr("Overall Statistics")
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
                MbTextBlock { item: maxSpread; width: 80; height: 25 }
            ]
        }
        
        MbItemRow {
            description: qsTr("Alerts")
            show: alertCount.valid && alertCount.value > 0
            values: [
                MbTextBlock { item: latestAlert; width: 220; height: 25 }
            ]
        }
        
        MbItemRow {
            description: qsTr("Battery Cells")
            values: [
                MbTextBlock { text: qsTr("Sample every "); width: 80; height: 25 },
                MbTextBlock { item: sampleInterval; width: 40; height: 25 },
                MbTextBlock { text: qsTr(" seconds"); width: 80; height: 25 }
            ]
        }
        
        MbItemValue {
            description: qsTr("Alert Threshold")
            item: alertThreshold
            show: alertThreshold.valid
        }
        
        MbOK {
            id: batteriesContainer
            description: qsTr("Physical Batteries")
            editable: false
            show: batteryData.valid
            
            function parseBatteryData() {
                if (!batteryData.valid || !batteryData.value)
                    return {}
                
                try {
                    return JSON.parse(batteryData.value)
                } catch (e) {
                    console.log("Error parsing battery data:", e)
                    return {}
                }
            }
            
            Component.onCompleted: {
                // Initial parse
                updateBatteryDisplay()
            }
            
            // Update when data changes
            Connections {
                target: batteryData
                onValueChanged: {
                    updateBatteryDisplay()
                }
            }
            
            function updateBatteryDisplay() {
                // Clear previous content
                while (batteryList.children.length > 0) {
                    batteryList.children[0].destroy()
                }
                
                var data = parseBatteryData()
                if (!data.batteries)
                    return
                
                // Create battery displays
                for (var batteryId in data.batteries) {
                    var batteryData = data.batteries[batteryId]
                    
                    batteryDelegate.createObject(batteryList, {
                        batteryId: batteryId,
                        cellCount: batteryData.cell_count,
                        minVoltage: batteryData.min_voltage,
                        maxVoltage: batteryData.max_voltage,
                        avgVoltage: batteryData.avg_voltage,
                        spread: batteryData.voltage_spread,
                        cellVoltages: batteryData.cell_voltages,
                        balancingState: batteryData.balancing
                    })
                }
            }
            
            content: Rectangle {
                color: "transparent"
                anchors.fill: parent
                
                Flickable {
                    id: batteryFlickable
                    anchors.fill: parent
                    contentWidth: width
                    contentHeight: batteryList.height
                    flickableDirection: Flickable.VerticalFlick
                    clip: true
                    
                    Column {
                        id: batteryList
                        width: parent.width
                        spacing: 5
                    }
                    
                    ScrollBar {
                        flickable: batteryFlickable
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