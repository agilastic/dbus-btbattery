# Enhanced Parallel Battery Support

## Summary of Changes

This update introduces comprehensive enhancements to the dbus-btbattery project's virtual battery functionality, particularly focused on improving parallel battery configurations.

## Recent Changes

### Configurable SOC Imbalance Detection

- Added configurable SOC imbalance detection for virtual batteries in parallel mode
- New configuration options:
  - `SOC_IMBALANCE_DETECTION_ENABLE`: Enable or disable SOC imbalance detection (default: True)
  - `SOC_IMBALANCE_THRESHOLD`: SOC difference threshold in percent (default: 10)
- Log output now includes imbalance detection configuration

### Key Improvements

#### Better Parallel Mode Logic
- Properly averages voltages instead of using just the first battery's value
- Correctly sums currents and capacities from all batteries
- Uses capacity-weighted SOC calculation for more accurate state reporting

#### Imbalance Detection and Handling
- Detects voltage, current, and SOC imbalances between batteries
- Automatically adjusts charge parameters when imbalances are detected
- Reports imbalance status via DBUS for monitoring

#### Enhanced Error Handling
- Better recovery from individual battery disconnections
- Graceful degradation when batteries go offline
- Detailed logging and status information

#### Improved DBUS Interface
- Added parallel-specific status parameters
- Better organization of code structure
- More consistent updating of DBUS values

## Implementation Details

### 1. Enhanced Virtual Battery (virtual.py)
- Complete rewrite of the virtual battery aggregation logic
- Separate handling for series vs. parallel configurations
- Added imbalance detection and handling methods
- Improved charge/discharge current and voltage management

### 2. DBUS Interface Enhancement (dbus_interface.py)
- New dedicated DBUS interface for virtual batteries
- Added parallel-specific DBUS paths
- Improved data update methods
- Better error handling

### 3. Main Service Script (dbus-btbattery.py)
- Modernized code structure
- Improved command-line parsing
- Better error handling and shutdown procedures
- Enhanced battery initialization

### 4. LiFePO4 Configuration (parallel_lfp_config.ini)
- Optimized settings for LiFePO4 batteries in parallel
- Conservative voltage and current limits
- Temperature-based current limiting

## Parallel Battery Aggregation Logic

When batteries are connected in parallel, the enhanced implementation:

- **Voltage**: Calculates the average voltage across all batteries (they should be at the same voltage in parallel)
- **Current**: Sums the current from all batteries (current is distributed in parallel)
- **Capacity**: Adds the capacity of all batteries (total capacity increases in parallel)
- **SoC**: Uses a capacity-weighted average of all batteries' SoC values
- **Temperature**: Uses the highest temperature for safety monitoring
- **FET Status**: Maintains charge/discharge if at least one battery allows it

## Imbalance Detection

The implementation now detects three types of imbalances:

1. **Voltage Imbalance**: Detected when batteries differ by more than 0.3V
2. **Current Imbalance**: Detected when current distribution is uneven (>20% difference)
3. **SoC Imbalance**: Detected when SoC values differ by more than 10%

When imbalances are detected, charge current and voltage are automatically adjusted to help rebalance the batteries.

## DBUS Interface Enhancements

New DBUS paths specific for parallel configurations:

- `/Parallel/VoltageImbalance`: Indicates voltage imbalance between batteries
- `/Parallel/CurrentImbalance`: Indicates current imbalance between batteries
- `/Parallel/SocImbalance`: Indicates SoC imbalance between batteries
- `/Parallel/TotalBatteries`: Total number of batteries in the configuration
- `/Parallel/ActiveBatteries`: Number of currently active batteries

## Usage

Run with batteries in parallel mode:
```bash
python3 dbus-btbattery.py -p AA:BB:CC:DD:EE:FF 00:11:22:33:44:55
```

For more details, see the PARALLEL_BATTERY_GUIDE.md file.

## Compatibility

These changes maintain backward compatibility with existing usage while adding new capabilities. Series mode operation continues to work as before.