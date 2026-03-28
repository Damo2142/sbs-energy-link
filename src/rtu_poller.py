"""
SBS EnergyLink - Modbus RTU Poller
Reads multiple Modbus RTU devices on the RevPi RS485 port (/dev/ttyRS485).

Each RTU device has its own Modbus address and device profile loaded from
config/device_profiles/. Points from each device are added to the BACnet
server as additional objects in Device 9001, with instance numbers offset
per device to avoid collisions.

In DEV_MODE, simulates RTU devices with random realistic values.
"""

import logging
import math
import os
import random
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# BACnet instance offset for RTU devices — device 0 starts at AI:100, BI:100
# Each device gets 50 instance slots (AI:100-149, AI:150-199, etc.)
RTU_INSTANCE_BASE = 100
RTU_INSTANCE_SLOT = 50


@dataclass
class RTUPoint:
    """A single register point read from an RTU device."""
    address: int = 0
    name: str = ""
    reg_type: str = "INT16"       # INT16, INT32, FLOAT, COIL
    function_code: int = 4
    scale: float = 1.0
    bacnet_type: str = "AI"       # AI, BI, AV, BV
    units: str = "noUnits"
    description: str = ""
    writable: bool = False
    value: float = 0.0            # current scaled value
    raw_value: int = 0


@dataclass
class RTUDevice:
    """Configuration and state for one RTU device on the serial bus."""
    index: int = 0                # 0-based device index for instance offsets
    address: int = 1              # Modbus RTU slave address (1-247)
    profile_file: str = ""        # device profile filename
    profile_name: str = ""        # display name from profile
    device_id: int = 0            # BACnet device ID (0 = merge into 9001)
    points: list = field(default_factory=list)
    connected: bool = False
    last_poll: float = 0.0
    poll_errors: int = 0

    @property
    def ai_base(self) -> int:
        """Base BACnet AI instance number for this device."""
        return RTU_INSTANCE_BASE + (self.index * RTU_INSTANCE_SLOT)

    @property
    def bi_base(self) -> int:
        """Base BACnet BI instance number for this device."""
        return RTU_INSTANCE_BASE + (self.index * RTU_INSTANCE_SLOT)


def _load_rtu_devices(config: dict) -> list[RTUDevice]:
    """Build RTUDevice list from config.yaml rtu_devices section."""
    from profiles import load_profile

    devices = []
    for i, entry in enumerate(config.get("rtu_devices", [])):
        dev = RTUDevice(
            index=i,
            address=entry.get("address", 1),
            profile_file=entry.get("profile", ""),
            device_id=entry.get("device_id", 0),
        )

        # Load profile and build points
        if dev.profile_file:
            profile = load_profile(dev.profile_file)
            if profile:
                dev.profile_name = profile.get("name", dev.profile_file)
                for reg in profile.get("registers", []):
                    dev.points.append(RTUPoint(
                        address=reg.get("address", 0),
                        name=reg.get("name", ""),
                        reg_type=reg.get("type", "INT16"),
                        function_code=reg.get("function_code", 4),
                        scale=float(reg.get("scale", 1.0)),
                        bacnet_type=reg.get("bacnet_type", "AI"),
                        units=reg.get("units", "noUnits"),
                        description=reg.get("description", ""),
                        writable=reg.get("writable", False),
                    ))
            else:
                log.warning(f"RTU device {i}: profile '{dev.profile_file}' not found")

        devices.append(dev)

    return devices


class RTUPoller:
    """
    Polls multiple Modbus RTU devices on a single RS485 serial port.

    In DEV_MODE or when the serial port is unavailable, simulates
    all configured devices with realistic random values.
    """

    def __init__(self, config: dict):
        rs485 = config.get("rs485", {})
        self._enabled = rs485.get("mode") == "modbus_rtu"
        self._port = rs485.get("port", "/dev/ttyRS485")
        self._baud = rs485.get("baud", 9600)
        self._parity = rs485.get("parity", "N")
        self._stopbits = rs485.get("stopbits", 1)
        self._poll_interval = config.get("rtu_poll_interval_seconds", 10)

        self._devices = _load_rtu_devices(config) if self._enabled else []
        self._client = None
        self._running = False
        self._simulate = False
        self._lock = threading.RLock()
        self._sim_t = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def devices(self) -> list[RTUDevice]:
        with self._lock:
            return list(self._devices)

    def status(self) -> dict:
        """Return RTU poller status for /api/status."""
        if not self._enabled:
            return {"enabled": False, "device_count": 0}
        with self._lock:
            devs = []
            for d in self._devices:
                devs.append({
                    "address": d.address,
                    "profile": d.profile_name,
                    "points": len(d.points),
                    "connected": d.connected,
                    "poll_errors": d.poll_errors,
                })
            return {
                "enabled": True,
                "port": self._port,
                "baud": self._baud,
                "device_count": len(self._devices),
                "simulated": self._simulate,
                "devices": devs,
            }

    def _init_serial(self) -> bool:
        """Try to open the serial port via pymodbus."""
        if os.environ.get("DEV_MODE") == "1":
            log.info("RTU: DEV_MODE — simulating RTU devices")
            return False

        if not os.path.exists(self._port):
            log.warning(f"RTU: Serial port {self._port} not found — simulating")
            return False

        try:
            from pymodbus.client import ModbusSerialClient
            self._client = ModbusSerialClient(
                port=self._port,
                baudrate=self._baud,
                parity=self._parity,
                stopbits=self._stopbits,
                timeout=2,
            )
            if self._client.connect():
                log.info(f"RTU: Connected to {self._port} @ {self._baud} baud")
                return True
            else:
                log.warning(f"RTU: Failed to open {self._port} — simulating")
                return False
        except Exception as e:
            log.warning(f"RTU: Serial init error: {e} — simulating")
            return False

    def _read_device(self, dev: RTUDevice):
        """Read all registers from one RTU device."""
        import struct as _struct
        for pt in dev.points:
            try:
                count = 2 if pt.reg_type in ("INT32", "FLOAT") else 1
                if pt.function_code == 3:
                    result = self._client.read_holding_registers(
                        address=pt.address, count=count, slave=dev.address)
                else:
                    result = self._client.read_input_registers(
                        address=pt.address, count=count, slave=dev.address)

                if result.isError():
                    continue

                regs = result.registers
                if pt.reg_type == "INT32" and len(regs) >= 2:
                    raw = (regs[0] << 16) | regs[1]
                    if raw >= 0x80000000:
                        raw -= 0x100000000
                elif pt.reg_type == "FLOAT" and len(regs) >= 2:
                    raw = _struct.unpack('>f', _struct.pack('>HH', regs[0], regs[1]))[0]
                else:
                    raw = regs[0]
                    if raw >= 0x8000:
                        raw -= 0x10000

                pt.raw_value = raw
                pt.value = round(raw * pt.scale, 4)
                dev.connected = True

            except Exception:
                dev.poll_errors += 1

        dev.last_poll = time.time()

    def _simulate_device(self, dev: RTUDevice):
        """Generate realistic simulated values for one device."""
        t = self._sim_t
        for pt in dev.points:
            if pt.bacnet_type == "BI":
                pt.value = 1.0 if random.random() < 0.05 else 0.0
                pt.raw_value = int(pt.value)
            else:
                base = 100.0 + (pt.address % 50) * 5.0
                pt.raw_value = int(base + 20.0 * math.sin(t / 30.0 + pt.address))
                pt.value = round(pt.raw_value * pt.scale, 4)
        dev.connected = True
        dev.last_poll = time.time()

    def run(self):
        """Main loop — call in a dedicated thread."""
        if not self._enabled:
            log.info("RTU: disabled (rs485.mode is not modbus_rtu)")
            return

        if not self._devices:
            log.info("RTU: no devices configured in rtu_devices")
            return

        self._running = True
        hw_ok = self._init_serial()
        self._simulate = not hw_ok

        mode = "hardware" if hw_ok else "simulated"
        log.info(f"RTU: started ({mode}), {len(self._devices)} device(s), "
                 f"poll every {self._poll_interval}s")

        while self._running:
            with self._lock:
                for dev in self._devices:
                    if self._simulate:
                        self._simulate_device(dev)
                    else:
                        self._read_device(dev)

            self._sim_t += self._poll_interval
            time.sleep(self._poll_interval)

    def stop(self):
        self._running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        log.info("RTU: poller stopped")
