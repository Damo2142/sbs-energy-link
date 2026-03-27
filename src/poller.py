"""
SBS EnergyLink - Modbus TCP Poller
Reads all BESS data points from the Tesla Site Controller / EPMS
using Modbus TCP Function Code 04 (Read Input Registers).

Register map based on JPMC Discovery BESS - EPMS/BMS Tie-In specification.
"""

import logging
import time
import struct
from typing import Optional

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from data_store import DataStore, BESSData

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Register Map
# All FC04 (Read Input Registers) unless noted
# ---------------------------------------------------------------------------

REG_APP_VERSION         = 200   # INT16
REG_BESS_CAPACITY       = 201   # INT32 (2 registers: 201, 202)
REG_BESS_POWER          = 202   # INT16  -- NOTE: overlaps INT32 above
# We handle this carefully - read 200-217 in one block then parse

REG_BESS_POWER_SETPOINT = 203   # INT16
REG_BESS_MAX_CHARGE     = 204   # INT16
REG_BESS_MAX_DISCHARGE  = 205   # INT16
REG_BESS_SOC            = 206   # INT16  %
REG_BESS_ERROR_PRESENT  = 207   # INT16  (0=ok, 1=error)
REG_BESS_FAULT_BITS     = 208   # INT16  (bit-packed fault flags)
REG_BESS_TOTAL_CHARGED  = 209   # INT32 (2 registers: 209, 210)
REG_BESS_TOTAL_DISCH    = 210   # INT16 -- part of INT32 above
REG_GRID_POWER          = 211   # INT16
REG_GRID_IMPORT         = 212   # INT32 (2 registers: 212, 213)
REG_GRID_EXPORT         = 213   # INT16 -- part of INT32 above
REG_SOLAR_POWER         = 214   # INT16
REG_SOLAR_ENERGY        = 215   # INT32 (2 registers: 215, 216)
REG_LOAD_POWER          = 216   # INT16 -- part of INT32 above
REG_LOAD_ENERGY         = 217   # INT32 (2 registers: 217, 218)

REG_ACTIVE_PWR_CMD      = 300   # INT16  FC03/06/16 (readable + writable)

# Fault bit masks for register 208
FAULT_COMM_ERROR        = 0x0001   # bit 0
FAULT_LOW_CELL_VOLT     = 0x0002   # bit 1
FAULT_HIGH_CELL_VOLT    = 0x0004   # bit 2
FAULT_LOW_TEMP          = 0x0008   # bit 3
FAULT_HIGH_TEMP         = 0x0010   # bit 4


def _to_int32(high: int, low: int) -> int:
    """Combine two 16-bit Modbus registers into a signed 32-bit integer."""
    combined = (high << 16) | low
    # Convert to signed
    if combined >= 0x80000000:
        combined -= 0x100000000
    return combined


def _to_int16_signed(val: int) -> int:
    """Convert unsigned 16-bit Modbus value to signed."""
    if val >= 0x8000:
        val -= 0x10000
    return val


class ModbusPoller:
    """
    Connects to the EPMS/Tesla Site Controller via Modbus TCP and
    continuously reads all data points, writing results to the DataStore.
    """

    def __init__(self, config: dict, store: DataStore):
        self.host = config["modbus"]["host"]
        self.port = config["modbus"].get("port", 502)
        self.unit_id = config["modbus"].get("unit_id", 1)
        self.poll_interval = config.get("poll_interval_seconds", 30)
        self.stale_timeout = config.get("stale_data_timeout_seconds", 120)
        self.store = store
        self._client: Optional[ModbusTcpClient] = None
        self._running = False

    def _connect(self) -> bool:
        """Establish Modbus TCP connection."""
        try:
            self._client = ModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=10
            )
            result = self._client.connect()
            if result:
                log.info(f"Modbus connected to {self.host}:{self.port} unit {self.unit_id}")
            else:
                log.error(f"Modbus connection failed to {self.host}:{self.port}")
            return result
        except Exception as e:
            log.error(f"Modbus connect exception: {e}")
            return False

    def _disconnect(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _read_all(self) -> Optional[BESSData]:
        """
        Read all registers in two passes:
        1. Registers 200-218 (main data block, FC04)
        2. Register 300 (active power command, FC03)
        Returns populated BESSData or None on failure.
        """
        try:
            # --- Pass 1: Read registers 200-218 (19 registers) FC04 ---
            result = self._client.read_input_registers(
                address=200,
                count=19,
                slave=self.unit_id
            )
            if result.isError():
                log.error(f"Modbus FC04 read error: {result}")
                return None

            r = result.registers
            # r[0] = reg200, r[1] = reg201, etc.

            data = BESSData()

            # INT16 singles
            data.application_version  = float(_to_int16_signed(r[0]))   # 200
            # r[1] is high word of BESS_CAPACITY INT32
            # r[2] is BESS_POWER INT16 - BUT also low word of BESS_CAPACITY
            # Per spec: 201=INT32 (capacity), 202=INT16 (power)
            # This means capacity uses regs 201+202 as INT32
            data.bess_capacity_kwh    = float(_to_int32(r[1], r[2]))    # 201-202
            data.bess_power_kw        = float(_to_int16_signed(r[2]))   # 202 standalone
            data.bess_power_setpoint_kw = float(_to_int16_signed(r[3])) # 203
            data.bess_max_charge_kw   = float(_to_int16_signed(r[4]))   # 204
            data.bess_max_discharge_kw = float(_to_int16_signed(r[5]))  # 205
            data.bess_soc_pct         = float(_to_int16_signed(r[6]))   # 206

            # Error / fault registers
            data.bess_error_present   = bool(r[7])                      # 207
            fault_bits                = r[8]                             # 208
            data.bess_comm_error      = bool(fault_bits & FAULT_COMM_ERROR)
            data.bess_low_cell_voltage = bool(fault_bits & FAULT_LOW_CELL_VOLT)
            data.bess_high_cell_voltage = bool(fault_bits & FAULT_HIGH_CELL_VOLT)
            data.bess_low_temp_error  = bool(fault_bits & FAULT_LOW_TEMP)
            data.bess_high_temp_error = bool(fault_bits & FAULT_HIGH_TEMP)

            # INT32 pairs
            data.bess_total_charged_kwh   = float(_to_int32(r[9],  r[10])) # 209-210
            data.bess_total_discharged_kwh = float(_to_int32(r[10], r[11])) # 210-211
            data.grid_power_kw            = float(_to_int16_signed(r[11]))  # 211
            data.grid_energy_import_kwh   = float(_to_int32(r[12], r[13])) # 212-213
            data.grid_energy_export_kwh   = float(_to_int32(r[13], r[14])) # 213-214  
            data.solar_power_kw           = float(_to_int16_signed(r[14])) # 214
            data.solar_energy_produced_kwh = float(_to_int32(r[15], r[16])) # 215-216
            data.load_power_kw            = float(_to_int16_signed(r[16])) # 216
            data.load_energy_consumed_kwh  = float(_to_int32(r[17], r[18])) # 217-218

            # --- Pass 2: Read register 300 FC03 (holding register, readable) ---
            result2 = self._client.read_holding_registers(
                address=300,
                count=1,
                slave=self.unit_id
            )
            if not result2.isError():
                data.bess_active_power_cmd_kw = float(
                    _to_int16_signed(result2.registers[0])
                )
            else:
                log.warning("Could not read register 300 (active power cmd)")
                data.bess_active_power_cmd_kw = 0.0

            return data

        except ModbusException as e:
            log.error(f"Modbus exception during read: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error during Modbus read: {e}")
            return None

    def write_power_command(self, kw: float) -> bool:
        """
        Write active power setpoint to register 300 (FC06 single register write).
        Positive = charge, Negative = discharge (confirm with Tesla documentation).
        Returns True on success.
        """
        if not self._client or not self._client.is_socket_open():
            log.error("Cannot write - Modbus not connected")
            return False

        try:
            value = int(kw)
            # Convert to unsigned 16-bit for Modbus
            if value < 0:
                value = value + 0x10000

            result = self._client.write_register(
                address=300,
                value=value,
                slave=self.unit_id
            )
            if result.isError():
                log.error(f"Write to register 300 failed: {result}")
                return False

            log.info(f"Power command written: {kw} kW to register 300")
            return True

        except Exception as e:
            log.error(f"Exception writing power command: {e}")
            return False

    def run(self):
        """
        Main polling loop. Runs forever, reconnecting on connection loss.
        Call this in a dedicated thread.
        """
        self._running = True
        log.info(f"Modbus poller starting — {self.host}:{self.port} "
                 f"every {self.poll_interval}s")

        while self._running:
            # Connect if not connected
            if not self._client or not self._client.is_socket_open():
                log.info("Attempting Modbus connection...")
                if not self._connect():
                    log.warning("Connection failed, retrying in 30s")
                    self.store.mark_poll_failed()
                    time.sleep(30)
                    continue

            # Read all points
            data = self._read_all()

            if data is not None:
                self.store.update(data)
                log.debug(f"Poll OK — SOC: {data.bess_soc_pct:.1f}% "
                          f"Power: {data.bess_power_kw:.1f}kW "
                          f"Grid: {data.grid_power_kw:.1f}kW")
            else:
                log.warning("Poll failed — marking data stale")
                self.store.mark_stale()
                self._disconnect()

            # Check stale threshold
            if self.store.is_stale(self.stale_timeout):
                log.error("Data is STALE — BACnet reliability will be set to fault")

            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False
        self._disconnect()
        log.info("Modbus poller stopped")
