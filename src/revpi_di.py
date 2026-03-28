"""
SBS EnergyLink - RevPi DI Module Reader
Reads 14 digital inputs from the Revolution Pi DI expansion module
via revpimodio2 at /dev/piControl0.

Each input maps to a BACnet Binary Input (BI:7 through BI:20).
Input names, normal states, and alarm flags are configured in the
wizard and stored in config.yaml under di_inputs[].

In DEV_MODE (or when revpimodio2 is unavailable), simulates inputs
with random toggling for development without hardware.
"""

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# Number of physical channels on the RevPi DI module
NUM_CHANNELS = 14

# BACnet BI instance offset — DI channel 1 → BI:7, channel 14 → BI:20
BI_INSTANCE_OFFSET = 6


@dataclass
class DIInput:
    """Configuration and live state for one digital input channel."""
    channel: int                    # 1-14
    name: str = ""                  # BACnet object name (set in wizard)
    description: str = ""           # BACnet object description
    normal_state: str = "open"      # "open" or "closed"
    alarm_on_fault: bool = False    # raise alarm when input is in fault state
    enabled: bool = False           # only create BACnet object if True
    raw_value: bool = False         # current hardware state (True = energised)

    @property
    def bi_instance(self) -> int:
        """BACnet Binary Input instance number."""
        return self.channel + BI_INSTANCE_OFFSET

    @property
    def is_active(self) -> bool:
        """Logical state after applying normal_state inversion.

        For normally-open contacts: energised (True) = active
        For normally-closed contacts: de-energised (False) = active
        """
        if self.normal_state == "closed":
            return not self.raw_value
        return self.raw_value


def _load_di_config(config: dict) -> list[DIInput]:
    """Build DIInput list from config.yaml di_inputs section.

    Returns 14 DIInput objects. Channels not present in config are
    returned with enabled=False (no BACnet object created).
    """
    inputs = {ch: DIInput(channel=ch) for ch in range(1, NUM_CHANNELS + 1)}

    for entry in config.get("di_inputs", []):
        ch = entry.get("channel")
        if ch is None or ch < 1 or ch > NUM_CHANNELS:
            continue
        di = inputs[ch]
        di.name = entry.get("name", "")
        di.description = entry.get("description", "")
        di.normal_state = entry.get("normal_state", "open")
        di.alarm_on_fault = entry.get("alarm_on_fault", False)
        di.enabled = bool(di.name)  # enabled if name is set

    return [inputs[ch] for ch in range(1, NUM_CHANNELS + 1)]


class RevPiDIReader:
    """
    Reads the RevPi DI expansion module and exposes digital input
    states for the BACnet server.

    On real hardware, uses revpimodio2 to read /dev/piControl0.
    In DEV_MODE or when the library is unavailable, simulates with
    random toggling.
    """

    def __init__(self, config: dict):
        self._config = config
        self._inputs = _load_di_config(config)
        self._lock = threading.RLock()
        self._running = False
        self._simulate = False
        self._rpi: object = None  # revpimodio2.RevPiModIO instance
        self._poll_interval = config.get("di_poll_interval_seconds", 1)

    @property
    def inputs(self) -> list[DIInput]:
        """Return snapshot of all 14 DI inputs (thread-safe read)."""
        with self._lock:
            return list(self._inputs)

    def get_enabled_inputs(self) -> list[DIInput]:
        """Return only configured/enabled inputs."""
        with self._lock:
            return [di for di in self._inputs if di.enabled]

    def get_input(self, channel: int) -> Optional[DIInput]:
        """Return a single input by channel number (1-14)."""
        with self._lock:
            if 1 <= channel <= NUM_CHANNELS:
                return self._inputs[channel - 1]
            return None

    def _init_hardware(self) -> bool:
        """Try to initialise revpimodio2. Returns True on success."""
        if os.environ.get("DEV_MODE") == "1":
            log.info("DEV_MODE: RevPi DI will simulate inputs")
            return False

        try:
            import revpimodio2
            self._rpi = revpimodio2.RevPiModIO(autorefresh=True)
            self._rpi.handlesignalend()
            log.info("RevPi DI module initialised via revpimodio2")
            return True
        except ImportError:
            log.warning("revpimodio2 not installed — simulating DI inputs")
            return False
        except Exception as e:
            log.warning(f"Cannot open RevPi DI hardware: {e} — simulating")
            return False

    def _read_hardware(self):
        """Read all 14 channels from the real DI module."""
        for di in self._inputs:
            try:
                # RevPi DI input names are typically "I_1" through "I_14"
                io_name = f"I_{di.channel}"
                di.raw_value = bool(self._rpi.io[io_name].value)
            except (KeyError, AttributeError, Exception) as e:
                log.debug(f"Could not read DI channel {di.channel}: {e}")
                di.raw_value = False

    def _read_simulated(self):
        """Simulate DI inputs with random toggling (~10% chance per cycle)."""
        for di in self._inputs:
            if di.enabled and random.random() < 0.10:
                di.raw_value = not di.raw_value

    def run(self):
        """Main loop — call in a dedicated thread.

        Reads hardware (or simulates) every poll interval and updates
        input states under the lock.
        """
        self._running = True
        hw_ok = self._init_hardware()
        self._simulate = not hw_ok

        enabled = [di for di in self._inputs if di.enabled]
        if not enabled:
            log.info("No DI inputs configured — DI reader idle")

        mode = "hardware" if hw_ok else "simulated"
        log.info(f"RevPi DI reader started ({mode}), "
                 f"{len(enabled)}/{NUM_CHANNELS} inputs enabled, "
                 f"poll every {self._poll_interval}s")

        while self._running:
            with self._lock:
                if self._simulate:
                    self._read_simulated()
                else:
                    self._read_hardware()

            time.sleep(self._poll_interval)

    def stop(self):
        self._running = False
        if self._rpi is not None:
            try:
                self._rpi.cleanup()
            except Exception:
                pass
        log.info("RevPi DI reader stopped")
