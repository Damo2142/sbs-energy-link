"""
SBS EnergyLink - BACnet/IP Server
Presents all BESS data points as a native BACnet device on the network.
Uses bacpypes3 library. Binds ONLY to eth1 (JACE-side interface).

BACnet Object List:
  AI:1  - AI:16   Analog Input points (read-only)
  BI:1  - BI:6    Binary Input points (fault flags)
  AV:1            Analog Value (BESS Active Power Command - writable)
"""

import argparse
import asyncio
import logging
import os
import socket
import time
from typing import Optional

from bacpypes3.app import Application
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject

from data_store import DataStore
from revpi_di import RevPiDIReader

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BACnet Object Definitions
# ---------------------------------------------------------------------------

ANALOG_INPUTS = [
    # (instance, name, units, description)
    (1,  "App_Version",               "noUnits",          "Application Version"),
    (2,  "BESS_Capacity_kWh",         "kilowattHours",    "BESS Total Nominal Capacity"),
    (3,  "BESS_Power_kW",             "kilowatts",        "Total Power from BESS"),
    (4,  "BESS_Power_Setpoint_kW",    "kilowatts",        "Active Power Commanded to All BESS"),
    (5,  "BESS_Max_Charge_kW",        "kilowatts",        "BESS Maximum Charge Power"),
    (6,  "BESS_Max_Discharge_kW",     "kilowatts",        "BESS Maximum Discharge Power"),
    (7,  "BESS_SOC_Pct",              "percent",          "BESS State of Charge - Weighted Average"),
    (8,  "BESS_Total_Charged_kWh",    "kilowattHours",    "BESS Total Energy Charged"),
    (9,  "BESS_Total_Discharged_kWh", "kilowattHours",    "BESS Total Energy Discharged"),
    (10, "Grid_Power_kW",             "kilowatts",        "Grid Power"),
    (11, "Grid_Energy_Import_kWh",    "kilowattHours",    "Grid Energy Import"),
    (12, "Grid_Energy_Export_kWh",     "kilowattHours",    "Grid Energy Export"),
    (13, "Solar_Power_kW",            "kilowatts",        "Solar Power"),
    (14, "Solar_Energy_Produced_kWh", "kilowattHours",    "Solar Energy Produced"),
    (15, "Load_Power_kW",             "kilowatts",        "Load Power"),
    (16, "Load_Energy_Consumed_kWh",  "kilowattHours",    "Load Energy Consumed"),
]

BINARY_INPUTS = [
    # (instance, name, active_text, inactive_text, description)
    (1, "BESS_Error_Present",    "ERROR",    "OK",      "BESS Error Present"),
    (2, "BESS_Comm_Error",       "FAULT",    "NORMAL",  "BESS Communication Error"),
    (3, "BESS_Low_Cell_Voltage", "FAULT",    "NORMAL",  "BESS Low Cell Voltage"),
    (4, "BESS_High_Cell_Voltage","FAULT",    "NORMAL",  "BESS High Cell Voltage"),
    (5, "BESS_Low_Temp_Error",   "FAULT",    "NORMAL",  "BESS Low Temperature Error"),
    (6, "BESS_High_Temp_Error",  "FAULT",    "NORMAL",  "BESS High Temperature Error"),
]

ANALOG_VALUES = [
    # (instance, name, units, description, writable)
    (1, "BESS_Active_Power_Cmd_kW", "kilowatts",
     "Active Power Commanded to EMS", True),
]


class BACnetServer:
    """
    BACnet/IP server that presents BESS data as native BACnet objects.
    Reads from DataStore and updates present values on each refresh cycle.

    Uses bacpypes3 (asyncio-based). The run() method creates its own
    asyncio event loop in the calling thread.
    """

    def __init__(self, config: dict, store: DataStore,
                 di_reader: Optional[RevPiDIReader] = None):
        self.config = config
        self.store = store
        self.di_reader = di_reader
        self.device_id = config["bacnet"]["device_id"]
        self.device_name = config["bacnet"]["device_name"]
        self.interface = config["bacnet"].get("bind_interface", "eth1")
        self.ip_address, self.network_mask = self._resolve_bind_address(config)
        self.refresh_interval = config.get("bacnet_refresh_seconds", 15)
        self._app: Optional[Application] = None
        self._ai_objects: dict[int, AnalogInputObject] = {}
        self._bi_objects: dict[int, BinaryInputObject] = {}
        self._av_objects: dict[int, AnalogValueObject] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @staticmethod
    def _resolve_bind_address(config: dict) -> tuple[str, str]:
        """Resolve the BACnet bind address and network mask.

        Production: uses config ip_address/network_mask (10.10.10.1/30).
        DEV_MODE=1: detects the machine's default IP and subnet mask
        so BACnet broadcasts reach the correct LAN broadcast address.
        """
        cfg_ip = config["bacnet"].get("ip_address", "10.10.10.1")
        cfg_mask = config["bacnet"].get("network_mask", "24")

        if os.environ.get("DEV_MODE") != "1":
            return cfg_ip, cfg_mask

        # Check if the configured IP is actually available
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((cfg_ip, 0))
            s.close()
            return cfg_ip, cfg_mask
        except OSError:
            pass

        # Fall back to the machine's default-route IP and detect its mask
        try:
            import fcntl
            import struct

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()

            # Detect the subnet mask from the interface
            mask = "24"  # safe default
            try:
                import subprocess
                result = subprocess.run(
                    ["ip", "-o", "-4", "addr", "show"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if ip in line:
                        # Format: "2: eth0  inet 192.168.0.26/24 ..."
                        addr_part = line.split("inet ")[1].split()[0]
                        mask = addr_part.split("/")[1]
                        break
            except Exception:
                pass

            log.info(f"DEV_MODE: BACnet binding to {ip}/{mask} "
                     f"instead of {cfg_ip}/{cfg_mask}")
            return ip, mask
        except OSError:
            log.warning(f"DEV_MODE: cannot detect local IP, "
                        f"using {cfg_ip}/{cfg_mask}")
            return cfg_ip, cfg_mask

    async def _start_bacnet(self):
        """Initialize bacpypes3 application and create all BACnet objects."""
        log.info(f"Starting BACnet/IP server — Device ID: {self.device_id} "
                 f"on {self.ip_address}/{self.network_mask}")

        args = argparse.Namespace(
            name=self.device_name,
            instance=self.device_id,
            address=f"{self.ip_address}/{self.network_mask}",
            network=0,
            vendoridentifier=999,
            modelname="SBS-EnergyLink-1",
            vendorname="SBS Controls",
            foreign=None,
            ttl=None,
            bbmd=None,
        )
        self._app = Application.from_args(args)

        # Create Analog Inputs
        for instance, name, units, description in ANALOG_INPUTS:
            obj = AnalogInputObject(
                objectIdentifier=("analogInput", instance),
                objectName=name,
                description=description,
                presentValue=0.0,
                units=units,
            )
            self._app.add_object(obj)
            self._ai_objects[instance] = obj
            log.debug(f"Created AI:{instance} {name}")

        # Create Binary Inputs
        for instance, name, active, inactive, description in BINARY_INPUTS:
            obj = BinaryInputObject(
                objectIdentifier=("binaryInput", instance),
                objectName=name,
                description=description,
                presentValue="inactive",
                activeText=active,
                inactiveText=inactive,
            )
            self._app.add_object(obj)
            self._bi_objects[instance] = obj
            log.debug(f"Created BI:{instance} {name}")

        # Create Binary Inputs for RevPi DI channels (BI:7 - BI:20)
        di_count = 0
        if self.di_reader:
            for di in self.di_reader.get_enabled_inputs():
                obj = BinaryInputObject(
                    objectIdentifier=("binaryInput", di.bi_instance),
                    objectName=di.name,
                    description=di.description,
                    presentValue="inactive",
                    activeText="ACTIVE",
                    inactiveText="NORMAL",
                )
                self._app.add_object(obj)
                self._bi_objects[di.bi_instance] = obj
                di_count += 1
                log.debug(f"Created BI:{di.bi_instance} {di.name} (DI ch{di.channel})")
            if di_count:
                log.info(f"Created {di_count} DI-sourced Binary Inputs (BI:7-BI:20)")

        # Create Analog Values (writable)
        for instance, name, units, description, writable in ANALOG_VALUES:
            obj = AnalogValueObject(
                objectIdentifier=("analogValue", instance),
                objectName=name,
                description=description,
                presentValue=0.0,
                units=units,
            )
            self._app.add_object(obj)
            self._av_objects[instance] = obj
            log.debug(f"Created AV:{instance} {name}")

        log.info(f"BACnet server ready — {len(ANALOG_INPUTS)} AI, "
                 f"{len(BINARY_INPUTS) + di_count} BI "
                 f"({len(BINARY_INPUTS)} BESS + {di_count} DI), "
                 f"{len(ANALOG_VALUES)} AV")

    def _update_points(self):
        """Push current DataStore values into BACnet present values."""
        data = self.store.get()
        stale = self.store.is_stale(
            self.config.get("stale_data_timeout_seconds", 120)
        )

        try:
            # Analog Inputs
            self._ai_objects[1].presentValue  = data.application_version
            self._ai_objects[2].presentValue  = data.bess_capacity_kwh
            self._ai_objects[3].presentValue  = data.bess_power_kw
            self._ai_objects[4].presentValue  = data.bess_power_setpoint_kw
            self._ai_objects[5].presentValue  = data.bess_max_charge_kw
            self._ai_objects[6].presentValue  = data.bess_max_discharge_kw
            self._ai_objects[7].presentValue  = data.bess_soc_pct
            self._ai_objects[8].presentValue  = data.bess_total_charged_kwh
            self._ai_objects[9].presentValue  = data.bess_total_discharged_kwh
            self._ai_objects[10].presentValue = data.grid_power_kw
            self._ai_objects[11].presentValue = data.grid_energy_import_kwh
            self._ai_objects[12].presentValue = data.grid_energy_export_kwh
            self._ai_objects[13].presentValue = data.solar_power_kw
            self._ai_objects[14].presentValue = data.solar_energy_produced_kwh
            self._ai_objects[15].presentValue = data.load_power_kw
            self._ai_objects[16].presentValue = data.load_energy_consumed_kwh

            # Binary Inputs (fault flags)
            self._bi_objects[1].presentValue = "active" if data.bess_error_present else "inactive"
            self._bi_objects[2].presentValue = "active" if data.bess_comm_error else "inactive"
            self._bi_objects[3].presentValue = "active" if data.bess_low_cell_voltage else "inactive"
            self._bi_objects[4].presentValue = "active" if data.bess_high_cell_voltage else "inactive"
            self._bi_objects[5].presentValue = "active" if data.bess_low_temp_error else "inactive"
            self._bi_objects[6].presentValue = "active" if data.bess_high_temp_error else "inactive"

            # Analog Value (writable command point)
            self._av_objects[1].presentValue = data.bess_active_power_cmd_kw

            # DI-sourced Binary Inputs (BI:7 - BI:20)
            if self.di_reader:
                for di in self.di_reader.get_enabled_inputs():
                    bi = self._bi_objects.get(di.bi_instance)
                    if bi is not None:
                        bi.presentValue = "active" if di.is_active else "inactive"

            if stale:
                log.warning("BACnet update with STALE data")

        except Exception as e:
            log.error(f"Error updating BACnet points: {e}")

    def get_power_cmd_from_bacnet(self) -> Optional[float]:
        """
        Read the current BACnet write to AV:1 (if operator wrote a value).
        Used by main loop to forward writes back to Modbus.
        """
        try:
            return float(self._av_objects[1].presentValue)
        except Exception:
            return None

    async def _run_async(self):
        """Async main loop: start BACnet, then periodically update points."""
        await self._start_bacnet()

        while self._running:
            self._update_points()
            await asyncio.sleep(self.refresh_interval)

    def run(self):
        """Main BACnet server entry point. Creates an asyncio event loop."""
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            log.error(f"BACnet server error: {e}")
        finally:
            self._loop.close()

    def stop(self):
        self._running = False
        if self._app:
            try:
                self._app.close()
            except Exception:
                pass
        log.info("BACnet server stopped")
