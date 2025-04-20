from battery import Protection, Battery, Cell
from utils import *
from struct import *
import argparse
import sys
import time
import binascii
import atexit



class Virtual(Battery):
	def __init__(self, b1=None, b2=None, b3=None, b4=None, series_config=True, config_files=None):
		Battery.__init__(self, 0, 0, 0)

		self.type = "Virtual"
		self.port = "/" + self.type
		self.series_config = series_config  # True for series, False for parallel
		self.config_files = config_files or {}  # Dict mapping BT address to config file

		self.batts = []
		if b1:
			self.batts.append(b1)
		if b2:
			self.batts.append(b2)
		if b3:
			self.batts.append(b3)
		if b4:
			self.batts.append(b4)
			
		# Load battery-specific configurations if in parallel mode
		if not series_config and self.config_files:
			for bat in self.batts:
				if hasattr(bat, 'address') and bat.address in self.config_files:
					logger.info(f"Loading custom config for battery {bat.address}: {self.config_files[bat.address]}")
					bat.load_custom_config(self.config_files[bat.address])
		

	def test_connection(self):
		return False


	def get_settings(self):
		self.voltage = 0
		self.current = 0
		self.cycles = 0
		self.production = 0
		self.soc = 0
		self.cell_count = 0
		self.capacity = 0
		self.capacity_remain = 0
		self.charge_fet	= True
		self.discharge_fet = True
		
		# Check if we have any batteries to work with
		bcnt = len(self.batts)
		if bcnt == 0:
			logger.error("No batteries in virtual battery configuration")
			return False

		result = False
		# Loop through all batteries
		for b in self.batts:
			try:
				result_b = b.get_settings()
				result = result or result_b
				
				if not result_b:
					logger.warning(f"Failed to get settings from battery {b.address}")
					continue
					
				if self.series_config:
					# SERIES CONFIGURATION
					# Add battery voltages together
					if b.voltage is not None:
						self.voltage += b.voltage
					
					# Add cell counts
					if b.cell_count is not None:
						self.cell_count += b.cell_count

					# Add current values, and div by cell count after the loop to get avg
					if b.current is not None:
						self.current += b.current
					
					# Use the lowest capacity value (conservative)
					if b.capacity is not None and (b.capacity < self.capacity or self.capacity == 0):
						self.capacity = b.capacity

					# Use the lowest capacity_remain value (conservative)
					if b.capacity_remain is not None and (b.capacity_remain < self.capacity_remain or self.capacity_remain == 0):
						self.capacity_remain = b.capacity_remain
				else:
					# PARALLEL CONFIGURATION
					# Use reference voltage from first battery (should be equal in parallel)
					if b.voltage is not None:
						if self.voltage == 0:
							self.voltage = b.voltage
						else:
							# Minor voltage correction (average for displayed value)
							self.voltage = (self.voltage + b.voltage) / 2
					
					# Use the cell count from the first battery (all parallel batteries have same cell count)
					if b.cell_count is not None and self.cell_count == 0:
						self.cell_count = b.cell_count
					
					# Add currents together
					if b.current is not None:
						self.current += b.current
					
					# Add capacities together
					if b.capacity is not None:
						self.capacity += b.capacity
					
					# Add capacity_remain together
					if b.capacity_remain is not None:
						self.capacity_remain += b.capacity_remain

				# Use the highest cycle count (for both configurations)
				if b.cycles is not None and b.cycles > self.cycles:
					self.cycles = b.cycles
				
				# Use the lowest SOC value (conservative for both configurations)
				# For parallel, we could also use a capacity-weighted average, but using the 
				# lowest value is safer to prevent over-discharge
				if b.soc is not None and (b.soc < self.soc or self.soc == 0):
					self.soc = b.soc

				# For parallel batteries, one battery in protective mode shouldn't disable all
				if self.series_config:
					self.charge_fet &= b.charge_fet if b.charge_fet is not None else True
					self.discharge_fet &= b.discharge_fet if b.discharge_fet is not None else True
				else:
					# For parallel, at least one battery should support charge/discharge
					# Only set to False if all batteries are False (using |= to avoid reset to True)
					if b.charge_fet is not None and b.charge_fet is False:
						self.charge_fet &= False
					if b.discharge_fet is not None and b.discharge_fet is False:
						self.discharge_fet &= False
			except Exception as e:
				logger.error(f"Error processing battery {b.address if hasattr(b, 'address') else 'unknown'}: {str(e)}")
				continue

		# Only allocate cells if we have a valid cell count
		if self.cell_count > 0:
			self.cells = [None]*self.cell_count
		else:
			self.cells = []

		# Get number of valid batteries
		active_batteries = sum(1 for b in self.batts if hasattr(b, 'voltage') and b.voltage is not None)
		
		if active_batteries > 0:
			if self.series_config and active_batteries > 0:
				# Avg the current for series configuration (only if we have active batteries)
				self.current /= active_batteries
			
			# Find the first battery with valid temperature data
			temp_battery = next((b for b in self.batts if hasattr(b, 'temp_sensors') and b.temp_sensors is not None), None)
			
			if temp_battery is not None:
				# Use the temp sensors from the first battery with valid data
				self.temp_sensors = temp_battery.temp_sensors
				self.temp1 = temp_battery.temp1
				self.temp2 = temp_battery.temp2
			else:
				logger.warning("No battery with valid temperature data found")


		self.max_battery_voltage = MAX_CELL_VOLTAGE * self.cell_count
		self.min_battery_voltage = MIN_CELL_VOLTAGE * self.cell_count

		self.max_battery_charge_current = MAX_BATTERY_CHARGE_CURRENT
		self.max_battery_discharge_current = MAX_BATTERY_DISCHARGE_CURRENT
		return result


	def refresh_data(self):
		result = self.get_settings()

		# Clear cells list
		self.cells: List[Cell] = []
		
		# Check if we have any batteries
		if not self.batts:
			logger.error("No batteries in virtual battery configuration")
			return False

		result2 = False
		at_least_one_success = False
		
		# Loop through all batteries
		for b in self.batts:
			try:
				result_refresh = b.refresh_data()
				if result_refresh:
					at_least_one_success = True
					
					if self.series_config:
						# In series, we append all cells together
						if hasattr(b, 'cells') and b.cells:
							self.cells += b.cells
					else:
						# In parallel configuration, we use cell data from first battery with valid data
						# This works because in parallel, all cells should have same voltage
						if len(self.cells) == 0 and hasattr(b, 'cells') and b.cells:
							self.cells = b.cells.copy()
				else:
					logger.warning(f"Failed to refresh data from battery {b.address if hasattr(b, 'address') else 'unknown'}")
			except Exception as e:
				logger.error(f"Error refreshing battery {b.address if hasattr(b, 'address') else 'unknown'}: {str(e)}")
				continue
		
		# For troubleshooting - log if no cell data was collected
		if not self.cells:
			logger.warning("No cell data collected from any battery")
		
		# Success if we got data from at least one battery
		result = result and at_least_one_success
		return result


	def log_settings(self):
		# Override log_settings() to call get_settings() first
		self.get_settings()
		logger.info(f"Virtual battery in {'series' if self.series_config else 'parallel'} configuration")
		Battery.log_settings(self)





# Unit test
if __name__ == "__main__":
	from jbdbt import JbdBt
	import sys

	# Parse command line for testing
	series_config = True  # Default to series
	if len(sys.argv) > 1 and sys.argv[1].lower() in ['-p', '--parallel']:
		series_config = False
		print("Testing in PARALLEL configuration")
	else:
		print("Testing in SERIES configuration")

	batt1 = JbdBt("70:3e:97:08:00:62")
	batt2 = JbdBt("a4:c1:37:40:89:5e")

	vbatt = Virtual(batt1, batt2, series_config=series_config)

	vbatt.get_settings()

	print("Configuration: " + ("Parallel" if not vbatt.series_config else "Series"))
	print("Cells: " + str(vbatt.cell_count))
	print("Voltage: " + str(vbatt.voltage) + "V")
	print("Capacity: " + str(vbatt.capacity) + "Ah")

	while True:
		vbatt.refresh_data()

		print("\n--- Battery Status ---")
		print("Cells: " + str(vbatt.cell_count))
		print("Voltage: " + str(vbatt.voltage) + "V")
		print("Current: " + str(vbatt.current) + "A")
		print("SOC: " + str(vbatt.soc) + "%")
		print("Capacity: " + str(vbatt.capacity) + "Ah")
		print("Capacity Remaining: " + str(vbatt.capacity_remain) + "Ah")
		print("Charge FET: " + str(vbatt.charge_fet))
		print("Discharge FET: " + str(vbatt.discharge_fet))

		print("Cell Voltages:", end=" ")
		for c in range(vbatt.cell_count):
			print(str(vbatt.cells[c].voltage) + "V", end=" ")
		print("")

		time.sleep(5)



