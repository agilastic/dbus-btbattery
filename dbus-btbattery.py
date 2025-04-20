#!/usr/bin/python
# -*- coding: utf-8 -*-
from typing import Union

from time import sleep
from dbus.mainloop.glib import DBusGMainLoop
from threading import Thread
import sys

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



logger.info("Starting dbus-btbattery")


def main():
	def poll_battery(loop):
		# Run in separate thread. Pass in the mainloop so the thread can kill us if there is an exception.
		poller = Thread(target=lambda: helper.publish_battery(loop))
		# Thread will die with us if deamon
		poller.daemon = True
		poller.start()
		return True


	def get_btaddr() -> str:
		# Get the bluetooth address we need to use from the argument
		if len(sys.argv) > 1:
			return sys.argv[1:]
		else:
			return False


	logger.info(
		"dbus-btbattery v" + str(utils.DRIVER_VERSION) + utils.DRIVER_SUBVERSION
	)

	btaddr = get_btaddr()
	
	# Check if the first argument is a configuration option
	series_config = True  # Default is series configuration
	start_idx = 0
	
	if btaddr and btaddr[0].lower() in ['-p', '--parallel']:
		# Parallel battery configuration
		series_config = False
		start_idx = 1
		btaddr = btaddr[1:]  # Remove the configuration flag
	elif btaddr and btaddr[0].lower() in ['-s', '--series']:
		# Series battery configuration (explicit)
		series_config = True
		start_idx = 1
		btaddr = btaddr[1:]  # Remove the configuration flag
		
	# Parse any config-related arguments
	config_files = {}
	filtered_btaddr = []
	
	# Format: BT_ADDRESS:CONFIG_PATH (e.g., AA:BB:CC:DD:EE:FF:/path/to/config.ini)
	for addr in btaddr:
		if ":" in addr and addr.count(":") > 5:  # More than 5 colons means it has a config path
			parts = addr.split(":", 6)  # Split at most 6 times to get BT address and config path
			bt_address = ":".join(parts[:6])  # First 6 parts form the BT address
			config_path = parts[6]  # The rest is the config path
			
			config_files[bt_address] = config_path
			filtered_btaddr.append(bt_address)
			logger.info(f"Custom config for {bt_address}: {config_path}")
		else:
			filtered_btaddr.append(addr)
	
	# Update btaddr with filtered addresses
	btaddr = filtered_btaddr
	
	# Create the appropriate battery object based on number of addresses
	battery = None
	try:
		if len(btaddr) >= 2:
			logger.info(f"Creating virtual battery in {'parallel' if not series_config else 'series'} configuration with {len(btaddr)} batteries")
			
			# Create batteries array from the addresses
			batteries = []
			for addr in btaddr:
				try:
					batteries.append(JbdBt(addr))
					logger.info(f"Added battery with address {addr}")
				except Exception as e:
					logger.error(f"Error creating battery with address {addr}: {str(e)}")
			
			# Check if we have any valid batteries
			if not batteries:
				logger.error("No valid batteries could be created")
				sys.exit(1)
				
			# Create virtual battery with up to 4 batteries
			if len(batteries) > 4:
				logger.warning(f"More than 4 battery addresses provided. Using only the first 4.")
				batteries = batteries[:4]
				
			# Unpack the batteries list for the Virtual constructor
			if len(batteries) == 1:
				# Only one valid battery, use it directly
				battery = batteries[0]
				logger.info(f"Using single battery with address {batteries[0].address}")
			elif len(batteries) == 2:
				battery = Virtual(batteries[0], batteries[1], series_config=series_config, config_files=config_files)
			elif len(batteries) == 3:
				battery = Virtual(batteries[0], batteries[1], batteries[2], series_config=series_config, config_files=config_files)
			elif len(batteries) == 4:
				battery = Virtual(batteries[0], batteries[1], batteries[2], batteries[3], series_config=series_config, config_files=config_files)
		elif len(btaddr) == 1:
			# Single battery
			logger.info(f"Using single battery with address {btaddr[0]}")
			battery = JbdBt(btaddr[0])
			
			# If we have a config file for this address, load it
			if btaddr[0] in config_files:
				logger.info(f"Loading custom config for battery {btaddr[0]}: {config_files[btaddr[0]]}")
				battery.load_custom_config(config_files[btaddr[0]])
		else:
			logger.error("ERROR >>> No battery address provided")
			sys.exit(1)
	except Exception as e:
		logger.error(f"ERROR >>> Failed to initialize battery: {str(e)}")
		sys.exit(1)

	if battery is None:
		logger.error("ERROR >>> No battery connection at " + str(btaddr))
		sys.exit(1)
		
	# Register cleanup function to handle graceful shutdown
	def cleanup():
		logger.info("Shutting down dbus-btbattery...")
		if isinstance(battery, Virtual):
			for b in battery.batts:
				if hasattr(b, 'stop'):
					b.stop()
		elif hasattr(battery, 'stop'):
			battery.stop()
			
	import atexit
	atexit.register(cleanup)

	battery.log_settings()

	# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
	DBusGMainLoop(set_as_default=True)
	if sys.version_info.major == 2:
		gobject.threads_init()
	mainloop = gobject.MainLoop()

	# Get the initial values for the battery used by setup_vedbus
	helper = DbusHelper(battery)

	if not helper.setup_vedbus():
		logger.error("ERROR >>> Problem with battery " + str(btaddr))
		sys.exit(1)

	# Poll the battery at INTERVAL and run the main loop
	gobject.timeout_add(battery.poll_interval, lambda: poll_battery(mainloop))
	try:
		mainloop.run()
	except KeyboardInterrupt:
		pass


if __name__ == "__main__":
	main()
