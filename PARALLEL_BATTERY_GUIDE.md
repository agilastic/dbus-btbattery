# Enhanced Parallel Battery Support Guide

This guide will help you set up and use the enhanced parallel battery support in dbus-btbattery.

## Overview

The enhanced parallel battery support provides:

- Better voltage averaging for parallel batteries
- Improved current and capacity summation for parallel batteries
- Detection of voltage, current, and SoC imbalances
- Automatic adjustment of charge parameters based on imbalance detection
- More accurate SoC calculation using capacity-weighted averages
- Enhanced DBUS interface with parallel-specific status reporting
- Better error handling and recovery from disconnections

## Requirements

- Multiple Bluetooth BMS units (JBD or compatible)
- Venus OS with D-Bus support
- Batteries physically connected in parallel

## Installation

1. Ensure you have the latest version of dbus-btbattery installed:

```bash
git clone https://github.com/Louisvdw/dbus-btbattery.git
cd dbus-btbattery
chmod +x installservice.sh
./installservice.sh
```

2. Copy the provided parallel configuration file:

```bash
cp parallel_lfp_config.ini /etc/dbus-btbattery/config.ini
```

## Usage

### Running in Parallel Mode

To run with batteries in parallel mode:

```bash
python3 dbus-btbattery.py -p AA:BB:CC:DD:EE:FF 00:11:22:33:44:55
```

You can specify custom config files per battery:

```bash
python3 dbus-btbattery.py -p AA:BB:CC:DD:EE:FF:/path/to/config1.ini 00:11:22:33:44:55:/path/to/config2.ini
```

### Checking Status

Once running, you can monitor the battery status through the Venus OS GUI or using D-Bus:

```bash
# View all battery services
dbus -y com.victronenergy.battery

# View specific parallel battery values
dbus -y com.victronenergy.battery.virtual_parallel/Parallel
```

## Understanding Parallel Mode D-Bus Paths

The parallel mode adds several new D-Bus paths to monitor parallel battery status:

| Path | Description |
|------|-------------|
| `/Parallel/VoltageImbalance` | Indicates voltage imbalance between batteries |
| `/Parallel/CurrentImbalance` | Indicates current imbalance between batteries |
| `/Parallel/SocImbalance` | Indicates SoC imbalance between batteries |
| `/Parallel/TotalBatteries` | Total number of batteries in the configuration |
| `/Parallel/ActiveBatteries` | Number of currently active batteries |

### Cell Voltage Monitoring

For parallel battery configurations, cell voltages from all physical batteries are now published with unique identifiers:

| Path Format | Description |
|-------------|-------------|
| `/Voltages/Cell<BATTERY>-<CELL>` | Cell voltage for each physical battery |
| `/Balances/Cell<BATTERY>-<CELL>` | Cell balancing status for each physical battery |

Examples:
- `/Voltages/Cell1-3` = Voltage of cell #3 in battery #1
- `/Voltages/Cell2-4` = Voltage of cell #4 in battery #2
- `/Balances/Cell1-3` = Balance status of cell #3 in battery #1

This allows monitoring individual cell voltages across all physical batteries in the system.

## Handling Imbalances

The system automatically manages imbalances between batteries by:

1. Detecting voltage, current, and SoC differences between batteries
2. Adjusting charge voltage and current limits when imbalances are detected
3. Reporting imbalance status via D-Bus for monitoring

No manual intervention is required, but you may want to investigate if persistent imbalances are detected.

## Troubleshooting

### Batteries Not Connecting

If batteries are not connecting:

1. Ensure Bluetooth is enabled and working
2. Check that the BMS addresses are correct
3. Try running the scan.py tool to verify BMS visibility:
   ```bash
   python3 scan.py
   ```

### Imbalance Issues

If persistent imbalance warnings occur:

1. Check physical battery connections
2. Ensure all batteries are the same type, age, and capacity
3. Consider performing a manual balancing charge cycle

### Service Issues

If the service fails to start or crashes:

1. Check the log files:
   ```bash
   cat /var/log/dbus-btbattery/current
   ```
2. Ensure all dependencies are installed
3. Verify configurations are correct

## Advanced Configuration

The parallel_lfp_config.ini file contains optimized settings for LiFePO4 batteries in parallel. Key settings to consider adjusting:

- `MAX_BATTERY_CHARGE_CURRENT` - Combined maximum charge current
- `MAX_BATTERY_DISCHARGE_CURRENT` - Combined maximum discharge current
- `CELL_VOLTAGES_WHILE_CHARGING` - Voltage points for charge current tapering
- `MAX_CHARGE_CURRENT_CV_FRACTION` - Current tapering fractions

### Imbalance Detection Configuration

You can configure the SOC imbalance detection feature in the config file:

- `SOC_IMBALANCE_DETECTION_ENABLE` - Enable or disable SOC imbalance detection (default: True)
- `SOC_IMBALANCE_THRESHOLD` - SOC difference threshold in percent (default: 10)

To disable SOC imbalance detection, set `SOC_IMBALANCE_DETECTION_ENABLE = False` in your config file.
To adjust the sensitivity, modify the `SOC_IMBALANCE_THRESHOLD` value - higher values make detection less sensitive.

For more advanced settings, refer to the comments in the configuration file.