#!/usr/bin/env python3
"""
SBS EnergyLink - Modbus TCP Simulator
Simulates a Tesla EPMS / Site Controller on port 5020.

Provides the same register map that the real poller reads:
  - Input Registers 200-218 (FC04) — BESS data
  - Holding Register 300 (FC03/06) — Active Power Command (R/W)

Values cycle realistically so the BACnet server has changing data
to serve. Run alongside main.py (without --sim) to test the full
Modbus → DataStore → BACnet pipeline.

Usage:
    python tools/modbus_simulator.py              # port 5020
    python tools/modbus_simulator.py --port 502   # real port (needs root)
"""

import argparse
import logging
import math
import struct
import sys
import threading
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)
from pymodbus.server import StartTcpServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("modbus-sim")


def _to_uint16(val: int) -> int:
    """Convert signed int to unsigned 16-bit for Modbus register."""
    if val < 0:
        val += 0x10000
    return val & 0xFFFF


def _int32_to_regs(val: int) -> tuple[int, int]:
    """Split signed 32-bit int into two unsigned 16-bit registers (high, low)."""
    if val < 0:
        val += 0x100000000
    high = (val >> 16) & 0xFFFF
    low = val & 0xFFFF
    return high, low


class BESSSimulator:
    """Generates realistic cycling Tesla BESS data and writes to datastore."""

    def __init__(self, context: ModbusServerContext):
        self.context = context
        self.t = 0.0
        self._running = True
        # Accumulating energy counters
        self.total_charged = 10000.0
        self.total_discharged = 9500.0
        self.grid_import = 50000.0
        self.grid_export = 30000.0
        self.solar_produced = 15000.0
        self.load_consumed = 80000.0

    def run(self):
        """Update registers every 2 seconds with cycling data."""
        log.info("BESS simulator running — updating registers every 2s")
        while self._running:
            self._update()
            time.sleep(2)
            self.t += 2

    def _update(self):
        t = self.t
        slave = self.context[1]  # unit_id = 1

        # --- Analog values with realistic cycling ---
        soc = 50.0 + 40.0 * math.sin(t / 60.0)
        bess_power = 500.0 * math.sin(t / 30.0)
        grid_power = 200.0 + 100.0 * math.sin(t / 45.0)
        solar_power = max(0.0, 300.0 * math.sin(t / 50.0))
        load_power = 350.0 + 50.0 * math.sin(t / 20.0)

        # Accumulate energy (kWh = kW * hours, 2s = 2/3600 hours)
        dt_h = 2.0 / 3600.0
        if bess_power > 0:
            self.total_charged += bess_power * dt_h
        else:
            self.total_discharged += abs(bess_power) * dt_h
        if grid_power > 0:
            self.grid_import += grid_power * dt_h
        else:
            self.grid_export += abs(grid_power) * dt_h
        self.solar_produced += solar_power * dt_h
        self.load_consumed += load_power * dt_h

        # Occasional fault simulation (every ~120s, lasts ~10s)
        fault_active = (int(t) % 120) > 110
        error_present = 1 if fault_active else 0
        fault_bits = 0x0001 if fault_active else 0  # comm error bit

        # --- Build register block 200-218 (19 registers) ---
        # pymodbus input registers are 0-indexed internally
        regs = [0] * 19

        regs[0] = _to_uint16(1)                            # 200: App Version
        h, l = _int32_to_regs(3900)                        # 201-202: Capacity (INT32)
        regs[1] = h
        regs[2] = _to_uint16(int(bess_power))              # 202: BESS Power (overlaps)
        regs[3] = _to_uint16(500)                           # 203: Power Setpoint
        regs[4] = _to_uint16(1264)                          # 204: Max Charge
        regs[5] = _to_uint16(1264)                          # 205: Max Discharge
        regs[6] = _to_uint16(int(soc))                      # 206: SOC %
        regs[7] = _to_uint16(error_present)                 # 207: Error Present
        regs[8] = _to_uint16(fault_bits)                    # 208: Fault Bits

        h, l = _int32_to_regs(int(self.total_charged))     # 209-210: Total Charged
        regs[9] = h; regs[10] = l
        regs[11] = _to_uint16(int(grid_power))              # 211: Grid Power (overlaps 210-211 INT32)

        h, l = _int32_to_regs(int(self.grid_import))       # 212-213: Grid Import
        regs[12] = h; regs[13] = l
        regs[14] = _to_uint16(int(solar_power))             # 214: Solar Power (overlaps 213-214)

        h, l = _int32_to_regs(int(self.solar_produced))    # 215-216: Solar Produced
        regs[15] = h; regs[16] = l

        h, l = _int32_to_regs(int(self.load_consumed))     # 217-218: Load Consumed
        regs[17] = h; regs[18] = l

        # Write to input registers (FC04) starting at address 200
        slave.setValues(4, 200, regs)

        if int(t) % 10 == 0:
            log.debug(
                f"SOC={soc:.0f}% Power={bess_power:.0f}kW "
                f"Grid={grid_power:.0f}kW Solar={solar_power:.0f}kW "
                f"Load={load_power:.0f}kW Fault={'YES' if fault_active else 'no'}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="SBS EnergyLink — Modbus TCP BESS Simulator"
    )
    parser.add_argument(
        "--port", type=int, default=5020,
        help="TCP port to listen on (default: 5020)"
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)"
    )
    args = parser.parse_args()

    # --- Build datastore ---
    # Input registers (FC04): 200-218, pre-filled with zeros
    # Need address range to cover 200-218 → start at 200, 19 values
    ir_block = ModbusSequentialDataBlock(200, [0] * 119)  # 200-318

    # Holding registers (FC03/06): 300 for power command
    hr_block = ModbusSequentialDataBlock(300, [0] * 10)

    slave = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [0]),   # unused
        co=ModbusSequentialDataBlock(0, [0]),   # unused
        hr=hr_block,                             # FC03/06 — holding regs
        ir=ir_block,                             # FC04 — input regs
    )
    context = ModbusServerContext(slaves={1: slave}, single=False)

    # --- Start simulator thread ---
    sim = BESSSimulator(context)
    t = threading.Thread(target=sim.run, daemon=True, name="bess-sim")
    t.start()

    # --- Start Modbus TCP server ---
    log.info(f"Modbus TCP simulator listening on {args.host}:{args.port}")
    log.info(f"  Input Registers 200-218 (FC04) — BESS data, cycling")
    log.info(f"  Holding Register 300 (FC03/06) — Power Command (R/W)")
    log.info(f"  Unit ID: 1")
    log.info(f"")
    log.info(f"  Point your config.yaml modbus.host at this machine,")
    log.info(f"  set modbus.port to {args.port}, and run main.py without --sim")

    try:
        StartTcpServer(
            context=context,
            address=(args.host, args.port),
        )
    except KeyboardInterrupt:
        log.info("Shutting down")
    except OSError as e:
        log.error(f"Cannot bind to {args.host}:{args.port}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
