"""
SBS EnergyLink - BACnet MSTP Router Manager
Manages the bacnet-stack router-mstp process that bridges BACnet/IP
(eth1, network 1) to BACnet MSTP (RS485, network 2).

The router-mstp binary is a separate C process from Steve Karg's
bacnet-stack project. It handles MSTP token passing and serial I/O
on /dev/ttyRS485. Our Python bacpypes3 device on BACnet/IP becomes
discoverable from MSTP devices through the router — no external
hardware needed.

Architecture:
    MSTP device ──RS485──► router-mstp ──BACnet/IP──► bacpypes3 app
                           (C process)                (Python process)
    Network 2              routes between             Network 1
"""

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

ROUTER_BINARY = "router-mstp"
DEFAULT_SERIAL_PORT = "/dev/ttyRS485"
DEFAULT_BAUD = 38400
DEFAULT_MAC = 127
DEFAULT_MAX_MASTER = 127
DEFAULT_IP_NET = 1
DEFAULT_MSTP_NET = 2


class MSTProuter:
    """
    Manages the bacnet-stack router-mstp subprocess.

    Starts the router when MSTP is enabled in config, monitors the
    process, and restarts on unexpected exit. Provides status info
    for the /api/status endpoint.
    """

    def __init__(self, config: dict):
        mstp = config.get("mstp", {})
        self._enabled = mstp.get("enabled", False)
        self._serial_port = mstp.get("port", DEFAULT_SERIAL_PORT)
        self._baud = mstp.get("baud", DEFAULT_BAUD)
        self._mac = mstp.get("mac", DEFAULT_MAC)
        self._max_master = mstp.get("max_master", DEFAULT_MAX_MASTER)
        self._ip_interface = config.get("bacnet", {}).get("bind_interface", "eth1")
        self._ip_net = mstp.get("ip_network", DEFAULT_IP_NET)
        self._mstp_net = mstp.get("mstp_network", DEFAULT_MSTP_NET)

        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._lock = threading.Lock()
        self._started_ok = False
        self._last_error: Optional[str] = None
        self._restart_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def status(self) -> dict:
        """Return MSTP status dict for /api/status."""
        with self._lock:
            if not self._enabled:
                return {"enabled": False}

            alive = self._process is not None and self._process.poll() is None
            return {
                "enabled": True,
                "running": alive,
                "serial_port": self._serial_port,
                "baud": self._baud,
                "mac": self._mac,
                "max_master": self._max_master,
                "ip_network": self._ip_net,
                "mstp_network": self._mstp_net,
                "serial_port_exists": os.path.exists(self._serial_port),
                "binary_installed": shutil.which(ROUTER_BINARY) is not None,
                "restart_count": self._restart_count,
                "last_error": self._last_error,
            }

    def _find_binary(self) -> Optional[str]:
        """Locate the router-mstp binary."""
        # Check PATH first
        path = shutil.which(ROUTER_BINARY)
        if path:
            return path
        # Check common install locations
        for candidate in ["/usr/local/bin/router-mstp", "/usr/bin/router-mstp"]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def _build_env(self) -> dict:
        """Build environment variables for the router-mstp process."""
        env = os.environ.copy()
        env["BACNET_IFACE"] = self._ip_interface
        env["BACNET_IP_PORT"] = "47808"
        env["BACNET_IP_NET"] = str(self._ip_net)
        env["BACNET_MSTP_IFACE"] = self._serial_port
        env["BACNET_MSTP_BAUD"] = str(self._baud)
        env["BACNET_MSTP_MAC"] = str(self._mac)
        env["BACNET_MSTP_NET"] = str(self._mstp_net)
        env["BACNET_MAX_MASTER"] = str(self._max_master)
        env["BACNET_MAX_INFO_FRAMES"] = "128"
        return env

    def _start_process(self) -> bool:
        """Start the router-mstp subprocess. Returns True on success."""
        binary = self._find_binary()
        if not binary:
            self._last_error = (
                f"router-mstp binary not found. "
                f"Run: sudo bash scripts/build_mstp_router.sh"
            )
            log.error(f"MSTP: {self._last_error}")
            return False

        if not os.path.exists(self._serial_port):
            self._last_error = f"Serial port {self._serial_port} does not exist"
            log.error(f"MSTP: {self._last_error}")
            return False

        try:
            env = self._build_env()
            log.info(
                f"MSTP: Starting router-mstp — "
                f"{self._serial_port} @ {self._baud} baud, MAC {self._mac}, "
                f"IP net {self._ip_net} ↔ MSTP net {self._mstp_net}"
            )
            self._process = subprocess.Popen(
                [binary],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            # Give it a moment to either crash or start
            time.sleep(1)
            if self._process.poll() is not None:
                output = self._process.stdout.read() if self._process.stdout else ""
                self._last_error = f"router-mstp exited immediately: {output.strip()}"
                log.error(f"MSTP: {self._last_error}")
                self._process = None
                return False

            self._started_ok = True
            self._last_error = None
            log.info(f"MSTP: router-mstp started (PID {self._process.pid})")
            return True

        except Exception as e:
            self._last_error = str(e)
            log.error(f"MSTP: Failed to start router-mstp: {e}")
            return False

    def run(self):
        """Main loop — call in a dedicated thread.

        Starts the router-mstp process and monitors it, restarting
        on unexpected exit with exponential backoff.
        """
        if not self._enabled:
            log.info("MSTP: disabled in config, router not started")
            return

        if os.environ.get("DEV_MODE") == "1":
            log.info(
                "MSTP: DEV_MODE active — RS485 router requires RevPi hardware. "
                "MSTP routing disabled for this session."
            )
            return

        self._running = True
        backoff = 5  # seconds, increases on repeated failures

        while self._running:
            if not self._start_process():
                log.warning(f"MSTP: Retry in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
                continue

            # Reset backoff on successful start
            backoff = 5

            # Monitor the process
            while self._running:
                retcode = self._process.poll()
                if retcode is not None:
                    # Process exited
                    output = ""
                    if self._process.stdout:
                        output = self._process.stdout.read()
                    self._last_error = (
                        f"router-mstp exited with code {retcode}: "
                        f"{output.strip()[-200:]}"
                    )
                    log.warning(f"MSTP: {self._last_error}")
                    self._process = None
                    self._restart_count += 1
                    break
                time.sleep(2)

            if self._running:
                log.info(f"MSTP: Restarting router-mstp in {backoff}s "
                         f"(restart #{self._restart_count})...")
                time.sleep(backoff)

    def stop(self):
        """Stop the router-mstp process."""
        self._running = False
        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except Exception:
                    pass
                finally:
                    self._process = None
        log.info("MSTP: router stopped")
