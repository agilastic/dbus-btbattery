from battery import Protection, Battery, Cell
from utils import *
from struct import *
import argparse
import sys
import time
import binascii
import atexit



class Virtual(Battery):
	def __init__(self, batteries=None, b1=None, b2=None, b3=None, b4=None, series_config=True, config_files=None):
		Battery.__init__(self, "/virtual", 0, 0)  # Use meaningful port path

		self.type = "Virtual"
		self.series_config = series_config  # True for series, False for parallel
		self.online = True # Assume online initially

		# Initialize battery list - either from batteries list or individual parameters
		self.batts = []
		if batteries and isinstance(batteries, list):
			self.batts = batteries
		else:
			# For backward compatibility
			if b1: self.batts.append(b1)
			if b2: self.batts.append(b2)
			if b3: self.batts.append(b3)
			if b4: self.batts.append(b4)
			
		# Initialize aggregated attributes
		self._initialize_attributes()
		
		# Log battery info
		logger.info(f"Virtual battery created with {len(self.batts)} components in {'series' if series_config else 'parallel'} mode.")
		

	def _initialize_attributes(self):
		"""Sets initial/default values for aggregated attributes."""
		self.voltage = 0.0
		self.current = 0.0
		self.capacity_remain = 0.0
		self.capacity = 0.0
		self.soc = None # Start with unknown SOC
		self.cycles = 0
		self.production = None
		self.charge_fet = True # Assume FETs are initially on
		self.discharge_fet = True
		self.cell_count = 0
		self.temp_sensors = 0
		self.temp1 = None
		self.temp2 = None
		self.cells = [] # Empty cell list initially
		self.max_battery_voltage = None
		self.min_battery_voltage = None
		self.max_battery_charge_current = MAX_BATTERY_CHARGE_CURRENT
		self.max_battery_discharge_current = MAX_BATTERY_DISCHARGE_CURRENT
		
	def test_connection(self):
		# Test connection by checking if at least one component battery tests positive
		if not self.batts:
			return False
		for b in self.batts:
			try:
				if b.test_connection():
					return True
			except Exception as e:
				logger.warning(f"Error testing connection for component battery {getattr(b, 'address', 'N/A')}: {e}")
		return False


	def get_settings(self):
		logger.info("Getting settings for virtual battery components...")
		if not self.batts:
			logger.error("Virtual battery has no components.")
			self.online = False
			return False

		# Reset aggregated values
		self._initialize_attributes()

		any_success = False
		# Get data from each component battery
		for b in self.batts:
			try:
				if b.get_settings():
					any_success = True
					# Mark battery as online if available
					if hasattr(b, 'online'):
						b.online = True
				else:
					logger.warning(f"Failed to get settings from battery {getattr(b, 'address', 'N/A')}")
					# Mark battery as offline if available
					if hasattr(b, 'online'):
						b.online = False
			except Exception as e:
				logger.error(f"Error getting settings from battery {getattr(b, 'address', 'N/A')}: {e}")
				# Mark battery as offline if available
				if hasattr(b, 'online'):
					b.online = False

		if not any_success:
			logger.error("Failed to get settings from any component battery.")
			self.online = False
			return False

		# Perform data aggregation
		self._aggregate_data()
		
		return True


	def refresh_data(self):
		logger.debug("Refreshing data for virtual battery components...")
		if not self.batts:
			logger.error("Virtual battery has no components.")
			self.online = False
			return False

		# Reset aggregated values
		self._initialize_attributes()

		any_success = False
		# Get data from each component battery
		for b in self.batts:
			try:
				if b.refresh_data():
					any_success = True
					# Mark battery as online if available
					if hasattr(b, 'online'):
						b.online = True
				else:
					logger.warning(f"Failed to refresh data from battery {getattr(b, 'address', 'N/A')}")
					# Mark battery as offline if available
					if hasattr(b, 'online'):
						b.online = False
			except Exception as e:
				logger.error(f"Error refreshing data from battery {getattr(b, 'address', 'N/A')}: {e}")
				# Mark battery as offline if available
				if hasattr(b, 'online'):
					b.online = False

		if not any_success:
			logger.warning("Failed to refresh data from any component battery.")
			self.online = False
			return False

		# Perform data aggregation
		self._aggregate_data()
		
		# Return True if we are considered online after aggregation
		return self.online


	def _aggregate_data(self):
		"""
		Aggregates data from component batteries into the virtual battery's attributes.
		This should be called AFTER component batteries have been refreshed or had settings read.
		"""
		logger.debug(f"Aggregating data for virtual battery ({'series' if self.series_config else 'parallel'})...")

		if not self.batts:
			logger.warning("No batteries to aggregate data from.")
			self.online = False
			return

		active_batteries = 0
		total_current = 0.0
		total_capacity = 0.0
		total_capacity_remain = 0.0
		min_soc = 101.0  # Start high to find minimum SOC
		max_cycles = 0
		first_valid_voltage = None
		sum_voltages = 0.0 # For averaging parallel voltage display
		all_cells = []
		min_charge_fet = True # Assume True unless one is False
		min_discharge_fet = True # Assume True unless one is False
		temp_data_source = None # Find first battery with temp data

		# Loop through all batteries and collect data
		for b in self.batts:
			# Skip offline batteries
			if hasattr(b, 'online') and not b.online:
				logger.debug(f"Skipping offline battery {getattr(b, 'address', 'N/A')}")
				continue

			valid_data_found = False
			if b.voltage is not None:
				valid_data_found = True
				sum_voltages += b.voltage
				if self.series_config:
					self.voltage += b.voltage
				elif first_valid_voltage is None:
					first_valid_voltage = b.voltage # Use first as reference for parallel

			if b.current is not None:
				valid_data_found = True
				total_current += b.current

			if b.capacity is not None and b.capacity > 0:
				valid_data_found = True
				if self.series_config:
					# Use lowest capacity for series (most conservative)
					if self.capacity == 0.0 or b.capacity < self.capacity:
						self.capacity = b.capacity
				else: # Parallel
					total_capacity += b.capacity

			if b.capacity_remain is not None:
				valid_data_found = True
				if self.series_config:
					# Use lowest remaining capacity for series (most conservative)
					if self.capacity_remain == 0.0 or b.capacity_remain < self.capacity_remain:
						self.capacity_remain = b.capacity_remain
				else: # Parallel
					total_capacity_remain += b.capacity_remain

			if b.soc is not None:
				valid_data_found = True
				# Use lowest SOC for both modes (conservative)
				if b.soc < min_soc:
					min_soc = b.soc

			if b.cycles is not None:
				valid_data_found = True
				# Use highest cycle count for both modes
				if b.cycles > max_cycles:
					max_cycles = b.cycles

			if b.cell_count is not None and b.cell_count > 0:
				valid_data_found = True
				if self.series_config:
					self.cell_count += b.cell_count
				elif self.cell_count == 0: # Parallel: use first battery's count
					self.cell_count = b.cell_count

				# Cell aggregation
				if hasattr(b, 'cells') and b.cells:
					if self.series_config:
						all_cells.extend(b.cells) # Append all cells for series
					elif not all_cells: # Parallel: Take cells from first battery providing them
						all_cells = b.cells[:] # Make a copy

			# FET status aggregation
			if b.charge_fet is False: min_charge_fet = False
			if b.discharge_fet is False: min_discharge_fet = False

			# Temperature data source
			if temp_data_source is None and hasattr(b, 'temp_sensors') and b.temp_sensors:
				temp_data_source = b # Use first battery with temp sensors

			if valid_data_found:
				active_batteries += 1

		# --- Final calculations ---
		if active_batteries == 0:
			logger.warning("No active batteries found during aggregation.")
			self.online = False
			return

		# Assign aggregated values
		self.cycles = max_cycles
		self.soc = min_soc if min_soc <= 100 else None
		self.charge_fet = min_charge_fet
		self.discharge_fet = min_discharge_fet
		self.cells = all_cells

		if self.series_config:
			# Voltage is already summed
			# Capacity is already minimized
			# Capacity remain is already minimized
			# Average current across active series batteries
			self.current = total_current / active_batteries if active_batteries > 0 else 0.0
		else: # Parallel
			# Use average voltage for display (more accurate than first)
			self.voltage = sum_voltages / active_batteries if active_batteries > 0 else 0.0
			if first_valid_voltage is not None and self.voltage == 0.0:
				self.voltage = first_valid_voltage # Fallback to first valid voltage
			self.current = total_current # Sum currents
			self.capacity = total_capacity # Sum capacities
			self.capacity_remain = total_capacity_remain # Sum remaining

		# Assign temperature data
		if temp_data_source:
			self.temp_sensors = getattr(temp_data_source, 'temp_sensors', 0)
			self.temp1 = getattr(temp_data_source, 'temp1', None)
			self.temp2 = getattr(temp_data_source, 'temp2', None)
		else:
			logger.debug("No temperature data found from component batteries.")

		# Calculate overall min/max voltage limits based on aggregated cell count
		if self.cell_count > 0:
			self.max_battery_voltage = MAX_CELL_VOLTAGE * self.cell_count
			self.min_battery_voltage = MIN_CELL_VOLTAGE * self.cell_count
		else:
			logger.warning("Virtual battery cell count is zero after aggregation.")

		self.online = True # Mark as online after successful aggregation
		logger.debug(f"Aggregation complete. Voltage={self.voltage:.2f}V, Current={self.current:.2f}A, SOC={self.soc}%, Cells={self.cell_count}")


	def log_settings(self):
		# Settings should be aggregated before logging
		logger.info(f"--- Virtual Battery ({'Series' if self.series_config else 'Parallel'}) ---")
		logger.info(f"> Component Batteries: {len(self.batts)}")
		
		# Call the base class method to log common settings
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



