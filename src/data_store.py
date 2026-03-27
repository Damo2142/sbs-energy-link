"""
SBS EnergyLink - Shared Data Store
Thread-safe in-memory state shared between the Modbus poller
and the BACnet server.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BESSData:
    """All data points read from the Tesla BESS / EPMS via Modbus."""

    # --- Analog Points ---
    application_version: float = 0.0        # Reg 200 - INT16
    bess_capacity_kwh: float = 0.0          # Reg 201 - INT32  kWh
    bess_power_kw: float = 0.0             # Reg 202 - INT16  kW
    bess_power_setpoint_kw: float = 0.0    # Reg 203 - INT16  kW
    bess_max_charge_kw: float = 0.0        # Reg 204 - INT16  kW
    bess_max_discharge_kw: float = 0.0     # Reg 205 - INT16  kW
    bess_soc_pct: float = 0.0              # Reg 206 - INT16  %
    bess_total_charged_kwh: float = 0.0    # Reg 209 - INT32  kWh
    bess_total_discharged_kwh: float = 0.0 # Reg 210 - INT32  kWh
    grid_power_kw: float = 0.0             # Reg 211 - INT16  kW
    grid_energy_import_kwh: float = 0.0    # Reg 212 - INT32  kWh
    grid_energy_export_kwh: float = 0.0    # Reg 213 - INT32  kWh
    solar_power_kw: float = 0.0            # Reg 214 - INT16  kW
    solar_energy_produced_kwh: float = 0.0 # Reg 215 - INT32  kWh
    load_power_kw: float = 0.0             # Reg 216 - INT16  kW
    load_energy_consumed_kwh: float = 0.0  # Reg 217 - INT32  kWh

    # --- Writable ---
    bess_active_power_cmd_kw: float = 0.0  # Reg 300 - INT16  kW (read/write)

    # --- Binary / Fault Points ---
    bess_error_present: bool = False        # Reg 207 - 0=no errors, 1=errors
    bess_comm_error: bool = False           # Reg 208 bit 0
    bess_low_cell_voltage: bool = False     # Reg 208 bit 1
    bess_high_cell_voltage: bool = False    # Reg 208 bit 2
    bess_low_temp_error: bool = False       # Reg 208 bit 3
    bess_high_temp_error: bool = False      # Reg 208 bit 4

    # --- Health / Metadata ---
    last_update: float = 0.0               # Unix timestamp of last successful poll
    poll_success: bool = False             # True if last poll was successful
    stale: bool = True                     # True if data is older than timeout


class DataStore:
    """
    Thread-safe shared data store.
    The Modbus poller writes here; the BACnet server reads from here.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._data = BESSData()

    def update(self, data: BESSData):
        with self._lock:
            self._data = data
            self._data.last_update = time.time()
            self._data.poll_success = True
            self._data.stale = False

    def mark_stale(self):
        with self._lock:
            self._data.stale = True
            self._data.poll_success = False

    def mark_poll_failed(self):
        with self._lock:
            self._data.poll_success = False

    def get(self) -> BESSData:
        with self._lock:
            return self._data

    def is_stale(self, timeout_seconds: int = 120) -> bool:
        with self._lock:
            if self._data.last_update == 0:
                return True
            return (time.time() - self._data.last_update) > timeout_seconds

    def seconds_since_update(self) -> Optional[float]:
        with self._lock:
            if self._data.last_update == 0:
                return None
            return time.time() - self._data.last_update


# Singleton instance shared across all modules
store = DataStore()
