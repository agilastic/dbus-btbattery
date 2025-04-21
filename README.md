# dbus-btbattery
This is a driver for VenusOS devices (As of yet only tested on Raspberry Pi running the VenusOS v2.92 image). 

The driver will communicate with a Battery Management System (BMS) via Bluetooth and publish this data to the VenusOS system. 

## Prerequisites
- VenusOS device (tested on Raspberry Pi with VenusOS v2.92+)
- Supported BMS with Bluetooth capability (currently JBD BMS is fully supported)
- Bluetooth hardware (built-in or USB dongle)
- Root access to the VenusOS device

### Instructions
To get started you need a VenusOS device. I've only tried on Raspberry Pi, you can follow my instructions here: https://www.youtube.com/watch?v=yvGdNOZQ0Rw to set one up.

You need to setup some dependencies on your VenusOS first:

1) SSH to IP assigned to venus device
2) Resize/Expand file system
```
/opt/victronenergy/swupdate-scripts/resize2fs.sh
```

3) Update opkg
```
opkg update
```

4) Install pip
```
opkg install python3-pip
```

5) Install build essentials as bluepy has some C code that needs to be compiled
```
opkg install packagegroup-core-buildessential
```

6) Install glib-dev required by bluepy
```
opkg install libglib-2.0-dev
```

7) Install bluepy
```
pip3 install bluepy
```

8) Install git
```
opkg install git
```

9) Clone dbus-btbattery repo
```
cd /opt/victronenergy/
git clone https://github.com/agilastic/dbus-btbattery
```

10) Run the battery monitor with your BMS Bluetooth address
```
cd dbus-btbattery
./dbus-btbattery.py 70:3e:97:08:00:62
```
Replace 70:3e:97:08:00:62 with the Bluetooth address of your BMS/Battery.

You can run `./scan.py` to find Bluetooth devices around you.

### To make dbus-btbattery startup automatically
1) Edit the service run file
```
nano service/run
```

2) Replace 70:3e:97:08:00:62 with the Bluetooth address of your BMS/Battery
3) Save with "Ctrl O"
4) Install the service and reboot
```
./installservice.sh
reboot
```

## Virtual Battery Feature
You can now add up to 4 bt battery addresses to the command line. It will connect to all batteries and create a single virtual battery. Supports both series and parallel configurations.

### Series Configuration (default)
For batteries connected in series (e.g., two 12V batteries providing 24V total):
```
./dbus-btbattery.py 70:3e:97:08:00:62 a4:c1:37:40:89:5e
```
or explicitly specifying series configuration:
```
./dbus-btbattery.py -s 70:3e:97:08:00:62 a4:c1:37:40:89:5e
```

In series configuration:
- Voltages add together
- Current is averaged across batteries
- Capacity uses the lowest value (conservative approach)
- Cell counts add together
- FET status (charge/discharge) uses logical AND (if any battery disables, all are disabled)

### Parallel Configuration
For batteries connected in parallel (e.g., two 12V batteries providing more capacity at 12V):
```
./dbus-btbattery.py -p 70:3e:97:08:00:62 a4:c1:37:40:89:5e
```

In parallel configuration:
- Voltage is averaged (should be nearly identical between batteries)
- Currents are added together
- Capacities are added together
- Cell count uses the first battery (all parallel batteries must have the same cell count)
- Cell data uses the first battery (because cell voltages should be equal)
- FET status is maintained if at least one battery allows charge/discharge

## Configuration Options
The system reads configuration from `default_config.ini`. You can create a custom `config.ini` file with your own settings that will override the defaults.

### Per-Battery Configuration
When running in parallel mode, you can now specify different configuration files for each battery:

```
./dbus-btbattery.py -p 70:3e:97:08:00:62:/path/to/config1.ini a4:c1:37:40:89:5e:/path/to/config2.ini
```

Format for specifying a battery with custom config: `BT_ADDRESS:CONFIG_PATH`

This allows you to use different parameters for each battery, which is especially useful when batteries have different capacities or characteristics.

### Key Configuration Options
- `MAX_BATTERY_CHARGE_CURRENT`: Maximum charge current (default 70.0A)
- `MAX_BATTERY_DISCHARGE_CURRENT`: Maximum discharge current (default 90.0A)
- `MIN_CELL_VOLTAGE`: Minimum cell voltage (default 2.9V)
- `MAX_CELL_VOLTAGE`: Maximum cell voltage (default 3.45V)
- `FLOAT_CELL_VOLTAGE`: Float voltage per cell (default 3.35V)
- `SOC_LOW_WARNING`: State of charge low warning level (default 20%)
- `SOC_LOW_ALARM`: State of charge low alarm level (default 10%)

See the `default_config.ini` file for more configuration options.

## Troubleshooting

### Common Issues
1. **Connection Problems**
   - Verify your Bluetooth address is correct using `./scan.py`
   - Check if the battery is within range
   - Ensure your BMS has Bluetooth enabled
   
2. **Data Not Appearing in VenusOS**
   - Check service logs: `cat /var/log/dbus-btbattery/current`
   - Verify the service is running: `svstat /service/dbus-btbattery`
   - Restart the service: `svc -t /service/dbus-btbattery`

3. **Bluetooth Connection Drops**
   - The script has a built-in watchdog timer that will reboot the system if the Bluetooth connection hangs
   - The watchdog can be adjusted in `jbdbt.py` (BT_WATCHDOG_TIMER)

### Logging
Logs can be found at `/var/log/dbus-btbattery/current` when running as a service.

When running manually, logs are printed to the console and include connection status, cell voltages, and error messages.

## Raspberry Pi Bluetooth Firmware
For Raspberry Pi users experiencing Bluetooth issues, updated firmware is included in the `rpi_bt_firmware` directory. Run `rpi_bt_firmware/installfirmware.sh` to update your Bluetooth firmware.

## QML Integration
The `qml` directory contains QML pages for VenusOS GUI integration. Run `qml/install-qml.sh` to install these pages, which will add battery screens to your VenusOS display.

## Cell Voltage Monitoring
The system now includes advanced cell voltage monitoring capabilities for virtual battery setups with multiple physical batteries:

- Tracks individual cell voltages across all physical batteries
- Displays min/max/average voltage values for each battery
- Records historical voltage data for trend analysis
- Provides visual indication of cell imbalances
- Generates alerts for critical voltage differences
- Supports both series and parallel configurations

The cell monitor is automatically enabled when running with multiple batteries and is accessible through the "Cell Monitor" menu in the Battery screen.

For more details, see the [Cell Monitoring Guide](CELL_MONITORING_GUIDE.md).

NOTES: This driver is far from complete, so some things will probably be broken. Also only JBD BMS is currently supported.