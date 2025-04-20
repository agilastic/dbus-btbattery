from bluepy.btle import Peripheral, DefaultDelegate, BTLEException, BTLEDisconnectError
from threading import Thread, Lock
from battery import Protection, Battery, Cell
from utils import *
from struct import *
import sys
import time
import binascii
import os

# Constants
INITIAL_DATA_TIMEOUT_SECONDS = 30  # Timeout for waiting for first data read
RECONNECT_DELAY_SECONDS = 5        # Delay before attempting reconnect
POLL_INTERVAL_SECONDS = 5          # How often to request data

# Read Watchdog settings from config
try:
    BT_WATCHDOG_TIMEOUT = int(config["DEFAULT"].get("BT_WATCHDOG_TIMEOUT", 30))
    BT_WATCHDOG_ACTION = config["DEFAULT"].get("BT_WATCHDOG_ACTION", "log").lower()
except (ValueError, KeyError):
    logger.warning("Could not read BT Watchdog settings from config, using defaults (30s, log)")
    BT_WATCHDOG_TIMEOUT = 30
    BT_WATCHDOG_ACTION = "log"


class JbdProtection(Protection):
	def __init__(self):
		Protection.__init__(self)
		self.voltage_high_cell = False
		self.voltage_low_cell = False
		self.short = False
		self.IC_inspection = False
		self.software_lock = False

	def set_voltage_high_cell(self, value):
		self.voltage_high_cell = value
		self.cell_imbalance = (
			2 if self.voltage_low_cell or self.voltage_high_cell else 0
		)

	def set_voltage_low_cell(self, value):
		self.voltage_low_cell = value
		self.cell_imbalance = (
			2 if self.voltage_low_cell or self.voltage_high_cell else 0
		)

	def set_short(self, value):
		self.short = value
		# Set internal_failure instead of incorrectly calling set_cell_imbalance
		self.internal_failure = (
			2 if self.short or self.IC_inspection or self.software_lock else 0
		)

	def set_ic_inspection(self, value):
		self.IC_inspection = value
		self.internal_failure = (
			2 if self.short or self.IC_inspection or self.software_lock else 0
		)

	def set_software_lock(self, value):
		self.software_lock = value
		self.internal_failure = (
			2 if self.short or self.IC_inspection or self.software_lock else 0
		)



class JbdBtDev(DefaultDelegate, Thread):
	def __init__(self, address, battery_parent):
		DefaultDelegate.__init__(self)
		Thread.__init__(self)
		self.daemon = True  # Make thread exit with main program

		self.battery_parent = battery_parent # Reference to the main JbdBt object
		self.address = address
		self.bt = Peripheral()
		self.bt.setDelegate(self)
		self.is_connected = False
		self.last_data_received_time = time.monotonic()
		self.running = False

		# Data handling attributes
		self.cellDataCallback = None
		self.generalDataCallback = None
		self.incoming_data_buffer = {} # Dictionary to store fragmented data
		self.expected_lengths = {} # Dictionary to store expected lengths
		self.last_command_type = None # Track last command type
		self.cellData = None
		self.generalData = None
		self.last_state = "0000"
		self.cellDataTotalLen = 0
		self.cellDataRemainingLen = 0
		self.generalDataTotalLen = 0
		self.generalDataRemainingLen = 0
		self.interval = POLL_INTERVAL_SECONDS


	def connect(self):
		try:
			logger.info(f'Connecting to {self.address}')
			self.bt.connect(self.address, addrType="public")
			self.bt.setDelegate(self) # Re-set delegate after connection
			logger.info(f'Connected successfully to {self.address}')
			self.is_connected = True
			self.last_data_received_time = time.monotonic() # Reset watchdog timer on connect
			return True
		except BTLEException as ex:
			logger.error(f'Connection failed to {self.address}: {ex}')
			self.is_connected = False
			return False
		except Exception as e:
			logger.error(f"Unexpected error during connect to {self.address}: {e}")
			self.is_connected = False
			return False


	def disconnect(self):
		try:
			if self.is_connected:
				logger.info(f"Disconnecting from {self.address}")
				self.bt.disconnect()
		except BTLEException as ex:
			logger.warning(f"Error during disconnect from {self.address}: {ex}")
		except Exception as e:
			logger.warning(f"Unexpected error during disconnect from {self.address}: {e}")
		finally:
			self.is_connected = False


	def run(self):
		self.running = True
		last_poll_time = 0

		while self.running:
			if not self.is_connected:
				if not self.connect():
					time.sleep(RECONNECT_DELAY_SECONDS)
					continue # Try connecting again

			try:
				# Check for notifications
				self.bt.waitForNotifications(1.0)

				# Check watchdog timer
				self.check_watchdog()

				# Request data periodically
				current_time = time.monotonic()
				if (current_time - last_poll_time) >= self.interval:
					logger.debug(f"Polling data from {self.address}")
					if self.send_command(b'\xdd\xa5\x03\x00\xff\xfd\x77'): # Request general info (0x03)
						time.sleep(0.5) # Short delay between commands
						self.send_command(b'\xdd\xa5\x04\x00\xff\xfc\x77') # Request cell info (0x04)
					last_poll_time = current_time

			except BTLEDisconnectError:
				logger.warning(f'Device {self.address} disconnected.')
				self.is_connected = False
				time.sleep(RECONNECT_DELAY_SECONDS)
			except BTLEException as ex:
				logger.error(f'BTLE Exception for {self.address}: {ex}')
				self.disconnect()
				time.sleep(RECONNECT_DELAY_SECONDS)
			except Exception as e:
				 logger.error(f"Unexpected error in JbdBtDev run loop for {self.address}: {e}")
				 self.disconnect()
				 time.sleep(RECONNECT_DELAY_SECONDS)

		# Clean up on exit
		self.disconnect()
		logger.info(f"JbdBtDev thread stopped for {self.address}")


	def stop(self):
		logger.info(f"Stopping JbdBtDev thread for {self.address}...")
		self.running = False


	def send_command(self, command_bytes):
		if not self.is_connected:
			logger.warning(f"Cannot send command to {self.address}, not connected.")
			return False
		try:
			hex_string = binascii.hexlify(command_bytes).decode('utf-8')
			logger.debug(f"Sending command to {self.address}: {hex_string}")
			self.bt.writeCharacteristic(0x15, command_bytes, withResponse=True)
			# Set last command type based on request
			if command_bytes[2] == 0x03:
				self.last_command_type = 0x03
			elif command_bytes[2] == 0x04:
				self.last_command_type = 0x04
			return True
		except BTLEException as ex:
			logger.error(f"Failed to write command to {self.address}: {ex}")
			self.is_connected = False
			return False
		except Exception as e:
			logger.error(f"Unexpected error writing command to {self.address}: {e}")
			self.is_connected = False
			return False


	def addCellDataCallback(self, func):
		self.cellDataCallback = func

	def addGeneralDataCallback(self, func):
		self.generalDataCallback = func

	def handleNotification(self, cHandle, data):
		hex_data = binascii.hexlify(data)
		hex_string = hex_data.decode('utf-8')		
		logger.info("new Hex_String(" +str(len(data))+"): " + str(hex_string))

		# Update watchdog timer
		self.last_data_received_time = time.monotonic()

		HEADER_LEN = 4 #[Start Code][Command][Status][Length]
		FOOTER_LEN = 3 #[16bit Checksum][Stop Code]

		# Using the same data handling logic as the original code
		# since it seems to work for this specific BMS protocol

		# Cell Data
		if hex_string.find('dd04') != -1:
			self.last_state = "dd04"
			# Because of small MTU size, the BMS data may not be transmitted in a single packet.
			# We use the 4th byte defined as "data len" in the BMS protocol to calculate the remaining bytes
			# that will be transmitted in the second packet
			self.cellDataTotalLen = data[3] + HEADER_LEN + FOOTER_LEN
			self.cellDataRemainingLen = self.cellDataTotalLen - len(data)
			logger.info("cellDataTotalLen: " + str(int(self.cellDataTotalLen)))
			logger.info("cellDataRemainingLen: " + str(int(self.cellDataRemainingLen)))
			self.cellData = data
		elif self.last_state == "dd04" and hex_string.find('dd04') == -1 and hex_string.find('dd03') == -1: 
			self.cellData = self.cellData + data
			self.cellDataCallback(self.cellData)
			logger.info("Final Length cellData(" + str(len(self.cellData))+ "): " + str(binascii.hexlify(self.cellData).decode('utf-8')))
				
		# General Data
		elif hex_string.find('dd03') != -1:
			self.last_state = "dd03"
			self.generalDataTotalLen = data[3] + HEADER_LEN + FOOTER_LEN
			self.generalDataRemainingLen = self.generalDataTotalLen - len(data)
			logger.info("generalDataTotalLen: " + str(int(self.generalDataTotalLen)))
			logger.info("generalDataRemainingLen: " + str(int(self.generalDataRemainingLen)))
			self.generalData = data
		elif self.last_state == "dd03" and hex_string.find('dd04') == -1 and hex_string.find('dd03') == -1: 
			self.generalData = self.generalData + data			
			self.generalDataCallback(self.generalData)
			logger.info("Final Length generalData(" + str(len(self.generalData)) + "): " + str(binascii.hexlify(self.generalData).decode('utf-8')))

		if self.last_state == "dd04" and self.cellData and len(self.cellData) == self.cellDataTotalLen:			
			self.last_state = "0000"  # Fixed: was using == instead of =
			self.cellData = None

		if self.last_state == "dd03" and self.generalData and len(self.generalData) == self.generalDataTotalLen:			
			self.last_state = "0000"  # Fixed: was using == instead of =
			self.generalData = None


	def check_watchdog(self):
		if BT_WATCHDOG_TIMEOUT <= 0: # Watchdog disabled
			return

		elapsed = time.monotonic() - self.last_data_received_time

		if elapsed > BT_WATCHDOG_TIMEOUT:
			logger.critical(f'WATCHDOG TRIGGERED for {self.address}! No data received for {elapsed:.1f} seconds (limit: {BT_WATCHDOG_TIMEOUT}s).')
			self.last_data_received_time = time.monotonic() # Reset timer to prevent immediate re-trigger

			if BT_WATCHDOG_ACTION == "reboot":
				logger.critical("Watchdog action: REBOOTING SYSTEM.")
				# Ensure logs are flushed before rebooting
				logging.shutdown()
				# Use a more robust reboot command
				os.system('sync; sleep 1; reboot')
				# Exit script immediately after issuing reboot
				sys.exit(1)
			elif BT_WATCHDOG_ACTION == "log":
				 logger.critical("Watchdog action: Logging error (no reboot configured).")
				 # Mark battery as offline
				 if self.battery_parent:
					 self.battery_parent.online = False
			else:
				logger.error(f"Unknown watchdog action configured: {BT_WATCHDOG_ACTION}")

class JbdBt(Battery):
	def __init__(self, address, config_path=None):
		Battery.__init__(self, 0, 0, address)

		self.protection = JbdProtection()
		self.type = "JBD BT"
		self.online = True # Assume online initially

		# Load custom config if provided
		self.custom_config = None
		if config_path:
			self.load_custom_config(config_path)

		# Bluepy stuff
		self.bt = Peripheral()
		self.bt.setDelegate(self)

		self.mutex = Lock()
		self.generalData = None
		self.generalDataTS = time.monotonic()
		self.cellData = None
		self.cellDataTS = time.monotonic()

		# address is already set by parent class, don't override it
		self.port = "/bt" + self.address.replace(":", "")
		self.interval = 5

		self.dev = JbdBtDev(self.address, self) # Pass self for watchdog offline signaling
		self.dev.addCellDataCallback(self.cellDataCB)
		self.dev.addGeneralDataCallback(self.generalDataCB)
		self.dev.start() # Use start() instead of connect()


	def __del__(self):
		# Destructor to ensure thread cleanup
		if hasattr(self, 'dev') and self.dev.is_alive():
			self.dev.stop()
			self.dev.join(timeout=5.0)


	def stop(self):
		"""Stops the Bluetooth communication thread."""
		if hasattr(self, 'dev') and self.dev.is_alive():
			logger.info(f"Stopping communication thread for {self.address}")
			self.dev.stop()
			self.dev.join(timeout=5.0)


	def load_custom_config(self, config_path):
		"""Load a custom configuration file for this specific battery"""
		try:
			from utils import load_config
			logger.info(f"Loading custom config for {self.address} from {config_path}")
			self.custom_config = load_config(config_path)
			# Apply relevant settings immediately if needed
			if self.custom_config and "DEFAULT" in self.custom_config:
				self.max_battery_charge_current = float(self.custom_config["DEFAULT"].get("MAX_BATTERY_CHARGE_CURRENT", MAX_BATTERY_CHARGE_CURRENT))
				self.max_battery_discharge_current = float(self.custom_config["DEFAULT"].get("MAX_BATTERY_DISCHARGE_CURRENT", MAX_BATTERY_DISCHARGE_CURRENT))
				logger.info(f"Applied custom limits for {self.address}: Charge={self.max_battery_charge_current}A, Discharge={self.max_battery_discharge_current}A")
		except FileNotFoundError:
			logger.error(f"Custom config file not found for {self.address}: {config_path}")
			self.custom_config = None
		except Exception as e:
			logger.error(f"Error loading custom config for {self.address} from {config_path}: {e}")
			self.custom_config = None


	def test_connection(self):
		# Check if the thread is alive and connected
		return self.dev is not None and self.dev.is_alive() and self.dev.is_connected

	def get_settings(self):
		# Wait for initial data with timeout
		start_time = time.monotonic()
		result = False
		while time.monotonic() - start_time < INITIAL_DATA_TIMEOUT_SECONDS:
			result = self.read_gen_data()
			if result:
				logger.info(f"Initial general data received for {self.address}")
				break # Got data
			time.sleep(1)
		
		if not result:
			logger.error(f"Timeout waiting for initial general data from {self.address}")
			self.online = False
			return False
			
		# Use custom config if available, otherwise use global config
		if self.custom_config and "DEFAULT" in self.custom_config:
			self.max_battery_charge_current = float(self.custom_config["DEFAULT"].get("MAX_BATTERY_CHARGE_CURRENT", MAX_BATTERY_CHARGE_CURRENT))
			self.max_battery_discharge_current = float(self.custom_config["DEFAULT"].get("MAX_BATTERY_DISCHARGE_CURRENT", MAX_BATTERY_DISCHARGE_CURRENT))
		else:
			self.max_battery_charge_current = MAX_BATTERY_CHARGE_CURRENT
			self.max_battery_discharge_current = MAX_BATTERY_DISCHARGE_CURRENT
		return result

	def refresh_data(self):
		# Check if thread is alive
		if not self.dev or not self.dev.is_alive():
			logger.error(f"BT communication thread for {self.address} is not running.")
			self.online = False
			return False

		# Check age of data
		gen_data_age = time.monotonic() - self.generalDataTS if self.generalDataTS > 0 else float('inf')
		cell_data_age = time.monotonic() - self.cellDataTS if self.cellDataTS > 0 else float('inf')

		# Consider data stale after ~3 poll intervals
		max_data_age = POLL_INTERVAL_SECONDS * 3
		if gen_data_age > max_data_age or cell_data_age > max_data_age:
			logger.warning(f"Stale data for {self.address}: General={gen_data_age:.1f}s, Cell={cell_data_age:.1f}s (Max={max_data_age}s)")

		# Read latest data (thread should be updating in background)
		gen_result = self.read_gen_data()
		cell_result = self.read_cell_data()
		
		self.online = gen_result or cell_result # Consider online if either parsing worked
		return self.online

	def log_settings(self):
		# Override log_settings() to call get_settings() first
		self.get_settings()
		Battery.log_settings(self)

	def to_protection_bits(self, byte_data):
		tmp = bin(byte_data)[2:].rjust(13, zero_char)

		self.protection.voltage_high = 2 if is_bit_set(tmp[10]) else 0
		self.protection.voltage_low = 2 if is_bit_set(tmp[9]) else 0
		self.protection.temp_high_charge = 1 if is_bit_set(tmp[8]) else 0
		self.protection.temp_low_charge = 1 if is_bit_set(tmp[7]) else 0
		self.protection.temp_high_discharge = 1 if is_bit_set(tmp[6]) else 0
		self.protection.temp_low_discharge = 1 if is_bit_set(tmp[5]) else 0
		self.protection.current_over = 1 if is_bit_set(tmp[4]) else 0
		self.protection.current_under = 1 if is_bit_set(tmp[3]) else 0

		# Software implementations for low soc
		self.protection.soc_low = (
			2 if self.soc < SOC_LOW_ALARM else 1 if self.soc < SOC_LOW_WARNING else 0
		)

		# extra protection flags for LltJbd
		self.protection.set_voltage_low_cell = is_bit_set(tmp[11])
		self.protection.set_voltage_high_cell = is_bit_set(tmp[12])
		self.protection.set_software_lock = is_bit_set(tmp[0])
		self.protection.set_IC_inspection = is_bit_set(tmp[1])
		self.protection.set_short = is_bit_set(tmp[2])

	def to_cell_bits(self, byte_data, byte_data_high):
		# clear the list
		#for c in self.cells:
		#	self.cells.remove(c)
		self.cells: List[Cell] = []

		# get up to the first 16 cells
		tmp = bin(byte_data)[2:].rjust(min(self.cell_count, 16), zero_char)
		for bit in reversed(tmp):
			self.cells.append(Cell(is_bit_set(bit)))

		# get any cells above 16
		if self.cell_count > 16:
			tmp = bin(byte_data_high)[2:].rjust(self.cell_count - 16, zero_char)
			for bit in reversed(tmp):
				self.cells.append(Cell(is_bit_set(bit)))

	def to_fet_bits(self, byte_data):
		tmp = bin(byte_data)[2:].rjust(2, zero_char)
		self.charge_fet = is_bit_set(tmp[1])
		self.discharge_fet = is_bit_set(tmp[0])

	def read_gen_data(self):
		self.mutex.acquire()
		
		if self.generalData is None:
			self.mutex.release()
			return False

		gen_data = self.generalData[4:]  # Skip header
		self.mutex.release()

		if len(gen_data) < 27:
			logger.warning(f"General data packet too short for {self.address}: {len(gen_data)} bytes")
			return False

		try:
			(
				voltage,
				current,
				capacity_remain,
				capacity,
				cycles,
				production,
				balance,
				balance2,
				protection,
				version,
				soc,
				fet,
				cell_count,
				temp_sensors,
			) = unpack_from(">HhHHHHhHHBBBBB", gen_data, 0)
			
			# Apply values with appropriate scaling
			self.voltage = voltage / 100
			self.current = current / 100 * INVERT_CURRENT_MEASUREMENT  # Apply inversion if needed
			self.capacity_remain = capacity_remain / 100
			self.capacity = capacity / 100 if capacity > 0 else BATTERY_CAPACITY
			self.cycles = cycles
			self.production = production  # Could parse into a date format if needed
			self.soc = soc
			self.cell_count = cell_count
			self.temp_sensors = temp_sensors
			
			# Use helper methods for bit values
			self.to_cell_bits(balance, balance2)
			self.version = float(str(version >> 4 & 0x0F) + "." + str(version & 0x0F))
			self.to_fet_bits(fet)
			self.to_protection_bits(protection)
			
			# Calculate min/max voltage based on cell count
			self.max_battery_voltage = MAX_CELL_VOLTAGE * self.cell_count
			self.min_battery_voltage = MIN_CELL_VOLTAGE * self.cell_count

			# Parse temperatures if available
			for t in range(self.temp_sensors):
				try:
					temp1 = unpack_from(">H", gen_data, 23 + (2 * t))[0]
					self.to_temp(t + 1, kelvin_to_celsius(temp1 / 10))
				except Exception as e:
					logger.warning(f"Error parsing temperature {t+1} for {self.address}: {e}")
			
			return True
			
		except struct.error as e:
			logger.error(f"Struct error parsing general data for {self.address}: {e}")
			return False
		except Exception as e:
			logger.error(f"Unexpected error parsing general data for {self.address}: {e}")
			return False

	def read_cell_data(self):
		self.mutex.acquire()
		
		if self.cellData is None:
			self.mutex.release()
			return False

		cell_data = self.cellData[4:]  # Skip header
		self.mutex.release()

		if not hasattr(self, 'cell_count') or self.cell_count <= 0:
			logger.warning(f"Cannot parse cell data for {self.address}, cell count is {getattr(self, 'cell_count', 'None')}")
			return False
			
		if len(cell_data) < self.cell_count * 2:
			logger.warning(f"Cell data packet too short for {self.address}: Got {len(cell_data)} bytes, need {self.cell_count * 2}")
			return False

		try:
			# Initialize cells array if needed
			if len(self.cells) != self.cell_count:
				logger.info(f"Initializing {self.cell_count} cells for {self.address}")
				self.cells = [Cell(False) for _ in range(self.cell_count)]
				
			# Parse cell voltages
			for c in range(self.cell_count):
				try:
					cell_volts = unpack_from(">H", cell_data, c * 2)
					if cell_volts and len(cell_volts) > 0:
						self.cells[c].voltage = cell_volts[0] / 1000
					else:
						logger.debug(f"No voltage data for cell {c+1} of {self.address}")
				except struct.error as e:
					logger.debug(f"Error unpacking voltage for cell {c+1} of {self.address}: {e}")
					self.cells[c].voltage = 0
				except Exception as e:
					logger.warning(f"Unexpected error parsing voltage for cell {c+1} of {self.address}: {e}")
					self.cells[c].voltage = 0
					
			return True
			
		except Exception as e:
			logger.error(f"Error parsing cell data for {self.address}: {e}")
			return False

	def cellDataCB(self, data):
		with self.mutex:
			self.cellData = data
			self.cellDataTS = time.monotonic()
			logger.debug(f"Cell data updated for {self.address}")

	def generalDataCB(self, data):
		with self.mutex:
			self.generalData = data
			self.generalDataTS = time.monotonic()
			logger.debug(f"General data updated for {self.address}")


# Unit test
if __name__ == "__main__":


	batt = JbdBt( "70:3e:97:07:e0:dd" )
	#batt = JbdBt( "70:3e:97:07:e0:d9" )
	#batt = JbdBt( "e0:9f:2a:fd:29:26" )
	#batt = JbdBt( "70:3e:97:08:00:62" )
	#batt = JbdBt( "a4:c1:37:40:89:5e" )
	#batt = JbdBt( "a4:c1:37:00:25:91" )
	batt.get_settings()

	while True:
		batt.refresh_data()
		print("Cells " + str(batt.cell_count) )
		for c in range(batt.cell_count):
			print( str(batt.cells[c].voltage) + "v", end=" " )
		print("")
		time.sleep(5)


