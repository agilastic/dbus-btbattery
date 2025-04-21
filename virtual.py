#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from battery import Protection, Battery, Cell
import utils
from utils import (
    logger, MAX_CELL_VOLTAGE, MIN_CELL_VOLTAGE, 
    MAX_BATTERY_CHARGE_CURRENT, MAX_BATTERY_DISCHARGE_CURRENT,
    SOC_IMBALANCE_DETECTION_ENABLE, SOC_IMBALANCE_THRESHOLD  
)
import time
import copy
from typing import List, Dict, Any, Optional, Union

class Virtual(Battery):
    """
    Enhanced Virtual Battery implementation with better parallel battery support.
    This class creates a virtual battery by combining data from multiple physical batteries
    in either series or parallel configuration.
    """
    
    def __init__(self, batteries=None, b1=None, b2=None, b3=None, b4=None, series_config=True, config_files=None):
        """
        Initialize the virtual battery with component batteries.
        
        Args:
            batteries: List of Battery objects (new style)
            b1, b2, b3, b4: Individual Battery objects (old style)
            series_config: True for series configuration, False for parallel
            config_files: Dict of battery configs (not used, for compatibility)
        """
        Battery.__init__(self, "/virtual", 0, 0)  # Use meaningful port path
        
        self.type = "Virtual"
        self.series_config = series_config  # True for series, False for parallel
        self.online = True  # Assume online initially
        self.last_full_update = 0  # Timestamp of last successful full update
        
        # Initialize battery list from either format
        self.batts = []
        if batteries and isinstance(batteries, list):
            self.batts = batteries
        else:
            # For backward compatibility
            if b1 is not None: 
                self.batts.append(b1)
            if b2 is not None: 
                self.batts.append(b2)
            if b3 is not None: 
                self.batts.append(b3)
            if b4 is not None: 
                self.batts.append(b4)
        
        # Initialize properties
        self._initialize_properties()
        
        # Create protection object
        self.protection = Protection()
        
        # Parallel-specific attributes
        self.voltage_imbalance = False
        self.current_imbalance = False
        self.soc_imbalance = False
        
        # Log battery info
        logger.info(f"Virtual battery created with {len(self.batts)} components in {'series' if series_config else 'parallel'} mode.")
    
    def _initialize_properties(self):
        """Initialize basic battery properties with default values."""
        self.voltage = 0.0
        self.current = 0.0
        self.capacity_remain = 0.0
        self.capacity = 0.0
        self.soc = None
        self.cycles = 0
        self.production = None
        self.charge_fet = True 
        self.discharge_fet = True
        self.cell_count = 0
        self.temp_sensors = 0
        self.temp1 = None
        self.temp2 = None
        self.cells = []
        self.max_battery_voltage = None
        self.min_battery_voltage = None
        self.hardware_version = "1.0"
        self.version = 1.0
        self.total_ah_drawn = 0.0
        
        # Charge control parameters - these will be populated on first refresh
        self.control_voltage = None
        self.control_charge_current = None
        self.control_discharge_current = None
        self.control_allow_charge = True
        self.control_allow_discharge = True
        self.max_battery_charge_current = MAX_BATTERY_CHARGE_CURRENT
        self.max_battery_discharge_current = MAX_BATTERY_DISCHARGE_CURRENT
    
    def test_connection(self) -> bool:
        """
        Test connection to at least one of the component batteries.
        
        Returns:
            bool: True if at least one battery is connected
        """
        if not self.batts:
            return False
        
        for battery in self.batts:
            try:
                if battery.test_connection():
                    return True
            except Exception as e:
                logger.warning(f"Error testing connection for battery {getattr(battery, 'address', 'N/A')}: {e}")
        
        return False
    
    def get_settings(self) -> bool:
        """
        Get settings from all component batteries and aggregate them.
        
        Returns:
            bool: True if at least one battery provided settings
        """
        logger.info("Getting settings for virtual battery components...")
        if not self.batts:
            logger.error("Virtual battery has no components.")
            self.online = False
            return False
        
        # Reset aggregated values
        self._initialize_properties()
        
        any_success = False
        # Get data from each component battery
        for battery in self.batts:
            try:
                has_online = hasattr(battery, 'online')
                if battery.get_settings():
                    any_success = True
                    # Mark battery as online
                    if has_online:
                        battery.online = True
                else:
                    logger.warning(f"Failed to get settings from battery {getattr(battery, 'address', 'N/A')}")
                    # Mark battery as offline
                    if has_online:
                        battery.online = False
            except Exception as e:
                logger.error(f"Error getting settings from battery {getattr(battery, 'address', 'N/A')}: {e}")
                # Mark battery as offline
                if hasattr(battery, 'online'):
                    battery.online = False
        
        if not any_success:
            logger.error("Failed to get settings from any component battery.")
            self.online = False
            return False
        
        # Aggregate data from all batteries
        self._aggregate_data()
        
        # Set initial charge control parameters
        self._set_initial_charge_parameters()
        
        self.last_full_update = time.time()
        return True
    
    def _set_initial_charge_parameters(self) -> None:
        """Set initial charge control parameters based on configuration."""
        if self.series_config:
            # For series: use minimum of all batteries (most conservative)
            charge_currents = [b.max_battery_charge_current 
                              for b in self.batts 
                              if hasattr(b, 'max_battery_charge_current') and 
                              b.max_battery_charge_current is not None]
            
            discharge_currents = [b.max_battery_discharge_current 
                                 for b in self.batts 
                                 if hasattr(b, 'max_battery_discharge_current') and 
                                 b.max_battery_discharge_current is not None]
            
            self.max_battery_charge_current = (
                min(charge_currents) if charge_currents else MAX_BATTERY_CHARGE_CURRENT
            )
            
            self.max_battery_discharge_current = (
                min(discharge_currents) if discharge_currents else MAX_BATTERY_DISCHARGE_CURRENT
            )
        else:
            # For parallel: sum the currents
            charge_currents = [b.max_battery_charge_current 
                              for b in self.batts 
                              if hasattr(b, 'max_battery_charge_current') and 
                              b.max_battery_charge_current is not None]
            
            discharge_currents = [b.max_battery_discharge_current 
                                 for b in self.batts 
                                 if hasattr(b, 'max_battery_discharge_current') and 
                                 b.max_battery_discharge_current is not None]
            
            self.max_battery_charge_current = (
                sum(charge_currents) if charge_currents else MAX_BATTERY_CHARGE_CURRENT
            )
            
            self.max_battery_discharge_current = (
                sum(discharge_currents) if discharge_currents else MAX_BATTERY_DISCHARGE_CURRENT
            )
        
        # Initialize control parameters with max values
        self.control_charge_current = self.max_battery_charge_current
        self.control_discharge_current = self.max_battery_discharge_current
    
    def refresh_data(self) -> bool:
        """
        Refresh data from all component batteries and aggregate results.
        
        Returns:
            bool: True if at least one battery provided data
        """
        logger.debug("Refreshing data for virtual battery components...")
        if not self.batts:
            logger.error("Virtual battery has no components.")
            self.online = False
            return False
        
        any_success = False
        # Get data from each component battery
        for battery in self.batts:
            try:
                has_online = hasattr(battery, 'online')
                if battery.refresh_data():
                    any_success = True
                    # Mark battery as online
                    if has_online:
                        battery.online = True
                else:
                    logger.warning(f"Failed to refresh data from battery {getattr(battery, 'address', 'N/A')}")
                    # Mark battery as offline if available
                    if has_online:
                        battery.online = False
            except Exception as e:
                logger.error(f"Error refreshing data from battery {getattr(battery, 'address', 'N/A')}: {e}")
                # Mark battery as offline if available
                if hasattr(battery, 'online'):
                    battery.online = False
        
        if not any_success:
            logger.warning("Failed to refresh data from any component battery.")
            self.online = False
            return False
        
        # Aggregate data from all batteries
        self._aggregate_data()
        
        # Update virtual battery control parameters
        self._update_control_parameters()
        
        self.last_full_update = time.time()
        return self.online
    
    def _update_control_parameters(self) -> None:
        """Update charge and discharge control parameters based on battery state."""
        # If we are in parallel mode, call manage_charge_current on each battery first
        if not self.series_config:
            for battery in self.batts:
                if (hasattr(battery, 'online') and battery.online and 
                    hasattr(battery, 'manage_charge_current')):
                    try:
                        battery.manage_charge_current()
                    except Exception as e:
                        logger.warning(
                            f"Error managing charge current for battery "
                            f"{getattr(battery, 'address', 'N/A')}: {e}"
                        )
        
        # Then call the virtual battery's own management functions
        try:
            self.manage_charge_voltage()
            self.manage_charge_current()
        except Exception as e:
            logger.error(f"Error updating control parameters: {e}")
    
    def _aggregate_data(self) -> None:
        """
        Aggregate data from all component batteries based on the configuration.
        Uses different logic for series and parallel configurations.
        """
        logger.debug(f"Aggregating data for virtual battery ({'series' if self.series_config else 'parallel'})...")
        
        if not self.batts:
            logger.warning("No batteries to aggregate data from.")
            self.online = False
            return
        
        # Get list of active batteries
        active_batteries = [b for b in self.batts if hasattr(b, 'online') and b.online]
        
        if not active_batteries:
            logger.warning("No active batteries found during aggregation.")
            self.online = False
            return
        
        # Reset imbalance flags for parallel batteries
        if not self.series_config:
            self.voltage_imbalance = False
            self.current_imbalance = False
            self.soc_imbalance = False
        
        # Call appropriate aggregation function based on configuration
        if self.series_config:
            self._aggregate_series_data(active_batteries)
        else:
            self._aggregate_parallel_data(active_batteries)
        
        # Calculate battery voltage limits based on cell count
        if self.cell_count > 0:
            self.max_battery_voltage = MAX_CELL_VOLTAGE * self.cell_count
            self.min_battery_voltage = MIN_CELL_VOLTAGE * self.cell_count
        else:
            logger.warning("Virtual battery cell count is zero after aggregation.")
            self.max_battery_voltage = 0
            self.min_battery_voltage = 0
        
        # Mark as online after successful aggregation
        self.online = True
        
        if self.voltage is not None and self.current is not None and self.soc is not None:
            logger.debug(
                f"Aggregation complete: {self.cell_count} cells, "
                f"{self.voltage:.2f}V, {self.current:.2f}A, {self.soc:.1f}% SOC"
            )
    
    def _aggregate_series_data(self, active_batteries: List[Battery]) -> None:
        """
        Aggregate data for batteries connected in series.
        
        Args:
            active_batteries: List of active Battery objects
        """
        # Reset values that will be aggregated
        self.voltage = 0.0
        current_sum = 0.0
        current_count = 0
        self.capacity_remain = None
        self.capacity = None
        self.soc = None
        self.cycles = 0
        self.cell_count = 0
        self.cells = []
        min_charge_fet = True
        min_discharge_fet = True
        temp_readings = []
        total_ah_drawn_sum = 0.0
        
        # Aggregate series data:
        # - Voltages add up
        # - Current is the same (average to account for sensor differences)
        # - Capacity is limited by the smallest battery
        # - SOC is determined by the lowest battery SOC
        
        for battery in active_batteries:
            # Voltage adds up in series
            if hasattr(battery, 'voltage') and battery.voltage is not None:
                self.voltage += battery.voltage
            
            # Current should be the same in series (average for sensor differences)
            if hasattr(battery, 'current') and battery.current is not None:
                current_sum += battery.current
                current_count += 1
            
            # Use the lowest capacity (most conservative)
            if hasattr(battery, 'capacity') and battery.capacity is not None and battery.capacity > 0:
                if self.capacity is None or battery.capacity < self.capacity:
                    self.capacity = battery.capacity
            
            # Use the lowest remaining capacity (most conservative)
            if hasattr(battery, 'capacity_remain') and battery.capacity_remain is not None:
                if self.capacity_remain is None or battery.capacity_remain < self.capacity_remain:
                    self.capacity_remain = battery.capacity_remain
            
            # Use the lowest SOC (most conservative)
            if hasattr(battery, 'soc') and battery.soc is not None:
                if self.soc is None or battery.soc < self.soc:
                    self.soc = battery.soc
            
            # Use the highest cycle count
            if hasattr(battery, 'cycles') and battery.cycles is not None and battery.cycles > self.cycles:
                self.cycles = battery.cycles
            
            # Total Ah drawn (sum)
            if hasattr(battery, 'total_ah_drawn') and battery.total_ah_drawn is not None:
                total_ah_drawn_sum += battery.total_ah_drawn
            
            # Cell count adds up in series
            if hasattr(battery, 'cell_count') and battery.cell_count is not None:
                self.cell_count += battery.cell_count
            
            # Cells: append all cells in series configuration
            if hasattr(battery, 'cells') and battery.cells:
                # Create deep copies of cell objects to avoid modifying originals
                self.cells.extend(copy.deepcopy(battery.cells))
            
            # FET status (if any battery disables, all are disabled in series)
            if hasattr(battery, 'charge_fet') and battery.charge_fet is False:
                min_charge_fet = False
            if hasattr(battery, 'discharge_fet') and battery.discharge_fet is False:
                min_discharge_fet = False
            
            # Collect temperature data
            if hasattr(battery, 'temp1') and battery.temp1 is not None:
                temp_readings.append(battery.temp1)
            if hasattr(battery, 'temp2') and battery.temp2 is not None:
                temp_readings.append(battery.temp2)
        
        # Set current (average)
        if current_count > 0:
            self.current = current_sum / current_count
        
        # Set total Ah drawn
        self.total_ah_drawn = total_ah_drawn_sum
        
        # Set FET status
        self.charge_fet = min_charge_fet
        self.discharge_fet = min_discharge_fet
        
        # Set temperature data (use max for safety)
        if temp_readings:
            self.temp1 = max(temp_readings)
            self.temp_sensors = 1
            
            # If we have multiple temperatures, use second highest for temp2
            if len(temp_readings) > 1:
                temp_readings.sort(reverse=True)
                self.temp2 = temp_readings[1]
                self.temp_sensors = 2
        
        # Aggregate protection flags
        self._aggregate_protection_flags(active_batteries)
    
    def _aggregate_parallel_data(self, active_batteries: List[Battery]) -> None:
        """
        Aggregate data for batteries connected in parallel.
        
        Args:
            active_batteries: List of active Battery objects
        """
        # Reset values that will be aggregated
        voltage_sum = 0.0
        voltage_count = 0
        self.current = 0.0
        self.capacity_remain = 0.0
        self.capacity = 0.0
        soc_readings = []
        self.cycles = 0
        self.cell_count = 0
        self.cells = []
        any_charge_fet = False
        any_discharge_fet = False
        temp_readings = []
        total_ah_drawn_sum = 0.0
        
        # Variables for detecting imbalance
        voltages = []
        currents = []
        socs = []
        first_battery_with_cells = None
        
        # Aggregate parallel data:
        # - Voltage is the same (average to account for sensor differences)
        # - Currents add up
        # - Capacities add up
        # - SOC is weighted average based on capacity
        
        for battery in active_batteries:
            # Voltage (collect for averaging)
            if hasattr(battery, 'voltage') and battery.voltage is not None:
                voltage_sum += battery.voltage
                voltage_count += 1
                voltages.append(battery.voltage)
            
            # Current adds up in parallel
            if hasattr(battery, 'current') and battery.current is not None:
                self.current += battery.current
                currents.append(battery.current)
            
            # Capacity adds up in parallel
            if hasattr(battery, 'capacity') and battery.capacity is not None and battery.capacity > 0:
                self.capacity += battery.capacity
                
                # Collect capacity and SoC for weighted average
                if hasattr(battery, 'soc') and battery.soc is not None:
                    soc_readings.append((battery.soc, battery.capacity))
                    socs.append(battery.soc)
            
            # Capacity remaining adds up in parallel
            if hasattr(battery, 'capacity_remain') and battery.capacity_remain is not None:
                self.capacity_remain += battery.capacity_remain
            
            # Cycles: use highest value
            if hasattr(battery, 'cycles') and battery.cycles is not None and battery.cycles > self.cycles:
                self.cycles = battery.cycles
            
            # Total Ah drawn (sum)
            if hasattr(battery, 'total_ah_drawn') and battery.total_ah_drawn is not None:
                total_ah_drawn_sum += battery.total_ah_drawn
            
            # Cell count: use first battery's count for parallel (all should be the same)
            if (self.cell_count == 0 and hasattr(battery, 'cell_count') and 
                battery.cell_count is not None and battery.cell_count > 0):
                self.cell_count = battery.cell_count
            
            # For virtual battery in parallel mode, collect all batteries' cells 
            # but only use the first battery's cells for the main display
            # Individual physical battery data is preserved in PhysicalBatteryCellData
            if (not self.cells and hasattr(battery, 'cells') and 
                battery.cells and not first_battery_with_cells):
                # Deep copy to avoid modifying original
                self.cells = copy.deepcopy(battery.cells)
                first_battery_with_cells = battery
                
            # Ensure all physical batteries maintain their cell data
            # This is needed for the cell monitor to show per-battery details
            if hasattr(battery, 'cells') and battery.cells:
                # Preserve the battery's cells without modification
                pass
            
            # FET status (in parallel, we need at least one battery to allow charge/discharge)
            if hasattr(battery, 'charge_fet') and battery.charge_fet is True:
                any_charge_fet = True
            if hasattr(battery, 'discharge_fet') and battery.discharge_fet is True:
                any_discharge_fet = True
            
            # Collect temperature data
            if hasattr(battery, 'temp1') and battery.temp1 is not None:
                temp_readings.append(battery.temp1)
            if hasattr(battery, 'temp2') and battery.temp2 is not None:
                temp_readings.append(battery.temp2)
        
        # Set voltage (average)
        if voltage_count > 0:
            self.voltage = voltage_sum / voltage_count
        
        # Set total Ah drawn
        self.total_ah_drawn = total_ah_drawn_sum
        
        # Set SOC (weighted average based on capacity)
        if soc_readings:
            total_capacity = sum(capacity for _, capacity in soc_readings)
            # Avoid division by zero
            if total_capacity > 0:
                self.soc = sum(soc * (capacity / total_capacity) for soc, capacity in soc_readings)
            else:
                # If no valid capacity, use average SOC
                self.soc = sum(soc for soc, _ in soc_readings) / len(soc_readings) if soc_readings else None
        
        # Set FET status
        self.charge_fet = any_charge_fet
        self.discharge_fet = any_discharge_fet
        
        # Set temperature data (use max for safety)
        if temp_readings:
            self.temp1 = max(temp_readings)
            self.temp_sensors = 1
            
            # If we have multiple temperatures, use second highest for temp2
            if len(temp_readings) > 1:
                temp_readings.sort(reverse=True)
                self.temp2 = temp_readings[1]
                self.temp_sensors = 2
        
        # Check for imbalances
        if len(voltages) > 1:
            max_v = max(voltages)
            min_v = min(voltages)
            # Consider imbalance if > 0.3V difference
            if max_v - min_v > 0.3:
                self.voltage_imbalance = True
                logger.warning(f"Parallel battery voltage imbalance detected: min={min_v:.2f}V, max={max_v:.2f}V")
        
        if len(currents) > 1:
            max_c = max(currents)
            min_c = min(currents)
            # Consider imbalance if > 20% difference between batteries with significant current
            if max_c > 5.0 and max_c != 0 and abs(max_c - min_c) / max_c > 0.2:
                self.current_imbalance = True
                logger.warning(f"Parallel battery current imbalance detected: min={min_c:.2f}A, max={max_c:.2f}A")
        
        if len(socs) > 1:
            max_soc = max(socs)
            min_soc = min(socs)
            # Check if SOC imbalance detection is enabled and threshold is exceeded
            if utils.SOC_IMBALANCE_DETECTION_ENABLE and max_soc - min_soc > utils.SOC_IMBALANCE_THRESHOLD:
                self.soc_imbalance = True
                logger.warning(f"Parallel battery SOC imbalance detected: min={min_soc:.1f}%, max={max_soc:.1f}%")
        
        # Aggregate protection flags
        self._aggregate_protection_flags(active_batteries)
    
    def _aggregate_protection_flags(self, active_batteries: List[Battery]) -> None:
        """
        Aggregate protection flags from all active batteries.
        Uses most conservative approach (if any battery has a warning/alarm, the virtual battery does too).
        
        Args:
            active_batteries: List of active battery objects
        """
        # Protection fields to check
        protection_fields = [
            'voltage_high', 'voltage_low', 'voltage_cell_low', 'soc_low',
            'current_over', 'current_under', 'cell_imbalance', 'internal_failure',
            'temp_high_charge', 'temp_low_charge', 'temp_high_discharge', 'temp_low_discharge'
        ]
        
        # Reset protection flags
        for field in protection_fields:
            setattr(self.protection, field, 0)
        
        # Aggregate flags (most conservative approach)
        for battery in active_batteries:
            if hasattr(battery, 'protection'):
                for field in protection_fields:
                    if hasattr(battery.protection, field):
                        current_value = getattr(self.protection, field) or 0
                        battery_value = getattr(battery.protection, field) or 0
                        # Take highest value (2=alarm, 1=warning, 0=no alarm)
                        setattr(self.protection, field, max(current_value, battery_value))
        
        # For parallel configuration, add imbalance warnings
        if not self.series_config:
            if self.voltage_imbalance or self.current_imbalance or self.soc_imbalance:
                # At least warning level
                self.protection.cell_imbalance = max(self.protection.cell_imbalance or 0, 1)
    
    def manage_charge_voltage(self) -> None:
        """
        Manages charge voltage based on configuration and battery status.
        For parallel batteries, uses cell data from the reference battery.
        """
        # If no cells, use default values
        if not hasattr(self, 'cells') or not self.cells:
            logger.warning("No cell data available for voltage management")
            if self.max_battery_voltage is not None:
                self.control_voltage = self.max_battery_voltage
            else:
                # Set a reasonable default if max_battery_voltage is not set
                self.control_voltage = MAX_CELL_VOLTAGE * self.cell_count if self.cell_count > 0 else 0
            return
        
        # For parallel, use careful approach if imbalance detected
        if not self.series_config and (self.voltage_imbalance or self.soc_imbalance):
            # Reduce max voltage slightly for safety when imbalance detected
            if self.voltage is not None and self.min_battery_voltage is not None:
                self.control_voltage = max(self.voltage, self.min_battery_voltage)
                adjustment = 0.05 * self.cell_count  # 50mV per cell reduction
                
                if self.control_voltage > self.min_battery_voltage + adjustment:
                    self.control_voltage -= adjustment
                    logger.info(f"Reducing charge voltage due to imbalance: {self.control_voltage:.2f}V")
            else:
                # If voltage is not set, use safe default
                self.control_voltage = MAX_CELL_VOLTAGE * 0.95 * self.cell_count if self.cell_count > 0 else 0
            return
        
        # Otherwise use standard implementation
        try:
            super().manage_charge_voltage()
        except Exception as e:
            logger.error(f"Error in manage_charge_voltage: {e}")
            # Fallback to safe value
            if self.max_battery_voltage is not None:
                self.control_voltage = self.max_battery_voltage
            else:
                self.control_voltage = MAX_CELL_VOLTAGE * self.cell_count if self.cell_count > 0 else 0
    
    def manage_charge_current(self) -> None:
        """
        Manages charge/discharge current limits based on battery status.
        For parallel batteries, considers individual battery limits.
        """
        if not self.batts:
            # No physical batteries, use standard limits
            self.control_charge_current = self.max_battery_charge_current
            self.control_discharge_current = self.max_battery_discharge_current
            self.control_allow_charge = True
            self.control_allow_discharge = True
            return
        
        # Get online battery count
        active_count = sum(1 for b in self.batts if hasattr(b, 'online') and b.online)
        
        if active_count == 0:
            # No active batteries
            self.control_charge_current = 0
            self.control_discharge_current = 0
            self.control_allow_charge = False
            self.control_allow_discharge = False
            return
        
        if self.series_config:
            # For series, use standard implementation
            try:
                super().manage_charge_current()
            except Exception as e:
                logger.error(f"Error in standard manage_charge_current: {e}")
                # Fallback to safe values
                self.control_charge_current = self.max_battery_charge_current
                self.control_discharge_current = self.max_battery_discharge_current
        else:
            # For parallel, accumulate from individual batteries
            charge_currents = []
            discharge_currents = []
            
            for battery in self.batts:
                if hasattr(battery, 'online') and battery.online:
                    # Get current limits from individual batteries
                    if hasattr(battery, 'control_charge_current') and battery.control_charge_current is not None:
                        charge_currents.append(battery.control_charge_current)
                    elif hasattr(battery, 'max_battery_charge_current') and battery.max_battery_charge_current is not None:
                        charge_currents.append(battery.max_battery_charge_current)
                    
                    if hasattr(battery, 'control_discharge_current') and battery.control_discharge_current is not None:
                        discharge_currents.append(battery.control_discharge_current)
                    elif hasattr(battery, 'max_battery_discharge_current') and battery.max_battery_discharge_current is not None:
                        discharge_currents.append(battery.max_battery_discharge_current)
            
            # Sum the currents
            if charge_currents:
                self.control_charge_current = sum(charge_currents)
            else:
                self.control_charge_current = self.max_battery_charge_current
            
            if discharge_currents:
                self.control_discharge_current = sum(discharge_currents)
            else:
                self.control_discharge_current = self.max_battery_discharge_current
            
            # Check for current imbalance
            if len(charge_currents) > 1:
                max_cc = max(charge_currents)
                min_cc = min(charge_currents)
                if max_cc > 0 and (max_cc - min_cc) / max_cc > 0.3:  # 30% difference
                    self.current_imbalance = True
                    logger.warning(f"Charge current imbalance: min={min_cc:.1f}A, max={max_cc:.1f}A")
                    
                    # Optionally reduce total current for better balance
                    if self.current_imbalance and self.voltage_imbalance:
                        # Serious imbalance - reduce more aggressively
                        self.control_charge_current *= 0.7  # 30% reduction for safety
                        logger.info(f"Reducing charge current due to imbalance: {self.control_charge_current:.1f}A")
        
        # Update allow flags
        self.control_allow_charge = self.control_charge_current > 0
        self.control_allow_discharge = self.control_discharge_current > 0




    def get_physical_battery_cell_voltage(self, battery_index: int, cell_index: int) -> Optional[float]:
        """
        Get cell voltage from a specific physical battery.

        Args:
            battery_index: Index of the physical battery (0-based)
            cell_index: Index of the cell in the physical battery (0-based)

        Returns:
            Cell voltage or None if not available
        """
        if not hasattr(self, 'batts') or battery_index >= len(self.batts):
            return None

        battery = self.batts[battery_index]

        # Check if battery is online
        if hasattr(battery, 'online') and not battery.online:
            return None

        # Try to get cell voltage using get_cell_voltage method
        if hasattr(battery, 'get_cell_voltage'):
            return battery.get_cell_voltage(cell_index)

        # Try to get cell voltage directly from cells array
        if (hasattr(battery, 'cells') and battery.cells and
            cell_index < len(battery.cells) and
            hasattr(battery.cells[cell_index], 'voltage')):
            return battery.cells[cell_index].voltage

        return None

    def get_physical_battery_cell_balancing(self, battery_index: int, cell_index: int) -> bool:
        """
        Get cell balancing state from a specific physical battery.

        Args:
            battery_index: Index of the physical battery (0-based)
            cell_index: Index of the cell in the physical battery (0-based)

        Returns:
            True if cell is balancing, False otherwise
        """
        if not hasattr(self, 'batts') or battery_index >= len(self.batts):
            return False

        battery = self.batts[battery_index]

        # Check if battery is online
        if hasattr(battery, 'online') and not battery.online:
            return False

        # Try to get balancing state using get_cell_balancing method
        if hasattr(battery, 'get_cell_balancing'):
            balancing = battery.get_cell_balancing(cell_index)
            return balancing == 1 if isinstance(balancing, int) else bool(balancing)

        # Try to get balancing state directly from cells array
        if (hasattr(battery, 'cells') and battery.cells and
            cell_index < len(battery.cells) and
            hasattr(battery.cells[cell_index], 'balance')):
            return bool(battery.cells[cell_index].balance)

        return False

    def log_settings(self) -> None:
        """Log virtual battery settings and configuration."""
        logger.info(f"--- Virtual Battery ({'Series' if self.series_config else 'Parallel'}) ---")
        active_batts = sum(1 for b in self.batts if hasattr(b, 'online') and b.online)
        logger.info(f"> Component Batteries: {len(self.batts)} ({active_batts} online)")
        
        # Add null checks before formatting
        if self.voltage is not None and self.current is not None and self.soc is not None:
            logger.info(f"> Voltage: {self.voltage:.2f}V, Current: {self.current:.2f}A, SOC: {self.soc:.1f}%")
        
        if self.cell_count is not None and self.capacity is not None:
            logger.info(f"> Cell count: {self.cell_count}, Capacity: {self.capacity:.1f}Ah")
        
        if self.max_battery_charge_current is not None and self.max_battery_discharge_current is not None:
            logger.info(
                f"> Max charge current: {self.max_battery_charge_current:.1f}A, "
                f"Max discharge current: {self.max_battery_discharge_current:.1f}A"
            )
        
        # Call base class log_settings
        try:
            super().log_settings()
        except Exception as e:
            logger.error(f"Error in base log_settings: {e}")