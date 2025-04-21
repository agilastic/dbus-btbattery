#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
D-Bus Interface for Cell Voltage Monitoring System

This module provides D-Bus interfaces for the cell monitoring system,
allowing external applications to access cell voltage data.
"""

import dbus
import sys
import os
import time
import json
from typing import Dict, List, Any, Optional, Tuple, Union

# Import cell monitoring system
from cell_monitor import CellMonitor, get_cell_monitor
from utils import logger

# Import D-Bus related modules
try:
    from vedbus import VeDbusService
except ImportError:
    velib_path = os.path.join(os.path.dirname(__file__), 
                             "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
    if velib_path not in sys.path:
        sys.path.insert(1, velib_path)
    try:
        from vedbus import VeDbusService
    except ImportError:
        # Fallback for development environments
        from vedbus_mock import VeDbusService

def get_bus() -> dbus.Bus:
    """Get the appropriate D-Bus connection based on environment."""
    return (
        dbus.SessionBus()
        if "DBUS_SESSION_BUS_ADDRESS" in os.environ
        else dbus.SystemBus()
    )

class CellMonitorDbusService:
    """
    D-Bus service for the cell monitoring system, providing access to 
    detailed cell data per physical battery.
    """
    
    def __init__(self, cell_monitor: CellMonitor, service_name=None, existing_service=None):
        """
        Initialize the D-Bus service for cell monitoring.
        
        Args:
            cell_monitor: The cell monitor instance
            service_name: Optional custom service name
            existing_service: Optional existing D-Bus service to extend instead of creating new one
        """
        self.cell_monitor = cell_monitor
        
        # Generate service name if not provided
        if service_name is None:
            service_name = "com.victronenergy.battery.cellmonitor"
        
        self.service_name = service_name
        logger.info(f"Creating cell monitor D-Bus service: {self.service_name}")
        
        # Use existing service or create new one
        if existing_service:
            logger.info("Using existing D-Bus service for cell monitoring")
            self._dbusservice = existing_service
        else:
            # Initialize new D-Bus service
            self._dbusservice = VeDbusService(self.service_name, get_bus())
        
        # Set up D-Bus paths
        self._setup_dbus_paths()
    
    def _setup_dbus_paths(self) -> None:
        """Set up all the D-Bus paths for the cell monitor."""
        logger.info("Setting up D-Bus paths for cell monitor")
        
        # Only create management objects if using a new service
        if not hasattr(self._dbusservice, '_dbusobjects') or len(self._dbusservice._dbusobjects) == 0:
            # Create the management objects
            self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
            self._dbusservice.add_path("/Mgmt/ProcessVersion", "1.0")
            self._dbusservice.add_path("/Mgmt/Connection", "Cell Monitor")
            
            # Create service info
            self._dbusservice.add_path("/DeviceInstance", 0)
            self._dbusservice.add_path("/ProductId", 0)
            self._dbusservice.add_path("/ProductName", "Battery Cell Monitor")
            self._dbusservice.add_path("/FirmwareVersion", "1.0")
            self._dbusservice.add_path("/HardwareVersion", "1.0")
            self._dbusservice.add_path("/Connected", 1)
            self._dbusservice.add_path("/CustomName", "Cell Monitor", writeable=True)
        
        # Settings
        self._dbusservice.add_path(
            "/Settings/CellMonitor/SampleInterval", 
            self.cell_monitor.sample_interval, 
            writeable=True,
            onchangecallback=self._handle_sample_interval_change
        )
        self._dbusservice.add_path(
            "/Settings/CellMonitor/AlertThreshold", 
            self.cell_monitor.alert_threshold, 
            writeable=True,
            onchangecallback=self._handle_alert_threshold_change,
            gettextcallback=lambda p, v: "{:.3f}V".format(v)
        )
        
        # Overall statistics
        self._dbusservice.add_path(
            "/CellMonitor/Statistics/MinVoltage", 
            None, 
            writeable=True,
            gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
        )
        self._dbusservice.add_path(
            "/CellMonitor/Statistics/MaxVoltage", 
            None, 
            writeable=True,
            gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
        )
        self._dbusservice.add_path(
            "/CellMonitor/Statistics/AvgVoltage", 
            None, 
            writeable=True,
            gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
        )
        self._dbusservice.add_path(
            "/CellMonitor/Statistics/MaxSpread", 
            None, 
            writeable=True,
            gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
        )
        self._dbusservice.add_path(
            "/CellMonitor/Statistics/LastUpdate", 
            0, 
            writeable=True
        )
        
        # Alerts
        self._dbusservice.add_path(
            "/CellMonitor/Alerts/Count", 
            0, 
            writeable=True
        )
        self._dbusservice.add_path(
            "/CellMonitor/Alerts/Latest", 
            "", 
            writeable=True
        )
        
        # Battery count
        self._dbusservice.add_path(
            "/Parallel/BatteryCount", 
            0, 
            writeable=True
        )
        
        # JSON representation of complete data
        self._dbusservice.add_path(
            "/CellMonitor/Data", 
            "{}", 
            writeable=True
        )
        
        # Initialize battery-specific paths
        self._setup_battery_specific_paths()
    
    def _setup_battery_specific_paths(self) -> None:
        """Set up D-Bus paths for individual battery data."""
        # Get initial data
        cell_data = self.cell_monitor.get_cell_data()
        
        # Create paths for each battery
        for battery_id in cell_data.get("batteries", {}):
            battery_path_base = f"/Parallel/Battery/{battery_id.replace(':', '_')}"
            batt_key = battery_id.replace(':', '_')
            batt_id_short = battery_id[-5:].replace(':', '')  # Last 5 chars without colons
            
            # Battery summary data
            self._dbusservice.add_path(
                f"{battery_path_base}/CellCount", 
                0, 
                writeable=True
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/Name",
                f"Battery {batt_id_short}",
                writeable=True
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/MinVoltage", 
                None, 
                writeable=True,
                gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/MaxVoltage", 
                None, 
                writeable=True,
                gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/AvgVoltage", 
                None, 
                writeable=True,
                gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/VoltageSpread", 
                None, 
                writeable=True,
                gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
            )
            self._dbusservice.add_path(
                f"{battery_path_base}/LastUpdate", 
                0, 
                writeable=True
            )
            
            # Individual cell voltage paths in CCGX-friendly format
            battery_data = cell_data["batteries"].get(battery_id, {})
            cell_count = battery_data.get("cell_count", 0)
            
            for i in range(cell_count):
                # Add path for each cell using the battery ID in the path
                self._dbusservice.add_path(
                    f"{battery_path_base}/Cell/{i+1}/Volts",
                    None,
                    writeable=True,
                    gettextcallback=lambda p, v: "{:.3f}V".format(v) if v is not None else "---"
                )
                
                # Add balancing state path for each cell
                self._dbusservice.add_path(
                    f"{battery_path_base}/Cell/{i+1}/Balancing",
                    0,
                    writeable=True,
                    gettextcallback=lambda p, v: "Yes" if v else "No"
                )
            
            # JSON for cell voltages (for compatibility)
            self._dbusservice.add_path(
                f"{battery_path_base}/CellVoltages", 
                "[]", 
                writeable=True
            )
            
            # JSON for balancing state (for compatibility)
            self._dbusservice.add_path(
                f"{battery_path_base}/Balancing", 
                "[]", 
                writeable=True
            )
    
    def _handle_sample_interval_change(self, path: str, value: Any) -> Any:
        """Handle changes to the sample interval setting."""
        try:
            interval = int(value)
            if interval < 10:
                interval = 10  # Minimum 10 seconds
            
            self.cell_monitor.set_sample_interval(interval)
            logger.info(f"Sample interval changed to {interval} seconds")
            return interval
        except Exception as e:
            logger.error(f"Error changing sample interval: {e}")
            return self.cell_monitor.sample_interval
    
    def _handle_alert_threshold_change(self, path: str, value: Any) -> Any:
        """Handle changes to the alert threshold setting."""
        try:
            threshold = float(value)
            if threshold < 0.01:
                threshold = 0.01  # Minimum 10mV
            
            self.cell_monitor.set_alert_threshold(threshold)
            logger.info(f"Alert threshold changed to {threshold:.3f}V")
            return threshold
        except Exception as e:
            logger.error(f"Error changing alert threshold: {e}")
            return self.cell_monitor.alert_threshold
    
    def update(self) -> bool:
        """
        Update all D-Bus values from the current state of the cell monitor.
        
        Returns:
            True if the update was successful, False otherwise
        """
        try:
            # Get current cell data
            cell_data = self.cell_monitor.get_cell_data()
            
            # Update overall statistics
            stats = cell_data["overall_stats"]
            self._dbusservice["/CellMonitor/Statistics/MinVoltage"] = stats["min_voltage"]
            self._dbusservice["/CellMonitor/Statistics/MaxVoltage"] = stats["max_voltage"]
            self._dbusservice["/CellMonitor/Statistics/AvgVoltage"] = stats["avg_voltage"]
            self._dbusservice["/CellMonitor/Statistics/MaxSpread"] = stats["max_spread"]
            self._dbusservice["/CellMonitor/Statistics/LastUpdate"] = cell_data["timestamp"]
            
            # Update battery count
            self._dbusservice["/Parallel/BatteryCount"] = len(cell_data["batteries"])
            
            # Update alerts
            alerts = cell_data["recent_alerts"]
            self._dbusservice["/CellMonitor/Alerts/Count"] = len(alerts)
            if alerts:
                latest_alert = alerts[0]
                alert_str = (
                    f"Battery {latest_alert['battery_id']}: "
                    f"Imbalance {latest_alert['spread']:.3f}V "
                    f"(min={latest_alert['min']:.3f}V, max={latest_alert['max']:.3f}V)"
                )
                self._dbusservice["/CellMonitor/Alerts/Latest"] = alert_str
            
            # Update complete data as JSON
            self._dbusservice["/CellMonitor/Data"] = json.dumps(cell_data)
            
            # Update battery-specific data
            for battery_id, battery_data in cell_data["batteries"].items():
                # Create path base with battery ID cleaned for D-Bus
                battery_path_base = f"/Parallel/Battery/{battery_id.replace(':', '_')}"
                
                # Ensure paths exist for this battery
                if f"{battery_path_base}/CellCount" not in self._dbusservice._dbusobjects:
                    # This is a new battery, add paths for it
                    self._setup_battery_specific_paths()
                    continue  # Skip this iteration as paths were just created
                
                # Update battery data
                self._dbusservice[f"{battery_path_base}/CellCount"] = battery_data["cell_count"]
                self._dbusservice[f"{battery_path_base}/MinVoltage"] = battery_data["min_voltage"]
                self._dbusservice[f"{battery_path_base}/MaxVoltage"] = battery_data["max_voltage"]
                self._dbusservice[f"{battery_path_base}/AvgVoltage"] = battery_data["avg_voltage"]
                self._dbusservice[f"{battery_path_base}/VoltageSpread"] = battery_data["voltage_spread"]
                self._dbusservice[f"{battery_path_base}/LastUpdate"] = battery_data["last_update"]
                
                # Update individual cell voltages and balancing
                for i in range(battery_data["cell_count"]):
                    # Get cell voltage and balancing state
                    cell_voltage = None
                    if i < len(battery_data["cell_voltages"]):
                        cell_voltage = battery_data["cell_voltages"][i]
                    
                    balancing = False
                    if i < len(battery_data["balancing"]):
                        balancing = battery_data["balancing"][i]
                    
                    # Update D-Bus paths
                    cell_voltage_path = f"{battery_path_base}/Cell/{i+1}/Volts"
                    if cell_voltage_path in self._dbusservice._dbusobjects:
                        self._dbusservice[cell_voltage_path] = cell_voltage
                    
                    cell_balance_path = f"{battery_path_base}/Cell/{i+1}/Balancing"
                    if cell_balance_path in self._dbusservice._dbusobjects:
                        self._dbusservice[cell_balance_path] = 1 if balancing else 0
                
                # Update JSON data (for compatibility)
                self._dbusservice[f"{battery_path_base}/CellVoltages"] = json.dumps(battery_data["cell_voltages"])
                self._dbusservice[f"{battery_path_base}/Balancing"] = json.dumps(battery_data["balancing"])
            
            return True
        
        except Exception as e:
            logger.error(f"Error updating cell monitor D-Bus service: {e}")
            return False


# Global instance
_cell_monitor_dbus_service = None

def get_dbus_service() -> Optional[CellMonitorDbusService]:
    """Get the global cell monitor D-Bus service instance"""
    return _cell_monitor_dbus_service

def init_dbus_service(existing_service=None) -> Optional[CellMonitorDbusService]:
    """
    Initialize the cell monitor D-Bus service
    
    Args:
        existing_service: Optional existing D-Bus service to extend
    """
    global _cell_monitor_dbus_service
    
    # Get cell monitor instance
    cell_monitor = get_cell_monitor()
    if not cell_monitor:
        logger.error("Cannot initialize D-Bus service: Cell monitor not available")
        return None
    
    # Create service if it doesn't exist
    if _cell_monitor_dbus_service is None:
        _cell_monitor_dbus_service = CellMonitorDbusService(
            cell_monitor, 
            existing_service=existing_service
        )
    
    return _cell_monitor_dbus_service

def update_dbus_service() -> bool:
    """Update the cell monitor D-Bus service with current data"""
    if _cell_monitor_dbus_service:
        return _cell_monitor_dbus_service.update()
    return False