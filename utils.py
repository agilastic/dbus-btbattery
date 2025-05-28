# -*- coding: utf-8 -*-
import logging

import configparser
from pathlib import Path
from typing import List, Any, Callable

from time import sleep
from struct import unpack_from
import bisect

# Logging
logging.basicConfig()
logger = logging.getLogger("BluetoothBattery")
logger.setLevel(logging.INFO)

def load_config(custom_config_path=None):
    config = configparser.ConfigParser()
    path = Path(__file__).parents[0]
    default_config_file_path = path.joinpath("default_config.ini").absolute().__str__()
    
    # Load custom config if specified, otherwise use default config.ini
    if custom_config_path:
        custom_config_file_path = custom_config_path
    else:
        custom_config_file_path = path.joinpath("config.ini").absolute().__str__()
    
    config.read([default_config_file_path, custom_config_file_path])
    return config

# Load default config initially
config = load_config()


def _get_list_from_config(
    group: str, option: str, mapper: Callable[[Any], Any] = lambda v: v
) -> List[Any]:
    rawList = config[group][option].split(",")
    return list(
        map(mapper, [item for item in rawList if item != "" and item is not None])
    )


# battery types
# if not specified: baud = 9600

# Constants - Need to dynamically get them in future
DRIVER_VERSION = 0.1
DRIVER_SUBVERSION = ".3"
zero_char = chr(48)
degree_sign = "\N{DEGREE SIGN}"

# Choose the mode for voltage / current limitations (True / False)
# False is a Step mode. This is the default with limitations on hard boundary steps
# True "Linear"    # New linear limitations by WaldemarFech for smoother values
LINEAR_LIMITATION_ENABLE = "True" == config["DEFAULT"]["LINEAR_LIMITATION_ENABLE"]

# battery Current limits
MAX_BATTERY_CHARGE_CURRENT = float(config["DEFAULT"]["MAX_BATTERY_CHARGE_CURRENT"])
MAX_BATTERY_DISCHARGE_CURRENT = float(config["DEFAULT"]["MAX_BATTERY_DISCHARGE_CURRENT"]
)

# Parallel battery imbalance detection settings
SOC_IMBALANCE_DETECTION_ENABLE = "True" == config["DEFAULT"].get("SOC_IMBALANCE_DETECTION_ENABLE", "True")
SOC_IMBALANCE_THRESHOLD = float(config["DEFAULT"].get("SOC_IMBALANCE_THRESHOLD", "10"))

# -------- Cell Voltage limitation ---------
# Description:
# Maximal charge / discharge current will be in-/decreased depending on min- and max-cell-voltages
# Example: 18cells * 3.55V/cell = 63.9V max charge voltage. 18 * 2.7V = 48,6V min discharge voltage
#          ... but the (dis)charge current will be (in-/)decreased, if even ONE SINGLE BATTERY CELL reaches the limits

# Charge current control management referring to cell-voltage enable (True/False).
CCCM_CV_ENABLE = "True" == config["DEFAULT"]["CCCM_CV_ENABLE"]
# Discharge current control management referring to cell-voltage enable (True/False).
DCCM_CV_ENABLE = "True" == config["DEFAULT"]["DCCM_CV_ENABLE"]

# Set Steps to reduce battery current. The current will be changed linear between those steps
CELL_VOLTAGES_WHILE_CHARGING = _get_list_from_config(
    "DEFAULT", "CELL_VOLTAGES_WHILE_CHARGING", lambda v: float(v)
)
MAX_CHARGE_CURRENT_CV = _get_list_from_config(
    "DEFAULT",
    "MAX_CHARGE_CURRENT_CV_FRACTION",
    lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v),
)

CELL_VOLTAGES_WHILE_DISCHARGING = _get_list_from_config(
    "DEFAULT", "CELL_VOLTAGES_WHILE_DISCHARGING", lambda v: float(v)
)
MAX_DISCHARGE_CURRENT_CV = _get_list_from_config(
    "DEFAULT",
    "MAX_DISCHARGE_CURRENT_CV_FRACTION",
    lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v),
)

# -------- Temperature limitation ---------
# Description:
# Maximal charge / discharge current will be in-/decreased depending on temperature
# Example: The temperature limit will be monitored to control the currents. If there are two temperature senors,
#          then the worst case will be calculated and the more secure lower current will be set.
# Charge current control management referring to temperature enable (True/False).
CCCM_T_ENABLE = "True" == config["DEFAULT"]["CCCM_T_ENABLE"]
# Charge current control management referring to temperature enable (True/False).
DCCM_T_ENABLE = "True" == config["DEFAULT"]["DCCM_T_ENABLE"]

# Set Steps to reduce battery current. The current will be changed linear between those steps
TEMPERATURE_LIMITS_WHILE_CHARGING = _get_list_from_config(
    "DEFAULT", "TEMPERATURE_LIMITS_WHILE_CHARGING", lambda v: float(v)
)
MAX_CHARGE_CURRENT_T = _get_list_from_config(
    "DEFAULT",
    "MAX_CHARGE_CURRENT_T_FRACTION",
    lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v),
)

TEMPERATURE_LIMITS_WHILE_DISCHARGING = _get_list_from_config(
    "DEFAULT", "TEMPERATURE_LIMITS_WHILE_DISCHARGING", lambda v: float(v)
)
MAX_DISCHARGE_CURRENT_T = _get_list_from_config(
    "DEFAULT",
    "MAX_DISCHARGE_CURRENT_T_FRACTION",
    lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v),
)

# if the cell voltage reaches 3.55V, then reduce current battery-voltage by 0.01V
# if the cell voltage goes over 3.6V, then the maximum penalty will not be exceeded
# there will be a sum of all penalties for each cell, which exceeds the limits
PENALTY_AT_CELL_VOLTAGE = _get_list_from_config(
    "DEFAULT", "PENALTY_AT_CELL_VOLTAGE", lambda v: float(v)
)
PENALTY_BATTERY_VOLTAGE = _get_list_from_config(
    "DEFAULT", "PENALTY_BATTERY_VOLTAGE", lambda v: float(v)
)


# -------- SOC limitation ---------
# Description:
# Maximal charge / discharge current will be increased / decreased depending on State of Charge, see CC_SOC_LIMIT1 etc.
# The State of Charge (SoC) charge / discharge current will be in-/decreased depending on SOC.
# Example: 16cells * 3.45V/cell = 55,2V max charge voltage. 16*2.9V = 46,4V min discharge voltage
# Cell min/max voltages - used with the cell count to get the min/max battery voltage
MIN_CELL_VOLTAGE = float(config["DEFAULT"]["MIN_CELL_VOLTAGE"])
MAX_CELL_VOLTAGE = float(config["DEFAULT"]["MAX_CELL_VOLTAGE"])
FLOAT_CELL_VOLTAGE = float(config["DEFAULT"]["FLOAT_CELL_VOLTAGE"])
MAX_VOLTAGE_TIME_SEC = float(config["DEFAULT"]["MAX_VOLTAGE_TIME_SEC"])
SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT = float(
    config["DEFAULT"]["SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT"]
)

# Charge current control management enable (True/False).
CCCM_SOC_ENABLE = "True" == config["DEFAULT"]["CCCM_SOC_ENABLE"]
# Discharge current control management enable (True/False).
DCCM_SOC_ENABLE = "True" == config["DEFAULT"]["DCCM_SOC_ENABLE"]

# charge current soc limits
CC_SOC_LIMIT1 = float(config["DEFAULT"]["CC_SOC_LIMIT1"])
CC_SOC_LIMIT2 = float(config["DEFAULT"]["CC_SOC_LIMIT2"])
CC_SOC_LIMIT3 = float(config["DEFAULT"]["CC_SOC_LIMIT3"])

# charge current limits
CC_CURRENT_LIMIT1 = MAX_BATTERY_CHARGE_CURRENT * float(
    config["DEFAULT"]["CC_CURRENT_LIMIT1_FRACTION"]
)
CC_CURRENT_LIMIT2 = MAX_BATTERY_CHARGE_CURRENT * float(
    config["DEFAULT"]["CC_CURRENT_LIMIT2_FRACTION"]
)
CC_CURRENT_LIMIT3 = MAX_BATTERY_CHARGE_CURRENT * float(
    config["DEFAULT"]["CC_CURRENT_LIMIT3_FRACTION"]
)

# discharge current soc limits
DC_SOC_LIMIT1 = float(config["DEFAULT"]["DC_SOC_LIMIT1"])
DC_SOC_LIMIT2 = float(config["DEFAULT"]["DC_SOC_LIMIT2"])
DC_SOC_LIMIT3 = float(config["DEFAULT"]["DC_SOC_LIMIT3"])

# discharge current limits
DC_CURRENT_LIMIT1 = MAX_BATTERY_DISCHARGE_CURRENT * float(
    config["DEFAULT"]["DC_CURRENT_LIMIT1_FRACTION"]
)
DC_CURRENT_LIMIT2 = MAX_BATTERY_DISCHARGE_CURRENT * float(
    config["DEFAULT"]["DC_CURRENT_LIMIT2_FRACTION"]
)
DC_CURRENT_LIMIT3 = MAX_BATTERY_DISCHARGE_CURRENT * float(
    config["DEFAULT"]["DC_CURRENT_LIMIT3_FRACTION"]
)

# Charge voltage control management enable (True/False).
CVCM_ENABLE = "True" == config["DEFAULT"]["CVCM_ENABLE"]

# Simulate Midpoint graph (True/False).
MIDPOINT_ENABLE = "True" == config["DEFAULT"]["MIDPOINT_ENABLE"]

# soc low levels
SOC_LOW_WARNING = float(config["DEFAULT"]["SOC_LOW_WARNING"])
SOC_LOW_ALARM = float(config["DEFAULT"]["SOC_LOW_ALARM"])

# Daly settings
# Battery capacity (amps) if the BMS does not support reading it
BATTERY_CAPACITY = float(config["DEFAULT"]["BATTERY_CAPACITY"])
# Invert Battery Current. Default non-inverted. Set to -1 to invert
INVERT_CURRENT_MEASUREMENT = int(config["DEFAULT"]["INVERT_CURRENT_MEASUREMENT"])

# TIME TO SOC settings [Valid values 0-100, but I don't recommend more that 20 intervals]
# Set of SoC percentages to report on dbus. The more you specify the more it will impact system performance.
# TIME_TO_SOC_POINTS = [100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 0]
# Every 5% SoC
# TIME_TO_SOC_POINTS = [100, 95, 90, 85, 75, 50, 25, 20, 10, 0]
TIME_TO_SOC_POINTS = _get_list_from_config("DEFAULT", "TIME_TO_SOC_POINTS")
# Specify TimeToSoc value type: [Valid values 1,2,3]
# TIME_TO_SOC_VALUE_TYPE = 1      # Seconds
# TIME_TO_SOC_VALUE_TYPE = 2      # Time string HH:MN:SC
TIME_TO_SOC_VALUE_TYPE = int(config["DEFAULT"]["TIME_TO_SOC_VALUE_TYPE"])
# Specify how many loop cycles between each TimeToSoc updates
TIME_TO_SOC_LOOP_CYCLES = int(config["DEFAULT"]["TIME_TO_SOC_LOOP_CYCLES"])
# Include TimeToSoC points when moving away from the SoC point. [Valid values True,False]
# These will be as negative time. Disabling this improves performance slightly.
TIME_TO_SOC_INC_FROM = "True" == config["DEFAULT"]["TIME_TO_SOC_INC_FROM"]


# Select the format of cell data presented on dbus. [Valid values 0,1,2,3]
# 0 Do not publish all the cells (only the min/max cell data as used by the default GX)
# 1 Format: /Voltages/Cell# (also available for display on Remote Console)
# 2 Format: /Cell/#/Volts
# 3 Both formats 1 and 2
BATTERY_CELL_DATA_FORMAT = int(config["DEFAULT"]["BATTERY_CELL_DATA_FORMAT"])


PUBLISH_CONFIG_VALUES = int(config["DEFAULT"]["PUBLISH_CONFIG_VALUES"])

BMS_TYPE = config["DEFAULT"]["BMS_TYPE"]


def constrain(val, min_val, max_val):
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    return min(max_val, max(min_val, val))


def mapRange(inValue, inMin, inMax, outMin, outMax):
    return outMin + (((inValue - inMin) / (inMax - inMin)) * (outMax - outMin))


def mapRangeConstrain(inValue, inMin, inMax, outMin, outMax):
    return constrain(mapRange(inValue, inMin, inMax, outMin, outMax), outMin, outMax)


def calcLinearRelationship(inValue, inArray, outArray):
    if inArray[0] > inArray[-1]:  # change compare-direction in array
        return calcLinearRelationship(inValue, inArray[::-1], outArray[::-1])
    else:

        # Handle out of bounds
        if inValue <= inArray[0]:
            return outArray[0]
        if inValue >= inArray[-1]:
            return outArray[-1]

        # else calculate linear current between the setpoints
        idx = bisect.bisect(inArray, inValue)
        upperIN = inArray[idx - 1]  # begin with idx 0 as max value
        upperOUT = outArray[idx - 1]
        lowerIN = inArray[idx]
        lowerOUT = outArray[idx]
        return mapRangeConstrain(inValue, lowerIN, upperIN, lowerOUT, upperOUT)


def calcStepRelationship(inValue, inArray, outArray, returnLower):
    if inArray[0] > inArray[-1]:  # change compare-direction in array
        return calcStepRelationship(inValue, inArray[::-1], outArray[::-1], returnLower)

    # Handle out of bounds
    if inValue <= inArray[0]:
        return outArray[0]
    if inValue >= inArray[-1]:
        return outArray[-1]

    # else get index between the setpoints
    idx = bisect.bisect(inArray, inValue)

    return outArray[idx] if returnLower else outArray[idx - 1]


def is_bit_set(tmp):
    return False if tmp == zero_char else True


def kelvin_to_celsius(kelvin_temp):
    return kelvin_temp - 273.1


def format_value(value, prefix, suffix):
    return (
        None
        if value is None
        else ("" if prefix is None else prefix)
        + str(value)
        + ("" if suffix is None else suffix)
    )




locals_copy = locals().copy()


def publish_config_variables(dbusservice):
    for variable, value in locals_copy.items():
        if variable.startswith("__"):
            continue
        if (
            isinstance(value, float)
            or isinstance(value, int)
            or isinstance(value, str)
            or isinstance(value, List)
        ):
            dbusservice.add_path(f"/Info/Config/{variable}", value)
