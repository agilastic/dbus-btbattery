#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced dbus-btbattery service with improved parallel battery support.
This script connects to multiple Bluetooth BMS devices and creates virtual batteries
in series or parallel configurations.
"""

import sys
import os
import signal
import argparse
import logging
import time
from threading import Thread, Event
from typing import List, Dict, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("BTBattery")

# Determine if we're running Python 2 or 3 (for GLib/gobject)
if sys.version_info.major == 2:
    from dbus.mainloop.glib import DBusGMainLoop
    import gobject
else:
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib as gobject

# Import the necessary modules
from jbdbt import JbdBt
from virtual import Virtual
from dbus_interface import VirtualBatteryDbusService
import utils
from utils import (
    logger, DRIVER_VERSION, DRIVER_SUBVERSION
)

# Global variables
running = True
battery_instance = None
dbus_service = None
mainloop = None
stop_event = Event()

def parse_arguments() -> Tuple[List[str], Dict[str, str], bool]:
    """
    Parse command line arguments.
    
    Returns:
        Tuple containing:
        - List of BT addresses
        - Dict mapping addresses to config paths
        - Boolean indicating series (True) or parallel (False) configuration
    """
    parser = argparse.ArgumentParser(description='Connect to Bluetooth BMS devices and create virtual batteries')
    parser.add_argument('-s', '--series', action='store_true', help='Configure batteries in series (default)')
    parser.add_argument('-p', '--parallel', action='store_true', help='Configure batteries in parallel')
    parser.add_argument('addresses', nargs='+', help='BT addresses of BMS devices, optionally with config path (addr:config_path)')
    
    args = parser.parse_args()
    
    # If parallel is specified, use parallel mode, otherwise use series (default)
    series_config = not args.parallel
    
    # Parse BT addresses and configs
    bt_addresses = []
    config_files = {}
    
    for addr_arg in args.addresses:
        if ":" in addr_arg and addr_arg.count(":") > 5:  # Format: MAC:config_path
            try:
                parts = addr_arg.split(":", 6)  # Split on 6th colon
                bt_address = ":".join(parts[:6]).upper()
                config_path = parts[6]
                if not bt_address or not config_path:
                    raise ValueError("Invalid address:config format")
                    
                # Validate that config file exists
                if not os.path.isfile(config_path):
                    logger.warning(f"Config file '{config_path}' does not exist, will use defaults")
                    
                config_files[bt_address] = config_path
                bt_addresses.append(bt_address)
                logger.info(f"Found custom config for {bt_address}: {config_path}")
            except Exception as e:
                logger.error(f"Could not parse address:config argument '{addr_arg}': {e}")
                sys.exit(1)
        else:  # Just a BT address
            bt_address = addr_arg.upper()
            bt_addresses.append(bt_address)
    
    if not bt_addresses:
        logger.error("No Bluetooth addresses provided.")
        sys.exit(1)
    
    return bt_addresses, config_files, series_config

def initialize_batteries(bt_addresses: List[str], config_files: Dict[str, str], series_config: bool):
    """
    Initialize all physical batteries and create a virtual battery.
    
    Args:
        bt_addresses: List of Bluetooth addresses
        config_files: Dict mapping addresses to config file paths
        series_config: True for series configuration, False for parallel
    
    Returns:
        The created battery object (virtual or physical)
    """
    logger.info(f"Initializing {'series' if series_config else 'parallel'} battery configuration")
    logger.info(f"Processing {len(bt_addresses)} battery address(es): {', '.join(bt_addresses)}")
    
    # Create physical battery objects
    if len(bt_addresses) == 1:
        # Single battery mode
        addr = bt_addresses[0]
        config_path = config_files.get(addr)
        logger.info(f"Creating single JBD battery for {addr}" + 
                   (f" with config {config_path}" if config_path else ""))
        try:
            battery = JbdBt(addr, config_path=config_path)
            return battery
        except Exception as e:
            logger.error(f"Failed to initialize JBD battery {addr}: {e}")
            sys.exit(1)
    
    # Multiple batteries - create virtual battery
    physical_batteries = []
    for addr in bt_addresses:
        config_path = config_files.get(addr)
        logger.info(f"  Initializing physical JBD battery {addr}" + 
                   (f" with config {config_path}" if config_path else ""))
        try:
            physical_battery = JbdBt(addr, config_path=config_path)
            physical_batteries.append(physical_battery)
        except Exception as e:
            logger.error(f"  Failed to initialize physical battery {addr}: {e}")
            # Continue with other batteries
    
    if not physical_batteries:
        logger.error("No physical batteries could be initialized.")
        sys.exit(1)
    elif len(physical_batteries) == 1:
        logger.warning("Only one physical battery initialized successfully. Running as single battery.")
        return physical_batteries[0]
    
    # Create virtual battery with multiple physical batteries
    logger.info(f"Creating Virtual battery with {len(physical_batteries)} components in {'series' if series_config else 'parallel'} mode")
    try:
        virtual_battery = Virtual(
            batteries=physical_batteries,
            series_config=series_config
        )
        return virtual_battery
    except Exception as e:
        logger.error(f"Failed to initialize Virtual battery: {e}")
        sys.exit(1)

def create_dbus_service(battery):
    """
    Create a DBUS service for the battery.
    
    Args:
        battery: The battery object (virtual or physical)
    
    Returns:
        The created DBUS service
    """
    logger.info("Creating DBUS service...")
    
    try:
        # Determine service name based on battery type
        if isinstance(battery, Virtual):
            config_type = "series" if battery.series_config else "parallel"
            service_name = f"com.victronenergy.battery.virtual_{config_type}"
        else:
            # For single physical battery
            addr_short = battery.address.replace(":", "")
            service_name = f"com.victronenergy.battery.{addr_short}"
        
        # Create the service
        service = VirtualBatteryDbusService(battery, service_name=service_name)
        
        # Initial data update
        if not battery.get_settings():
            logger.error("Failed to get initial battery settings.")
            return None
        
        # Update DBUS with initial values
        service.update()
        
        logger.info(f"DBUS service created: {service_name}")
        return service
    
    except Exception as e:
        logger.error(f"Error creating DBUS service: {e}")
        return None

def poll_battery(loop):
    """
    Periodic function to refresh battery data and update DBUS.
    
    Args:
        loop: The main event loop
    
    Returns:
        bool: True to continue polling, False to stop
    """
    global battery_instance, dbus_service, stop_event
    
    # Check if stop was requested
    if stop_event.is_set():
        return False
    
    # Check for required objects
    if not battery_instance or not dbus_service:
        logger.error("Battery or DBUS service not initialized.")
        return False
    
    try:
        # Refresh battery data
        result = battery_instance.refresh_data()
        
        if result:
            # Update DBUS service with new data
            dbus_service.update()
            return True
        else:
            logger.warning("Failed to refresh battery data")
            
            # If battery is marked offline, update DBUS to reflect this
            if hasattr(battery_instance, 'online') and not battery_instance.online:
                dbus_service.update()
            
            # Continue polling - the battery might reconnect
            return True
    
    except Exception as e:
        logger.error(f"Error in poll_battery: {e}")
        # Continue polling unless a stop was requested
        return not stop_event.is_set()

def cleanup():
    """Cleanup function for safe shutdown."""
    global battery_instance, stop_event, mainloop
    logger.info("Executing cleanup function...")
    
    # Signal threads to stop
    stop_event.set()
    
    if battery_instance:
        logger.info("Stopping battery instance...")
        try:
            # Access the underlying battery/batteries for stopping
            if isinstance(battery_instance, Virtual):
                logger.info("Stopping virtual battery components...")
                for battery in battery_instance.batts:
                    if hasattr(battery, 'stop'):
                        logger.info(f"Stopping battery {getattr(battery, 'address', 'N/A')}")
                        battery.stop()
            elif hasattr(battery_instance, 'stop'):
                logger.info(f"Stopping battery {getattr(battery_instance, 'address', 'N/A')}")
                battery_instance.stop()
        except Exception as e:
            logger.error(f"Error during battery stop: {e}")

def signal_handler(sig, frame):
    """Handle termination signals."""
    global running, mainloop
    logger.info(f"Received signal {sig}, shutting down...")
    running = False
    
    # Call cleanup
    cleanup()
    
    # Quit the main loop if it's running
    if mainloop:
        mainloop.quit()
    
    logger.info("Shutdown complete")
    sys.exit(0)

def main():
    """Main entry point for the script."""
    global battery_instance, dbus_service, running, mainloop, stop_event
    
    logger.info(f"Starting dbus-btbattery v{DRIVER_VERSION}{DRIVER_SUBVERSION}")
    
    # Parse command line arguments
    bt_addresses, config_files, series_config = parse_arguments()
    
    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize DBus main loop
    DBusGMainLoop(set_as_default=True)
    if sys.version_info.major == 2:
        gobject.threads_init()
    mainloop = gobject.MainLoop()
    
    # Reset stop event
    stop_event.clear()
    
    # Initialize battery objects
    battery_instance = initialize_batteries(bt_addresses, config_files, series_config)
    
    # Create DBUS service
    dbus_service = create_dbus_service(battery_instance)
    if not dbus_service:
        logger.error("Failed to create DBUS service, exiting.")
        sys.exit(1)
    
    # Start polling
    poll_interval_ms = getattr(battery_instance, 'poll_interval', 1000)
    logger.info(f"Starting battery polling every {poll_interval_ms}ms")
    gobject.timeout_add(poll_interval_ms, lambda: poll_battery(mainloop))
    
    # Enter main loop
    logger.info("Entering main loop")
    try:
        mainloop.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        running = False
    except Exception as e:
        logger.error(f"Unhandled exception in main loop: {e}")
        running = False
    
    # Make sure cleanup is called
    cleanup()
    
    logger.info("Service exiting")

if __name__ == "__main__":
    main()