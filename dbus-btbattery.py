#!/usr/bin/python
# -*- coding: utf-8 -*-
from typing import Union, List, Dict, Optional

from time import sleep
from dbus.mainloop.glib import DBusGMainLoop
from threading import Thread
import sys
import signal # For graceful shutdown
import atexit

if sys.version_info.major == 2:
	import gobject
else:
	from gi.repository import GLib as gobject

# Victron packages
# from ve_utils import exit_on_error

from dbushelper import DbusHelper
from utils import logger
import utils
from battery import Battery
from jbdbt import JbdBt
from virtual import Virtual

# Global variables for cleanup
mainloop = None
dbus_helper = None
battery_instance = None

# Signal handler for graceful shutdown
def handle_signal(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    cleanup()
    if mainloop:
        mainloop.quit()
    sys.exit(0)

# Cleanup function
@atexit.register
def cleanup():
    logger.info("Executing cleanup function...")
    if battery_instance:
        logger.info("Stopping battery instance...")
        try:
            # Access the underlying battery/batteries for stopping
            if isinstance(battery_instance, Virtual):
                logger.info("Stopping virtual battery components...")
                for b in battery_instance.batts:
                    if hasattr(b, 'stop'):
                         logger.info(f"Stopping battery {getattr(b, 'address', 'N/A')}")
                         b.stop()
            elif hasattr(battery_instance, 'stop'):
                 logger.info(f"Stopping battery {getattr(battery_instance, 'address', 'N/A')}")
                 battery_instance.stop()
        except Exception as e:
            logger.error(f"Error during battery stop: {e}")



logger.info("Starting dbus-btbattery")


def poll_battery(loop):
	# This function is called regularly via gobject.timeout_add
	if dbus_helper and battery_instance:
		try:
			keep_polling = dbus_helper.publish_battery(loop)
			return keep_polling
		except Exception as e:
			logger.error(f"Error during battery polling: {e}")
			return False
	else:
		logger.warning("Polling skipped: helper or battery not available")
		return False


def main():
	global mainloop, dbus_helper, battery_instance
	
	logger.info(f"Starting dbus-btbattery v{utils.DRIVER_VERSION}{utils.DRIVER_SUBVERSION}")

	# Initialize DBus main loop early
	DBusGMainLoop(set_as_default=True)
	if sys.version_info.major == 2:
		gobject.threads_init()
	mainloop = gobject.MainLoop()

	# Setup signal handlers for graceful shutdown
	signal.signal(signal.SIGINT, handle_signal)
	signal.signal(signal.SIGTERM, handle_signal)

	# Parse command line arguments
	raw_args = sys.argv[1:]
	series_config = True  # Default: series
	config_files = {}
	bt_addresses = []

	i = 0
	while i < len(raw_args):
		arg = raw_args[i].lower()
		if arg in ['-p', '--parallel']:
			series_config = False
			logger.info("Parallel configuration selected.")
			i += 1
		elif arg in ['-s', '--series']:
			series_config = True
			logger.info("Series configuration selected.")
			i += 1
		else:
			# Assume it's a BT address or address:config pair
			addr_part = raw_args[i]
			if ":" in addr_part and addr_part.count(":") > 5:  # MAC:config_path format
				try:
					parts = addr_part.split(":", 6)
					bt_address = ":".join(parts[:6]).upper()  # Normalize MAC
					config_path = parts[6]
					if not bt_address or not config_path:
						raise ValueError("Invalid address:config format")
					config_files[bt_address] = config_path
					bt_addresses.append(bt_address)
					logger.info(f"Found custom config for {bt_address}: {config_path}")
				except Exception as e:
					logger.error(f"Could not parse address:config argument '{raw_args[i]}': {e}")
					sys.exit(1)
			else:  # Just a BT address
				bt_address = addr_part.upper()  # Normalize MAC
				bt_addresses.append(bt_address)
			i += 1

	if not bt_addresses:
		logger.error("No Bluetooth addresses provided.")
		sys.exit(1)

	logger.info(f"Processing {len(bt_addresses)} battery address(es): {', '.join(bt_addresses)}")

	# Create battery objects
	battery = None
	if len(bt_addresses) == 1:
		addr = bt_addresses[0]
		config_path = config_files.get(addr)
		logger.info(f"Creating single JBD battery for {addr}" + (f" with config {config_path}" if config_path else ""))
		try:
			# Pass config path directly to constructor
			battery = JbdBt(addr, config_path=config_path)
		except Exception as e:
			logger.error(f"Failed to initialize JBD battery {addr}: {e}")
			sys.exit(1)
	elif len(bt_addresses) >= 2:
		config_type = 'parallel' if not series_config else 'series'
		logger.info(f"Creating virtual battery ({config_type}) with {len(bt_addresses)} physical batteries")

		if len(bt_addresses) > 4:
			logger.warning("More than 4 battery addresses provided. Using only the first 4.")
			bt_addresses = bt_addresses[:4]

		physical_batteries = []
		for addr in bt_addresses:
			config_path = config_files.get(addr)
			logger.info(f"  Initializing physical JBD battery {addr}" + (f" with config {config_path}" if config_path else ""))
			try:
				physical_battery = JbdBt(addr, config_path=config_path)
				physical_batteries.append(physical_battery)
			except Exception as e:
				logger.error(f"  Failed to initialize physical battery {addr}: {e}")
				# Continue even if some batteries fail

		if not physical_batteries:
			logger.error("No physical batteries could be initialized.")
			sys.exit(1)
		elif len(physical_batteries) == 1:
			logger.warning("Only one physical battery initialized successfully. Running as single battery.")
			battery = physical_batteries[0]
		else:
			logger.info(f"Creating Virtual battery with {len(physical_batteries)} components")
			try:
				# Use the new constructor format
				battery = Virtual(
					batteries=physical_batteries,
					series_config=series_config
				)
			except Exception as e:
				logger.error(f"Failed to initialize Virtual battery: {e}")
				sys.exit(1)

	# Check if battery object was successfully created
	if battery is None:
		logger.error("ERROR >>> Battery object creation failed")
		sys.exit(1)

	battery_instance = battery  # Store globally for cleanup

	# Setup DBus and run
	logger.info("Setting up DBus service...")
	dbus_helper = DbusHelper(battery)

	try:
		if not dbus_helper.setup_vedbus():
			logger.error("Failed to setup DBus service. Exiting.")
			sys.exit(1)
	except Exception as e:
		logger.error(f"Exception during DBus setup: {e}")
		sys.exit(1)

	# Log initial settings
	try:
		battery.log_settings()
	except Exception as e:
		logger.error(f"Error logging initial settings: {e}")

	# Start polling and mainloop
	poll_interval_ms = getattr(battery, 'poll_interval', 1000)
	logger.info(f"Starting battery polling every {poll_interval_ms}ms")
	gobject.timeout_add(poll_interval_ms, lambda: poll_battery(mainloop))

	logger.info("Entering main loop")
	try:
		mainloop.run()  # Blocks until mainloop.quit() is called
	except KeyboardInterrupt:
		logger.info("KeyboardInterrupt received")
	except Exception as e:
		logger.critical(f"Unhandled exception in main loop: {e}")
		sys.exit(1)

	logger.info("Exiting dbus-btbattery")


if __name__ == "__main__":
	main()
