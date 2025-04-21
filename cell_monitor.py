#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cell Voltage Monitoring System for Virtual Batteries

This module provides cell voltage monitoring capabilities for individual 
physical batteries in a virtual battery environment. It tracks and displays
voltage values and history for each cell across all physical batteries.
"""

import time
import threading
import logging
import copy
import os
import json
from typing import Dict, List, Optional, Tuple, Any, Union, Deque
from collections import deque, defaultdict
import statistics
from datetime import datetime

# Import battery-related classes
from battery import Battery, Cell
from virtual import Virtual
import utils
from utils import logger

# Constants for cell monitoring
MAX_HISTORY_POINTS = 1000  # Maximum number of history points to store per cell
DEFAULT_SAMPLE_INTERVAL = 60  # Default sampling interval in seconds
DEFAULT_ALERT_THRESHOLD = 0.2  # Default alert threshold for cell imbalance (V)
HISTORY_FILE_PATH = "/data/cellhistory.json"  # Path to save history data (Venus OS location)

class CellVoltageRecord:
    """
    Represents a single cell voltage measurement record with timestamp
    """
    def __init__(self, voltage: float, timestamp: Optional[float] = None):
        self.voltage = voltage
        self.timestamp = timestamp if timestamp is not None else time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary for serialization"""
        return {
            "voltage": self.voltage,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CellVoltageRecord':
        """Create record from dictionary"""
        return cls(
            voltage=data["voltage"],
            timestamp=data["timestamp"]
        )


class PhysicalBatteryCellData:
    """
    Stores and manages cell data for a single physical battery
    """
    def __init__(self, battery_id: str, cell_count: int):
        self.battery_id = battery_id
        self.cell_count = cell_count
        self.cell_voltages: List[float] = [None] * cell_count
        self.cell_history: List[Deque[CellVoltageRecord]] = [
            deque(maxlen=MAX_HISTORY_POINTS) for _ in range(cell_count)
        ]
        self.min_voltage = None
        self.max_voltage = None
        self.avg_voltage = None
        self.voltage_spread = None
        self.last_update = None
        self.balancing = [False] * cell_count
    
    def update_cell_data(self, battery: Battery) -> bool:
        """
        Update cell data from a battery object
        Returns True if data was updated successfully
        """
        if not battery or not hasattr(battery, 'cells') or not battery.cells:
            return False
        
        updated = False
        current_time = time.time()
        min_v = float('inf')
        max_v = float('-inf')
        total_v = 0
        valid_count = 0
        
        # Update cell voltages and history
        for i in range(min(self.cell_count, len(battery.cells))):
            cell = battery.cells[i]
            if cell.voltage is not None:
                # Update current voltage
                self.cell_voltages[i] = cell.voltage
                
                # Update min/max tracking
                min_v = min(min_v, cell.voltage)
                max_v = max(max_v, cell.voltage)
                total_v += cell.voltage
                valid_count += 1
                
                # Update balancing state
                self.balancing[i] = cell.balance if cell.balance is not None else False
                
                # Add to history if enough time has passed since last record
                if not self.cell_history[i] or (current_time - self.cell_history[i][-1].timestamp >= DEFAULT_SAMPLE_INTERVAL):
                    self.cell_history[i].append(CellVoltageRecord(cell.voltage, current_time))
                
                updated = True
        
        # Update statistics
        if valid_count > 0:
            self.min_voltage = min_v
            self.max_voltage = max_v
            self.avg_voltage = total_v / valid_count
            self.voltage_spread = max_v - min_v
            self.last_update = current_time
        
        return updated
    
    def get_cell_voltage(self, cell_index: int) -> Optional[float]:
        """Get the current voltage for a specific cell"""
        if 0 <= cell_index < self.cell_count:
            return self.cell_voltages[cell_index]
        return None
    
    def is_cell_balancing(self, cell_index: int) -> bool:
        """Check if a specific cell is balancing"""
        if 0 <= cell_index < self.cell_count:
            return self.balancing[cell_index]
        return False
    
    def get_cell_history(self, cell_index: int) -> List[CellVoltageRecord]:
        """Get the voltage history for a specific cell"""
        if 0 <= cell_index < self.cell_count:
            return list(self.cell_history[cell_index])
        return []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "battery_id": self.battery_id,
            "cell_count": self.cell_count,
            "cell_history": [
                [record.to_dict() for record in cell_history]
                for cell_history in self.cell_history
            ]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhysicalBatteryCellData':
        """Create from dictionary"""
        instance = cls(
            battery_id=data["battery_id"],
            cell_count=data["cell_count"]
        )
        
        # Restore cell history
        for i, cell_records in enumerate(data["cell_history"]):
            if i < instance.cell_count:
                instance.cell_history[i] = deque(
                    [CellVoltageRecord.from_dict(record) for record in cell_records],
                    maxlen=MAX_HISTORY_POINTS
                )
        
        return instance


class CellMonitor:
    """
    Main cell monitoring system that manages cell data across multiple physical batteries
    """
    def __init__(self, virtual_battery: Virtual):
        """
        Initialize the cell monitor with a virtual battery object
        """
        self.virtual_battery = virtual_battery
        self.physical_batteries: Dict[str, PhysicalBatteryCellData] = {}
        self.lock = threading.Lock()
        self.alert_threshold = DEFAULT_ALERT_THRESHOLD
        self.alerts: List[Dict[str, Any]] = []
        self.running = True
        self.sample_interval = DEFAULT_SAMPLE_INTERVAL
        self.monitor_thread = None
        
        # Try to load history data
        self._load_history()
    
    def start_monitoring(self) -> None:
        """Start the monitoring thread"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            logger.info("Cell voltage monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop the monitoring thread"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
            logger.info("Cell voltage monitoring stopped")
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop that runs in a separate thread"""
        next_save_time = time.time() + 3600  # Save history every hour
        
        while self.running:
            try:
                self.update_all_batteries()
                
                # Check for alerts
                self._check_alerts()
                
                # Save history periodically
                current_time = time.time()
                if current_time >= next_save_time:
                    self._save_history()
                    next_save_time = current_time + 3600
                
                # Sleep until next collection interval
                time.sleep(self.sample_interval)
                
            except Exception as e:
                logger.error(f"Error in cell monitor thread: {e}")
                time.sleep(10)  # Sleep and retry on error
    
    def update_all_batteries(self) -> None:
        """Update cell data for all physical batteries"""
        if not self.virtual_battery or not hasattr(self.virtual_battery, 'batts'):
            return
        
        with self.lock:
            active_battery_ids = set()
            
            # Update data for each physical battery
            for battery in self.virtual_battery.batts:
                # Even if battery is marked as offline, try to get its data
                # for a more complete cell monitoring view
                
                # Skip batteries without cells
                if not hasattr(battery, 'cells') or not battery.cells:
                    continue
                
                # Get battery ID (address or another unique identifier)
                # Use a descriptive name if possible
                battery_id = getattr(battery, 'address', str(id(battery)))
                active_battery_ids.add(battery_id)
                
                # Create battery data object if it doesn't exist
                if battery_id not in self.physical_batteries:
                    cell_count = getattr(battery, 'cell_count', len(battery.cells))
                    name = getattr(battery, 'name', f"Battery {battery_id[-5:].replace(':', '')}")
                    logger.info(f"Adding new physical battery to cell monitor: {name} ({battery_id})")
                    self.physical_batteries[battery_id] = PhysicalBatteryCellData(battery_id, cell_count)
                
                # Update cell data
                updated = self.physical_batteries[battery_id].update_cell_data(battery)
                if updated and hasattr(battery, 'online') and not battery.online:
                    # Log that we got data from a battery marked as offline
                    logger.debug(f"Updated cell data for offline battery: {battery_id}")
            
            # Clean up batteries that are no longer present
            batteries_to_remove = set(self.physical_batteries.keys()) - active_battery_ids
            for battery_id in batteries_to_remove:
                logger.info(f"Removing inactive battery from cell monitor: {battery_id}")
                del self.physical_batteries[battery_id]
    
    def _check_alerts(self) -> None:
        """Check for alert conditions across all batteries"""
        with self.lock:
            # Check for severe cell voltage imbalances
            new_alerts = []
            
            for battery_id, battery_data in self.physical_batteries.items():
                # Skip if no valid data
                if battery_data.min_voltage is None or battery_data.max_voltage is None:
                    continue
                
                # Check if voltage spread exceeds threshold
                if battery_data.voltage_spread > self.alert_threshold:
                    alert = {
                        "type": "imbalance",
                        "battery_id": battery_id,
                        "spread": battery_data.voltage_spread,
                        "min": battery_data.min_voltage,
                        "max": battery_data.max_voltage,
                        "timestamp": time.time()
                    }
                    new_alerts.append(alert)
                    logger.warning(
                        f"Cell imbalance detected in battery {battery_id}: "
                        f"spread={battery_data.voltage_spread:.3f}V "
                        f"(min={battery_data.min_voltage:.3f}V, max={battery_data.max_voltage:.3f}V)"
                    )
            
            # Add new alerts to the list (limit to 100 recent alerts)
            self.alerts.extend(new_alerts)
            if len(self.alerts) > 100:
                self.alerts = self.alerts[-100:]
    
    def get_cell_data(self, battery_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cell data for a specific battery or all batteries
        
        Returns a dictionary with battery data including:
        - Overall stats (min/max/avg across all batteries)
        - Individual battery data
        - Recent alerts
        """
        with self.lock:
            result = {
                "timestamp": time.time(),
                "overall_stats": {
                    "min_voltage": None,
                    "max_voltage": None,
                    "avg_voltage": None,
                    "max_spread": None,
                },
                "batteries": {},
                "recent_alerts": self.alerts[:10]  # Return 10 most recent alerts
            }
            
            # Filter to a specific battery if requested
            batteries_to_process = {battery_id: self.physical_batteries[battery_id]} if battery_id and battery_id in self.physical_batteries else self.physical_batteries
            
            if not batteries_to_process:
                return result
            
            # Calculate overall stats
            all_voltages = []
            min_v = float('inf')
            max_v = float('-inf')
            max_spread = 0
            
            for battery_id, battery_data in batteries_to_process.items():
                if battery_data.min_voltage is not None and battery_data.max_voltage is not None:
                    min_v = min(min_v, battery_data.min_voltage)
                    max_v = max(max_v, battery_data.max_voltage)
                    max_spread = max(max_spread, battery_data.voltage_spread)
                    
                    # Collect all cell voltages for average calculation
                    all_voltages.extend([v for v in battery_data.cell_voltages if v is not None])
                
                # Add battery-specific data
                result["batteries"][battery_id] = {
                    "cell_count": battery_data.cell_count,
                    "min_voltage": battery_data.min_voltage,
                    "max_voltage": battery_data.max_voltage,
                    "avg_voltage": battery_data.avg_voltage,
                    "voltage_spread": battery_data.voltage_spread,
                    "last_update": battery_data.last_update,
                    "cell_voltages": battery_data.cell_voltages,
                    "balancing": battery_data.balancing
                }
            
            # Set overall stats
            if min_v != float('inf') and max_v != float('-inf'):
                result["overall_stats"]["min_voltage"] = min_v
                result["overall_stats"]["max_voltage"] = max_v
                result["overall_stats"]["max_spread"] = max_spread
                
                if all_voltages:
                    result["overall_stats"]["avg_voltage"] = sum(all_voltages) / len(all_voltages)
            
            return result
    
    def get_cell_history(self, battery_id: str, cell_index: int) -> List[Dict[str, Any]]:
        """Get history data for a specific cell"""
        with self.lock:
            if battery_id in self.physical_batteries:
                battery_data = self.physical_batteries[battery_id]
                history = battery_data.get_cell_history(cell_index)
                return [record.to_dict() for record in history]
            return []
    
    def set_alert_threshold(self, threshold: float) -> None:
        """Set the alert threshold for cell imbalance"""
        with self.lock:
            self.alert_threshold = max(0.01, threshold)  # Ensure minimum threshold
    
    def set_sample_interval(self, interval: int) -> None:
        """Set the sampling interval in seconds"""
        with self.lock:
            self.sample_interval = max(10, interval)  # Ensure minimum interval
    
    def _save_history(self) -> None:
        """Save cell history data to file"""
        try:
            with self.lock:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(HISTORY_FILE_PATH), exist_ok=True)
                
                # Prepare data structure
                data = {
                    "timestamp": time.time(),
                    "batteries": {
                        battery_id: battery_data.to_dict()
                        for battery_id, battery_data in self.physical_batteries.items()
                    }
                }
                
                # Write to file
                with open(HISTORY_FILE_PATH, 'w') as f:
                    json.dump(data, f)
                
                logger.info(f"Cell history data saved to {HISTORY_FILE_PATH}")
        
        except Exception as e:
            logger.error(f"Error saving cell history data: {e}")
    
    def _load_history(self) -> None:
        """Load cell history data from file"""
        try:
            if os.path.exists(HISTORY_FILE_PATH):
                with open(HISTORY_FILE_PATH, 'r') as f:
                    data = json.load(f)
                
                # Check timestamp to ensure data is not too old (7 days max)
                if time.time() - data.get("timestamp", 0) < 7 * 24 * 3600:
                    with self.lock:
                        for battery_id, battery_data in data.get("batteries", {}).items():
                            self.physical_batteries[battery_id] = PhysicalBatteryCellData.from_dict(battery_data)
                    
                    logger.info(f"Loaded cell history data from {HISTORY_FILE_PATH}")
        
        except Exception as e:
            logger.error(f"Error loading cell history data: {e}")
    
    def generate_cell_voltage_report(self) -> str:
        """Generate a formatted report of cell voltages across all batteries"""
        with self.lock:
            report = []
            report.append("=== Cell Voltage Report ===")
            report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report.append("")
            
            # Overall statistics
            cell_data = self.get_cell_data()
            stats = cell_data["overall_stats"]
            
            report.append("Overall Statistics:")
            if stats["min_voltage"] is not None:
                report.append(f"  Min Voltage: {stats['min_voltage']:.3f}V")
                report.append(f"  Max Voltage: {stats['max_voltage']:.3f}V")
                report.append(f"  Avg Voltage: {stats['avg_voltage']:.3f}V")
                report.append(f"  Max Spread: {stats['max_spread']:.3f}V")
            else:
                report.append("  No valid data available")
            
            report.append("")
            
            # Process each battery
            for battery_id, battery_data in self.physical_batteries.items():
                report.append(f"Battery: {battery_id}")
                report.append(f"  Cell Count: {battery_data.cell_count}")
                
                if battery_data.min_voltage is not None:
                    report.append(f"  Min Voltage: {battery_data.min_voltage:.3f}V")
                    report.append(f"  Max Voltage: {battery_data.max_voltage:.3f}V")
                    report.append(f"  Avg Voltage: {battery_data.avg_voltage:.3f}V")
                    report.append(f"  Voltage Spread: {battery_data.voltage_spread:.3f}V")
                    
                    # Cell voltage table
                    report.append("  Cell Voltages:")
                    cell_table = []
                    
                    # Table header
                    header = "  Cell |"
                    for i in range(battery_data.cell_count):
                        header += f" C{i+1:02d} |"
                    cell_table.append(header)
                    
                    # Voltage row
                    voltage_row = "  Volt |"
                    for i in range(battery_data.cell_count):
                        voltage = battery_data.cell_voltages[i]
                        if voltage is not None:
                            voltage_row += f" {voltage:.3f}|"
                        else:
                            voltage_row += " ---- |"
                    cell_table.append(voltage_row)
                    
                    # Balancing row
                    balance_row = "  Bal  |"
                    for i in range(battery_data.cell_count):
                        balance_row += " Yes |" if battery_data.balancing[i] else "  No |"
                    cell_table.append(balance_row)
                    
                    report.extend(cell_table)
                else:
                    report.append("  No valid cell data available")
                
                report.append("")
            
            # Recent alerts
            if cell_data["recent_alerts"]:
                report.append("Recent Alerts:")
                for alert in cell_data["recent_alerts"]:
                    alert_time = datetime.fromtimestamp(alert["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
                    report.append(f"  {alert_time} - Battery {alert['battery_id']}: Cell imbalance " +
                                 f"spread={alert['spread']:.3f}V (min={alert['min']:.3f}V, max={alert['max']:.3f}V)")
            
            return "\n".join(report)


# Global instance that can be accessed by other modules
_cell_monitor_instance = None

def get_cell_monitor() -> Optional[CellMonitor]:
    """Get the global cell monitor instance"""
    return _cell_monitor_instance

def init_cell_monitor(virtual_battery: Virtual) -> CellMonitor:
    """Initialize the global cell monitor instance"""
    global _cell_monitor_instance
    
    if _cell_monitor_instance is None:
        _cell_monitor_instance = CellMonitor(virtual_battery)
        _cell_monitor_instance.start_monitoring()
    
    return _cell_monitor_instance

def shutdown_cell_monitor() -> None:
    """Shutdown the global cell monitor instance"""
    global _cell_monitor_instance
    
    if _cell_monitor_instance is not None:
        _cell_monitor_instance.stop_monitoring()
        _cell_monitor_instance = None