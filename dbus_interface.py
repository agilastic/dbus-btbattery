#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import dbus
import sys
import os
import time
from typing import Dict, Any, Optional, List, Union, Tuple

# Utility function to add to system path if needed
def ensure_path(path: str) -> None:
    """Add a path to sys.path if it's not already there."""
    if path not in sys.path:
        sys.path.insert(1, path)

# Try to import Victron packages (handle both direct and Venus OS environments)
try:
    from vedbus import VeDbusService
except ImportError:
    velib_path = os.path.join(os.path.dirname(__file__), 
                             "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
    ensure_path(velib_path)
    try:
        from vedbus import VeDbusService
    except ImportError:
        # Fallback for development environments
        from vedbus_mock import VeDbusService

# Import utils module to access configuration and logging
import utils
# Import specific utility functions
from utils import logger, TIME_TO_SOC_POINTS, SOC_LOW_WARNING, BATTERY_CELL_DATA_FORMAT

def get_bus() -> dbus.Bus:
    """Get the appropriate D-Bus connection based on environment."""
    return (
        dbus.SessionBus()
        if "DBUS_SESSION_BUS_ADDRESS" in os.environ
        else dbus.SystemBus()
    )

class VirtualBatteryDbusService:
    """
    D-Bus service for the virtual battery, handling both series and parallel configurations.
    This class publishes battery data to the Venus OS D-Bus system.
    """
    
    def __init__(self, battery, service_name=None, device_instance=1):
        """
        Initialize the D-Bus service for the virtual battery.
        
        Args:
            battery: The virtual battery object
            service_name: Optional service name override
            device_instance: D-Bus device instance number
        """
        self.battery = battery
        self.device_instance = device_instance
        
        # Derive service name from configuration if not provided
        if service_name is None:
            config_type = "series" if hasattr(battery, 'series_config') and battery.series_config else "parallel"
            service_name = f"com.victronenergy.battery.virtual_{config_type}_{device_instance}"
        
        self.service_name = service_name
        logger.info(f"Creating virtual battery D-Bus service: {self.service_name}")
        
        # Initialize D-Bus service
        self._dbusservice = VeDbusService(self.service_name, get_bus())
        
        # Set up D-Bus paths
        self._setup_dbus_paths()
    
    def _setup_dbus_paths(self) -> None:
        """Set up all the D-Bus paths for the virtual battery."""
        logger.info("Setting up D-Bus paths for virtual battery")
        
        # Create the management objects
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion", "1.0")
        self._dbusservice.add_path("/Mgmt/Connection", "Virtual Battery")
        
        # Get configuration type once for use in multiple paths
        config_type = "Series" if hasattr(self.battery, 'series_config') and self.battery.series_config else "Parallel"
        
        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", self.device_instance)
        self._dbusservice.add_path("/ProductId", 0)
        self._dbusservice.add_path(
            "/ProductName", f"Virtual Battery ({config_type})"
        )
        self._dbusservice.add_path("/FirmwareVersion", "1.0")
        self._dbusservice.add_path("/HardwareVersion", "1.0")
        self._dbusservice.add_path("/Connected", 1)
        self._dbusservice.add_path(
            "/CustomName", f"Virtual {config_type} Battery", writeable=True
        )
        
        # Create battery static info
        self._dbusservice.add_path(
            "/Info/BatteryLowVoltage", 
            self.battery.min_battery_voltage, 
            writeable=True
        )
        self._dbusservice.add_path(
            "/Info/MaxChargeVoltage",
            self.battery.max_battery_voltage,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}V".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/Info/MaxChargeCurrent",
            self.battery.max_battery_charge_current,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}A".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/Info/MaxDischargeCurrent",
            self.battery.max_battery_discharge_current,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}A".format(v) if v is not None else "---",
        )
        
        # System information
        self._dbusservice.add_path(
            "/System/NrOfCellsPerBattery", 
            self.battery.cell_count, 
            writeable=True
        )
        self._dbusservice.add_path("/System/NrOfModulesOnline", 1, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesOffline", 0, writeable=True)
        self._dbusservice.add_path(
            "/System/NrOfModulesBlockingCharge", None, writeable=True
        )
        self._dbusservice.add_path(
            "/System/NrOfModulesBlockingDischarge", None, writeable=True
        )
        
        # Capacity
        self._dbusservice.add_path(
            "/Capacity",
            self.battery.get_capacity_remain() if hasattr(self.battery, 'get_capacity_remain') else None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}Ah".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/InstalledCapacity",
            self.battery.capacity,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}Ah".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/ConsumedAmphours",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}Ah".format(v) if v is not None else "---",
        )
        
        # Create SOC, DC and System items
        self._dbusservice.add_path("/Soc", None, writeable=True)
        self._dbusservice.add_path(
            "/Dc/0/Voltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:2.2f}V".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/Dc/0/Current",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:2.2f}A".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/Dc/0/Power",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}W".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path("/Dc/0/Temperature", None, writeable=True)
        
        # Midpoint voltage (if supported)
        self._dbusservice.add_path(
            "/Dc/0/MidVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}V".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path(
            "/Dc/0/MidVoltageDeviation",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.1f}%".format(v) if v is not None else "---",
        )
        
        # Cell data
        self._dbusservice.add_path("/System/MinCellTemperature", None, writeable=True)
        self._dbusservice.add_path("/System/MaxCellTemperature", None, writeable=True)
        self._dbusservice.add_path(
            "/System/MaxCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path("/System/MaxVoltageCellId", None, writeable=True)
        self._dbusservice.add_path(
            "/System/MinCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
        )
        self._dbusservice.add_path("/System/MinVoltageCellId", None, writeable=True)
        
        # History
        self._dbusservice.add_path("/History/ChargeCycles", None, writeable=True)
        self._dbusservice.add_path("/History/TotalAhDrawn", None, writeable=True)
        
        # Balance and FET status
        self._dbusservice.add_path("/Balancing", None, writeable=True)
        self._dbusservice.add_path("/Io/AllowToCharge", 0, writeable=True)
        self._dbusservice.add_path("/Io/AllowToDischarge", 0, writeable=True)
        
        # Alarms
        self._dbusservice.add_path("/Alarms/LowVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowSoc", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighChargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighDischargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/CellImbalance", None, writeable=True)
        self._dbusservice.add_path("/Alarms/InternalFailure", None, writeable=True)
        self._dbusservice.add_path(
            "/Alarms/HighChargeTemperature", None, writeable=True
        )
        self._dbusservice.add_path("/Alarms/LowChargeTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowTemperature", None, writeable=True)
        
        # Cell voltages (if enabled in settings)
        if hasattr(self.battery, 'cell_count') and self.battery.cell_count > 0 and hasattr(self.battery, 'cells'):
            self._setup_cell_dbus_paths()
        
        # Time to SOC paths
        for num in self._get_soc_points():
            self._dbusservice.add_path(f"/TimeToSoC/{num}", None, writeable=True)
        self._dbusservice.add_path("/TimeToGo", None, writeable=True)
        
        # Add parallel-specific paths
        if hasattr(self.battery, 'series_config') and not self.battery.series_config:
            self._setup_parallel_specific_paths()
    
    def _setup_cell_dbus_paths(self) -> None:
        """Set up dbus paths for individual cell data."""
        # Use BATTERY_CELL_DATA_FORMAT to determine format
        # 0: Do not publish all the cells
        # 1: Format: /Voltages/Cell#
        # 2: Format: /Cell/#/Volts
        # 3: Both formats 1 and 2
        
        if BATTERY_CELL_DATA_FORMAT > 0 and hasattr(self.battery, 'cell_count') and self.battery.cell_count > 0:
            logger.info(f"Setting up cell paths for {self.battery.cell_count} cells with format {BATTERY_CELL_DATA_FORMAT}")
            
            # Support both cell data formats
            formats = []
            if BATTERY_CELL_DATA_FORMAT & 1:
                formats.append("/Voltages/Cell%s")
            if BATTERY_CELL_DATA_FORMAT & 2:
                formats.append("/Cell/%s/Volts")
            
            # Create paths for each cell
            for i in range(1, self.battery.cell_count + 1):
                for cell_path_format in formats:
                    cell_path = cell_path_format % (str(i))
                    try:
                        self._dbusservice.add_path(
                            cell_path,
                            None,
                            writeable=True,
                            gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
                        )
                    except Exception as e:
                        logger.warning(f"Could not create cell path {cell_path}: {e}")
                
                # Add balance paths if format 1 is enabled
                if BATTERY_CELL_DATA_FORMAT & 1:
                    try:
                        balance_path = f"/Balances/Cell{i}"
                        self._dbusservice.add_path(balance_path, None, writeable=True)
                    except Exception as e:
                        logger.warning(f"Could not create balance path {balance_path}: {e}")
            
            # Add summary paths for each format
            for fmt in formats:
                # Determine path base (either "Cell" or "Voltages")
                path_base = "Cell" if fmt.startswith("/Cell") else "Voltages"
                
                try:
                    self._dbusservice.add_path(
                        f"/{path_base}/Sum",
                        None,
                        writeable=True,
                        gettextcallback=lambda p, v: "{:2.2f}V".format(v) if v is not None else "---",
                    )
                    self._dbusservice.add_path(
                        f"/{path_base}/Diff",
                        None,
                        writeable=True,
                        gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
                    )
                except Exception as e:
                    logger.warning(f"Could not create summary path for {path_base}: {e}")
    
    def _setup_parallel_specific_paths(self) -> None:
        """Set up additional dbus paths specific to parallel battery configuration."""
        # Imbalance indicators
        self._dbusservice.add_path(
            "/Parallel/VoltageImbalance", 
            0, 
            writeable=True,
            gettextcallback=lambda p, v: "Yes" if v else "No",
        )
        self._dbusservice.add_path(
            "/Parallel/CurrentImbalance", 
            0, 
            writeable=True,
            gettextcallback=lambda p, v: "Yes" if v else "No",
        )
        self._dbusservice.add_path(
            "/Parallel/SocImbalance", 
            0, 
            writeable=True,
            gettextcallback=lambda p, v: "Yes" if v else "No",
        )
        
        # Component battery info
        if hasattr(self.battery, 'batts'):
            self._dbusservice.add_path(
                "/Parallel/TotalBatteries", 
                len(self.battery.batts), 
                writeable=True
            )
            self._dbusservice.add_path(
                "/Parallel/ActiveBatteries", 
                0, 
                writeable=True
            )
    
    def _get_soc_points(self) -> List[int]:
        """
        Get the SOC points for TimeToSoc paths.
        
        Returns:
            List of SOC percentage points
        """
        # Use TIME_TO_SOC_POINTS from utils if available, or default to [100, 0]
        if TIME_TO_SOC_POINTS:
            return TIME_TO_SOC_POINTS
        return [100, 0]  # Default minimum
    
    def update(self) -> bool:
        """
        Update all dbus values from the current state of the battery.
        This should be called after the battery has been refreshed.
        
        Returns:
            True if the update was successful, False otherwise
        """
        try:
            # Only update if the battery is online
            if not hasattr(self.battery, 'online') or not self.battery.online:
                self._dbusservice["/Connected"] = 0
                return False
            
            # Basic status
            self._dbusservice["/Connected"] = 1
            
            # Handle potential None values safely
            if hasattr(self.battery, 'soc') and self.battery.soc is not None:
                self._dbusservice["/Soc"] = round(self.battery.soc, 2)
                
            if hasattr(self.battery, 'voltage') and self.battery.voltage is not None:
                self._dbusservice["/Dc/0/Voltage"] = round(self.battery.voltage, 2)
                
            if hasattr(self.battery, 'current') and self.battery.current is not None:
                self._dbusservice["/Dc/0/Current"] = round(self.battery.current, 2)
            
            # Power calculation
            if (hasattr(self.battery, 'voltage') and self.battery.voltage is not None and 
                hasattr(self.battery, 'current') and self.battery.current is not None):
                self._dbusservice["/Dc/0/Power"] = round(self.battery.voltage * self.battery.current, 2)
            else:
                self._dbusservice["/Dc/0/Power"] = None
            
            # Safe method calls with hasattr checks
            # Temperature
            if hasattr(self.battery, 'get_temp'):
                self._dbusservice["/Dc/0/Temperature"] = self.battery.get_temp()
            if hasattr(self.battery, 'get_min_temp'):
                self._dbusservice["/System/MinCellTemperature"] = self.battery.get_min_temp()
            if hasattr(self.battery, 'get_max_temp'):
                self._dbusservice["/System/MaxCellTemperature"] = self.battery.get_max_temp()
            
            # Capacity
            if hasattr(self.battery, 'get_capacity_remain'):
                self._dbusservice["/Capacity"] = self.battery.get_capacity_remain()
            if hasattr(self.battery, 'capacity'):
                self._dbusservice["/InstalledCapacity"] = self.battery.capacity
            
            # Consumed amphours
            if (hasattr(self.battery, 'capacity') and self.battery.capacity is not None and 
                hasattr(self.battery, 'get_capacity_remain') and 
                self.battery.get_capacity_remain() is not None):
                self._dbusservice["/ConsumedAmphours"] = self.battery.capacity - self.battery.get_capacity_remain()
            else:
                self._dbusservice["/ConsumedAmphours"] = None
            
            # Midpoint voltage (if enabled)
            if hasattr(self.battery, 'get_midvoltage'):
                try:
                    midpoint, deviation = self.battery.get_midvoltage()
                    if midpoint is not None:
                        self._dbusservice["/Dc/0/MidVoltage"] = midpoint
                        if deviation is not None:
                            self._dbusservice["/Dc/0/MidVoltageDeviation"] = deviation
                except Exception as e:
                    logger.warning(f"Error calculating midpoint voltage: {e}")
            
            # Cell data
            if hasattr(self.battery, 'cell_count'):
                self._dbusservice["/System/NrOfCellsPerBattery"] = self.battery.cell_count
            
            if hasattr(self.battery, 'get_min_cell_desc'):
                self._dbusservice["/System/MinVoltageCellId"] = self.battery.get_min_cell_desc()
            if hasattr(self.battery, 'get_max_cell_desc'):
                self._dbusservice["/System/MaxVoltageCellId"] = self.battery.get_max_cell_desc()
            if hasattr(self.battery, 'get_min_cell_voltage'):
                self._dbusservice["/System/MinCellVoltage"] = self.battery.get_min_cell_voltage()
            if hasattr(self.battery, 'get_max_cell_voltage'):
                self._dbusservice["/System/MaxCellVoltage"] = self.battery.get_max_cell_voltage()
            
            # Cycles and history
            if hasattr(self.battery, 'cycles'):
                self._dbusservice["/History/ChargeCycles"] = self.battery.cycles
            if hasattr(self.battery, 'total_ah_drawn'):
                self._dbusservice["/History/TotalAhDrawn"] = self.battery.total_ah_drawn
            
            # FET status
            if hasattr(self.battery, 'get_balancing'):
                self._dbusservice["/Balancing"] = self.battery.get_balancing()
            if hasattr(self.battery, 'charge_fet'):
                self._dbusservice["/Io/AllowToCharge"] = 1 if self.battery.charge_fet else 0
            if hasattr(self.battery, 'discharge_fet'):
                self._dbusservice["/Io/AllowToDischarge"] = 1 if self.battery.discharge_fet else 0
            
            # Module status
            if hasattr(self.battery, 'charge_fet'):
                self._dbusservice["/System/NrOfModulesBlockingCharge"] = 0 if self.battery.charge_fet else 1
            if hasattr(self.battery, 'discharge_fet'):
                self._dbusservice["/System/NrOfModulesBlockingDischarge"] = 0 if self.battery.discharge_fet else 1
            
            # Online status
            if hasattr(self.battery, 'batts'):
                active_batteries = sum(1 for b in self.battery.batts 
                                      if hasattr(b, 'online') and b.online)
                self._dbusservice["/System/NrOfModulesOnline"] = active_batteries
                self._dbusservice["/System/NrOfModulesOffline"] = len(self.battery.batts) - active_batteries
            
            # Charge control
            if hasattr(self.battery, 'control_charge_current') and self.battery.control_charge_current is not None:
                self._dbusservice["/Info/MaxChargeCurrent"] = self.battery.control_charge_current
            
            if hasattr(self.battery, 'control_discharge_current') and self.battery.control_discharge_current is not None:
                self._dbusservice["/Info/MaxDischargeCurrent"] = self.battery.control_discharge_current
            
            # Voltage control
            if hasattr(self.battery, 'control_voltage') and self.battery.control_voltage is not None:
                self._dbusservice["/Info/MaxChargeVoltage"] = self.battery.control_voltage
            
            # Update protection alarms
            self._update_alarms()
            
            # Update individual cell data
            if (BATTERY_CELL_DATA_FORMAT > 0 and 
                hasattr(self.battery, 'cell_count') and self.battery.cell_count > 0 and 
                hasattr(self.battery, 'cells') and self.battery.cells):
                self._update_cell_data()
            
            # Update TimeToSoc data
            self._update_time_to_soc()
            
            # Update parallel-specific paths
            if hasattr(self.battery, 'series_config') and not self.battery.series_config:
                self._update_parallel_specific_data()
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating dbus service: {e}")
            return False
    
    def _update_alarms(self) -> None:
        """Update all alarm states from the battery protection object."""
        if not hasattr(self.battery, 'protection'):
            return
        
        # Update the alarm states - handle potentially None values
        try:
            protection = self.battery.protection
            
            if hasattr(protection, 'voltage_low'):
                self._dbusservice["/Alarms/LowVoltage"] = protection.voltage_low
            if hasattr(protection, 'voltage_cell_low'):
                self._dbusservice["/Alarms/LowCellVoltage"] = protection.voltage_cell_low
            if hasattr(protection, 'voltage_high'):
                self._dbusservice["/Alarms/HighVoltage"] = protection.voltage_high
            if hasattr(protection, 'soc_low'):
                self._dbusservice["/Alarms/LowSoc"] = protection.soc_low
            if hasattr(protection, 'current_over'):
                self._dbusservice["/Alarms/HighChargeCurrent"] = protection.current_over
            if hasattr(protection, 'current_under'):
                self._dbusservice["/Alarms/HighDischargeCurrent"] = protection.current_under
            if hasattr(protection, 'cell_imbalance'):
                self._dbusservice["/Alarms/CellImbalance"] = protection.cell_imbalance
            if hasattr(protection, 'internal_failure'):
                self._dbusservice["/Alarms/InternalFailure"] = protection.internal_failure
            if hasattr(protection, 'temp_high_charge'):
                self._dbusservice["/Alarms/HighChargeTemperature"] = protection.temp_high_charge
            if hasattr(protection, 'temp_low_charge'):
                self._dbusservice["/Alarms/LowChargeTemperature"] = protection.temp_low_charge
            if hasattr(protection, 'temp_high_discharge'):
                self._dbusservice["/Alarms/HighTemperature"] = protection.temp_high_discharge
            if hasattr(protection, 'temp_low_discharge'):
                self._dbusservice["/Alarms/LowTemperature"] = protection.temp_low_discharge
                
        except Exception as e:
            logger.error(f"Error updating alarm status: {e}")
    
    def _update_cell_data(self) -> None:
        """Update individual cell voltage and balancing data."""
        if (not hasattr(self.battery, 'cells') or not self.battery.cells or 
            BATTERY_CELL_DATA_FORMAT == 0):
            return
        
        try:
            # Determine cell path format and base path once, outside the loop
            cell_path_format = "/Cell/%s/Volts" if (BATTERY_CELL_DATA_FORMAT & 2) else "/Voltages/Cell%s"
            path_base = "Cell" if (BATTERY_CELL_DATA_FORMAT & 2) else "Voltages"
            
            voltage_sum = 0
            cell_count = min(len(self.battery.cells), self.battery.cell_count)
            
            # First check if paths exist, if not create them
            for i in range(cell_count):
                cell_path = cell_path_format % (str(i + 1))
                if cell_path not in self._dbusservice._dbusobjects:
                    # Add path that was missing
                    self._dbusservice.add_path(
                        cell_path,
                        None,
                        writeable=True,
                        gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
                    )
                    logger.info(f"Created missing cell voltage path: {cell_path}")
                
                if BATTERY_CELL_DATA_FORMAT & 1 and hasattr(self.battery, 'get_cell_balancing'):
                    balance_path = f"/Balances/Cell{i + 1}"
                    if balance_path not in self._dbusservice._dbusobjects:
                        # Add path that was missing
                        self._dbusservice.add_path(balance_path, None, writeable=True)
                        logger.info(f"Created missing cell balance path: {balance_path}")
            
            # Now update the values
            for i in range(cell_count):
                if not hasattr(self.battery, 'get_cell_voltage'):
                    continue
                    
                cell_voltage = self.battery.get_cell_voltage(i)
                cell_path = cell_path_format % (str(i + 1))
                try:
                    self._dbusservice[cell_path] = cell_voltage
                except Exception as cell_error:
                    logger.error(f"Error updating cell data: '{cell_path}' - {cell_error}")
                
                if BATTERY_CELL_DATA_FORMAT & 1 and hasattr(self.battery, 'get_cell_balancing'):
                    try:
                        self._dbusservice[f"/Balances/Cell{i + 1}"] = self.battery.get_cell_balancing(i)
                    except Exception as bal_error:
                        logger.error(f"Error updating balance data: '/Balances/Cell{i + 1}' - {bal_error}")
                
                if cell_voltage:
                    voltage_sum += cell_voltage
            
            # Make sure summary paths exist
            if f"/{path_base}/Sum" not in self._dbusservice._dbusobjects:
                self._dbusservice.add_path(
                    f"/{path_base}/Sum",
                    None,
                    writeable=True,
                    gettextcallback=lambda p, v: "{:2.2f}V".format(v) if v is not None else "---",
                )
                logger.info(f"Created missing voltage sum path: /{path_base}/Sum")
                
            if f"/{path_base}/Diff" not in self._dbusservice._dbusobjects:
                self._dbusservice.add_path(
                    f"/{path_base}/Diff",
                    None,
                    writeable=True,
                    gettextcallback=lambda p, v: "{:0.3f}V".format(v) if v is not None else "---",
                )
                logger.info(f"Created missing voltage diff path: /{path_base}/Diff")
            
            # Update summary data
            try:
                self._dbusservice[f"/{path_base}/Sum"] = voltage_sum
            except Exception as sum_error:
                logger.error(f"Error updating voltage sum: '/{path_base}/Sum' - {sum_error}")
            
            # Calculate voltage difference
            if hasattr(self.battery, 'get_min_cell_voltage') and hasattr(self.battery, 'get_max_cell_voltage'):
                min_cell_voltage = self.battery.get_min_cell_voltage()
                max_cell_voltage = self.battery.get_max_cell_voltage()
                
                if min_cell_voltage is not None and max_cell_voltage is not None:
                    try:
                        self._dbusservice[f"/{path_base}/Diff"] = max_cell_voltage - min_cell_voltage
                    except Exception as diff_error:
                        logger.error(f"Error updating voltage diff: '/{path_base}/Diff' - {diff_error}")
            
        except Exception as e:
            logger.error(f"Error updating cell data: {e}")
    
    def _update_time_to_soc(self) -> None:
        """Update TimeToSoc values based on current state."""
        try:
            # Only calculate if we have the necessary data
            if (
                hasattr(self.battery, 'capacity') and self.battery.capacity is not None and
                hasattr(self.battery, 'soc') and self.battery.soc is not None and
                hasattr(self.battery, 'current') and self.battery.current is not None and
                hasattr(self.battery, 'get_timetosoc') and
                TIME_TO_SOC_POINTS
            ):
                # Skip if zero capacity to avoid division by zero
                if self.battery.capacity <= 0:
                    return
                    
                # Calculate percentage change per second
                current_pct_per_sec = (
                    abs(self.battery.current / (self.battery.capacity / 100)) / 3600
                )
                
                # Skip if zero current or very low rate of change
                if current_pct_per_sec < 0.00001:
                    return
                
                # Calculate time to reach each SOC point
                for num in TIME_TO_SOC_POINTS:
                    time_to_soc = self.battery.get_timetosoc(num, current_pct_per_sec)
                    self._dbusservice[f"/TimeToSoC/{num}"] = time_to_soc
                
                # Update TimeToGo (time to reach warning level)
                self._dbusservice["/TimeToGo"] = self.battery.get_timetosoc(
                    SOC_LOW_WARNING, current_pct_per_sec
                )
                
        except Exception as e:
            logger.error(f"Error updating TimeToSoc data: {e}")
    
    def _update_parallel_specific_data(self) -> None:
        """Update parallel battery specific status information."""
        if not hasattr(self.battery, 'series_config') or self.battery.series_config:
            return
        
        try:
            # Update imbalance flags
            if hasattr(self.battery, 'voltage_imbalance'):
                self._dbusservice["/Parallel/VoltageImbalance"] = 1 if self.battery.voltage_imbalance else 0
            
            if hasattr(self.battery, 'current_imbalance'):
                self._dbusservice["/Parallel/CurrentImbalance"] = 1 if self.battery.current_imbalance else 0
            
            if hasattr(self.battery, 'soc_imbalance'):
                self._dbusservice["/Parallel/SocImbalance"] = 1 if self.battery.soc_imbalance else 0
            
            # Update battery status if batts attribute exists
            if hasattr(self.battery, 'batts'):
                active_batteries = sum(1 for b in self.battery.batts 
                                      if hasattr(b, 'online') and b.online)
                self._dbusservice["/Parallel/ActiveBatteries"] = active_batteries
            
        except Exception as e:
            logger.error(f"Error updating parallel battery data: {e}")


class VirtualBatteryDbusManager:
    """
    Manager class for handling multiple virtual battery D-Bus services.
    This is useful when running in both series and parallel mode simultaneously.
    """
    
    def __init__(self):
        """Initialize the manager."""
        self.services = {}
    
    def add_battery(self, battery, service_name=None, device_instance=None):
        """
        Add a battery service.
        
        Args:
            battery: The battery object
            service_name: Optional custom service name
            device_instance: Optional device instance number
        
        Returns:
            The created service object
        """
        # Create a unique identifier for this battery
        battery_id = id(battery)
        
        # Create the service
        service = VirtualBatteryDbusService(
            battery, 
            service_name=service_name,
            device_instance=device_instance
        )
        
        # Store the service
        self.services[battery_id] = service
        
        return service
    
    def remove_battery(self, battery):
        """
        Remove a battery service.
        
        Args:
            battery: The battery object to remove
        
        Returns:
            True if removed, False if not found
        """
        battery_id = id(battery)
        if battery_id in self.services:
            # Clean up the service if needed
            del self.services[battery_id]
            return True
        
        return False
    
    def update_all(self):
        """
        Update all battery services.
        
        Returns:
            Number of successfully updated services
        """
        success_count = 0
        for service in self.services.values():
            if service.update():
                success_count += 1
        
        return success_count