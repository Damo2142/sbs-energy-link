"""
SBS EnergyLink - Main Entry Point
Starts all services in separate threads:
  - Modbus TCP poller (reads from EPMS/Tesla)
  - BACnet/IP server (presents data to BAS)
  - Commissioning web UI (setup & status)

Usage:
    python main.py
    python main.py --config /path/to/config.yaml
    python main.py --sim   (simulation mode, no real Modbus needed)
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time

import yaml

# Ensure src/ is on the path when running from project root
sys.path.insert(0, os.path.dirname(__file__))

from data_store import store
from poller import ModbusPoller
from bacnet_server import BACnetServer
from web_ui import run_webui

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
try:
    logging.getLogger().addHandler(logging.FileHandler("/var/log/sbs-energylink.log"))
except (PermissionError, OSError):
    pass
log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Simulation Mode (for development without real hardware)
# ---------------------------------------------------------------------------

def run_simulation(store):
    """
    Generates fake BESS data for development/testing.
    Run with:  python main.py --sim
    """
    import math
    from data_store import BESSData

    log.info("*** SIMULATION MODE — no real Modbus connection ***")
    t = 0
    while True:
        data = BESSData()
        data.application_version       = 1.0
        data.bess_capacity_kwh         = 3900.0
        data.bess_soc_pct              = 50.0 + 40.0 * math.sin(t / 60.0)
        data.bess_power_kw             = 500.0 * math.sin(t / 30.0)
        data.bess_power_setpoint_kw    = 500.0
        data.bess_max_charge_kw        = 1264.5
        data.bess_max_discharge_kw     = 1264.5
        data.bess_total_charged_kwh    = 10000.0 + t * 0.5
        data.bess_total_discharged_kwh = 9500.0 + t * 0.4
        data.grid_power_kw             = 200.0 + 100.0 * math.sin(t / 45.0)
        data.grid_energy_import_kwh    = 50000.0 + t * 0.2
        data.grid_energy_export_kwh    = 30000.0 + t * 0.1
        data.solar_power_kw            = max(0, 300.0 * math.sin(t / 50.0))
        data.solar_energy_produced_kwh = 15000.0 + t * 0.3
        data.load_power_kw             = 350.0 + 50.0 * math.sin(t / 20.0)
        data.load_energy_consumed_kwh  = 80000.0 + t * 0.35
        data.bess_error_present        = False
        data.bess_active_power_cmd_kw  = 0.0

        store.update(data)
        time.sleep(5)
        t += 5


# ---------------------------------------------------------------------------
# Config Loader
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        # Fall back to template
        template = config_path.replace("config.yaml", "config.template.yaml")
        if os.path.exists(template):
            log.warning(f"No config.yaml found, using template defaults")
            config_path = template
        else:
            log.error(f"No config file found at {config_path}")
            sys.exit(1)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    log.info(f"Config loaded from {config_path}")
    return cfg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SBS EnergyLink Integration Appliance")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml"),
        help="Path to config.yaml"
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Run in simulation mode (no real hardware needed)"
    )
    parser.add_argument(
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override web UI port (default: from config or 80)"
    )
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.loglevel))

    config = load_config(args.config)
    if args.port is not None:
        config["webui_port"] = args.port
    log.info(f"SBS EnergyLink starting — Site: {config.get('site_name', 'Unconfigured')}")

    threads = []

    # --- Modbus Poller (or Simulation) ---
    if args.sim:
        t = threading.Thread(
            target=run_simulation,
            args=(store,),
            name="simulator",
            daemon=True
        )
    else:
        poller = ModbusPoller(config, store)
        t = threading.Thread(
            target=poller.run,
            name="modbus-poller",
            daemon=True
        )
    threads.append(t)
    t.start()

    # --- BACnet Server ---
    bacnet = BACnetServer(config, store)
    t2 = threading.Thread(
        target=bacnet.run,
        name="bacnet-server",
        daemon=True
    )
    threads.append(t2)
    t2.start()

    # --- Commissioning Web UI ---
    t3 = threading.Thread(
        target=run_webui,
        args=(config,),
        name="web-ui",
        daemon=True
    )
    threads.append(t3)
    t3.start()

    # --- Graceful Shutdown ---
    def shutdown(sig, frame):
        log.info("Shutdown signal received")
        if not args.sim:
            poller.stop()
        bacnet.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("All services running. Press Ctrl+C to stop.")
    log.info(f"  Commissioning UI : http://{config['bacnet']['ip_address']}")
    log.info(f"  BACnet Device ID : {config['bacnet']['device_id']}")
    log.info(f"  Modbus Target    : {config['modbus']['host']}:{config['modbus'].get('port', 502)}")

    # Keep main thread alive
    while True:
        time.sleep(10)
        alive = [t.name for t in threads if t.is_alive()]
        log.debug(f"Active threads: {alive}")


if __name__ == "__main__":
    main()
