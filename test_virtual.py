#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Test script for enhanced virtual battery support
"""

from virtual import Virtual
from battery import Battery, Cell, Protection

# Create a simple test battery class
class TestBattery(Battery):
    def __init__(self, addr, voltage=13.2, current=5.0, soc=80.0):
        Battery.__init__(self, '/test', 0, addr)
        self.voltage = voltage
        self.current = current
        self.soc = soc
        self.capacity = 100.0
        self.capacity_remain = soc * self.capacity / 100.0
        self.cell_count = 4
        self.cells = [Cell(0) for _ in range(4)]
        
        # Set cell voltages
        for i, c in enumerate(self.cells):
            c.voltage = 3.3 + i*0.01
        
        # Status flags
        self.online = True
        self.charge_fet = True
        self.discharge_fet = True
        
        # Current limits
        self.max_battery_charge_current = 50.0
        self.max_battery_discharge_current = 60.0
        
        # Temperature
        self.temp1 = 25.0
        self.temp2 = None
        self.temp_sensors = 1
        
        # History
        self.cycles = 10
        self.total_ah_drawn = 200.0
        
        # Other required methods
        self.protection = Protection()
    
    def test_connection(self):
        return True
    
    def get_settings(self):
        return True
    
    def refresh_data(self):
        return True

# Create test batteries with different values
b1 = TestBattery('AA:BB:CC:DD:EE:FF', voltage=13.2, current=5.0, soc=80.0)
b2 = TestBattery('11:22:33:44:55:66', voltage=13.4, current=4.8, soc=82.0)

# Test parallel mode
print("Testing parallel mode...")
v_parallel = Virtual(batteries=[b1, b2], series_config=False)
v_parallel.get_settings()

print(f'Voltage: {v_parallel.voltage:.2f}V')
print(f'Current: {v_parallel.current:.2f}A')
print(f'Capacity: {v_parallel.capacity:.1f}Ah')
print(f'SOC: {v_parallel.soc:.1f}%')
print(f'Cell count: {v_parallel.cell_count}')

# Test for imbalance detection
print("\nImbalance detection test...")
b1.voltage = 13.2
b2.voltage = 13.8  # > 0.3V difference should trigger imbalance
v_parallel.refresh_data()

print(f'Voltage imbalance detected: {v_parallel.voltage_imbalance}')
print(f'Current imbalance detected: {v_parallel.current_imbalance}')
print(f'SOC imbalance detected: {v_parallel.soc_imbalance}')

# Test series mode
print("\nTesting series mode...")
v_series = Virtual(batteries=[b1, b2], series_config=True)
v_series.get_settings()

print(f'Voltage: {v_series.voltage:.2f}V')
print(f'Current: {v_series.current:.2f}A')
print(f'Capacity: {v_series.capacity:.1f}Ah')
print(f'SOC: {v_series.soc:.1f}%')
print(f'Cell count: {v_series.cell_count}')

print("\nTesting charge management...")
v_parallel.manage_charge_voltage()
v_parallel.manage_charge_current()

print(f'Control voltage: {v_parallel.control_voltage:.2f}V')
print(f'Control charge current: {v_parallel.control_charge_current:.2f}A')
print(f'Control discharge current: {v_parallel.control_discharge_current:.2f}A')

# Test with a battery offline
print("\nTesting with one battery offline...")
b2.online = False
v_parallel.refresh_data()

print(f'Voltage: {v_parallel.voltage:.2f}V')
print(f'Current: {v_parallel.current:.2f}A')
print(f'Online status: {v_parallel.online}')
print(f'Active batteries: {sum(1 for b in v_parallel.batts if hasattr(b, "online") and b.online)}')

print("\nTest completed successfully!")