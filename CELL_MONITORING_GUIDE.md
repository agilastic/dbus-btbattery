# Cell Voltage Monitoring Guide

This guide explains how to use the cell voltage monitoring system for virtual batteries in the dbus-btbattery software.

## Overview

The cell voltage monitoring system provides detailed information about individual cell voltages across all physical batteries in a virtual battery configuration. This is especially useful for:

- Monitoring the health of individual cells
- Detecting imbalances between cells
- Tracking cell voltage trends over time
- Identifying potential issues before they become critical

## Features

- Real-time monitoring of individual cell voltages
- Historical data tracking
- Cell voltage imbalance detection and alerts
- Visual representation of cell voltage status
- Support for both series and parallel battery configurations

## Requirements

To use the cell monitoring system:

1. You must have two or more physical batteries configured as a virtual battery
2. Each physical battery must have cell voltage data available
3. The Venus OS version should be compatible with the QML user interface

## Accessing the Cell Monitor

The cell monitor can be accessed from the main Battery screen:

1. Go to the Battery page in the Venus OS interface
2. Look for the "Cell Monitor" menu item (appears only when multiple batteries are configured as a virtual battery)
3. Select "Cell Monitor" to access the detailed cell monitoring page

## Understanding the Cell Monitor Display

The cell monitor page shows:

### Overall Statistics
- Min/Max/Avg cell voltage across all batteries
- Maximum voltage spread (a measure of imbalance)
- Current alert count

### Individual Battery Data
Each physical battery is displayed with:
- Battery identification (MAC address or ID)
- Summary of min/max/avg voltage and spread
- Color-coded cell grid showing:
  - Green: Cell within normal range
  - Red: Cell voltage outside normal range or actively balancing
- Cell voltage displayed for each cell
- Small orange indicator for cells that are actively balancing

## Configuring Alerts

The cell monitor includes configurable alerts:

- **Alert Threshold**: The voltage difference (in volts) that triggers an imbalance alert
- **Sample Interval**: How frequently cells are sampled (in seconds)

These settings can be adjusted from the Cell Monitor page.

## Historical Data

Cell voltage history is automatically collected and stored. This data persists across system reboots and can be used to:

- Track cell performance over time
- Identify gradual degradation patterns
- Diagnose recurring issues

## Troubleshooting

### Cell Monitor Not Appearing
- Ensure you have multiple physical batteries configured
- Check that the main virtual battery service is running correctly
- Verify that cell voltage data is available from your BMS

### No Data for Some Cells
- Some cells may not report data if there are communication issues with a particular battery
- Check the Bluetooth connection to the affected battery
- Make sure the battery is online

### Excessive Alerts
- If you receive too many alerts, you may need to adjust the alert threshold
- A higher threshold will only alert on more significant imbalances

## Technical Details

The cell monitoring system is implemented as:

1. A background monitoring service that collects data from all physical batteries
2. A D-Bus interface that exposes this data to the Venus OS
3. A QML user interface for displaying the data

The system stores historical data in JSON format in `/data/cellhistory.json` on the Venus OS filesystem.

## Command Line Access

For advanced users, the cell monitoring data can also be accessed via the D-Bus interface:

```
# Get overall statistics
dbus -y com.victronenergy.battery.cellmonitor /CellMonitor/Statistics/MinVoltage
dbus -y com.victronenergy.battery.cellmonitor /CellMonitor/Statistics/MaxVoltage
dbus -y com.victronenergy.battery.cellmonitor /CellMonitor/Statistics/AvgVoltage
dbus -y com.victronenergy.battery.cellmonitor /CellMonitor/Statistics/MaxSpread

# Get complete data as JSON
dbus -y com.victronenergy.battery.cellmonitor /CellMonitor/Data
```