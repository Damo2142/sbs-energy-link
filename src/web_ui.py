"""
SBS EnergyLink - Web UI
5-step setup wizard and read-only live data dashboard.
No JACE — EnergyLink handles all networking directly.
"""

import ipaddress
import json
import logging
import os
import subprocess
import time as _time

import yaml
from flask import Flask, render_template, request, jsonify, redirect, url_for

from license import load_license
from profiles import list_profiles, load_profile

log = logging.getLogger(__name__)

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SRC_DIR)

app = Flask(
    __name__,
    template_folder=os.path.join(_PROJECT_DIR, "templates"),
)
CONFIG_PATH = os.path.join(_PROJECT_DIR, "config", "config.yaml")
TEMPLATE_PATH = os.path.join(_PROJECT_DIR, "config", "config.template.yaml")

_license = load_license()


def _dev_mode() -> bool:
    return os.environ.get("DEV_MODE") == "1"


def load_config() -> dict:
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else TEMPLATE_PATH
    with open(path) as f:
        return yaml.safe_load(f)


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)


def _get_mstp_status() -> dict:
    """Get MSTP router status from the MSTProuter instance."""
    router = app.config.get("mstp_router")
    if router is None:
        return {"enabled": False}
    return router.status()


def _mask_to_prefix(mask: str) -> int:
    """Convert subnet mask like 255.255.255.0 to prefix length like 24."""
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return 24


# ---------------------------------------------------------------------------
# Routes — Wizard
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/step1", methods=["GET", "POST"])
def step1():
    cfg = load_config()
    if request.method == "POST":
        cfg["site_name"] = request.form.get("site_name", "").strip()
        cfg["unit_id_label"] = request.form.get("unit_id_label", "").strip()
        cfg["engineer_name"] = request.form.get("engineer_name", "").strip()
        cfg["install_date"] = request.form.get("install_date", "").strip()
        save_config(cfg)
        return redirect(url_for("step2"))
    return render_template("step1.html", cfg=cfg)


@app.route("/step2", methods=["GET", "POST"])
def step2():
    cfg = load_config()
    if request.method == "POST":
        # EPMS / Modbus
        cfg.setdefault("modbus", {})
        cfg["modbus"]["host"] = request.form.get("modbus_host", "").strip()
        cfg["modbus"]["port"] = int(request.form.get("modbus_port", 502))
        cfg["modbus"]["unit_id"] = int(request.form.get("modbus_unit_id", 1))
        cfg["poll_interval_seconds"] = int(request.form.get("poll_interval", 30))
        # eth0 network
        cfg.setdefault("eth0", {})
        cfg["eth0"]["mode"] = request.form.get("eth0_mode", "dhcp")
        cfg["eth0"]["ip_address"] = request.form.get("eth0_ip", "").strip()
        cfg["eth0"]["subnet_mask"] = request.form.get("eth0_mask", "255.255.255.0").strip()
        cfg["eth0"]["gateway"] = request.form.get("eth0_gateway", "").strip()
        save_config(cfg)
        return redirect(url_for("step3"))
    return render_template("step2.html", cfg=cfg)


@app.route("/step3", methods=["GET", "POST"])
def step3():
    cfg = load_config()
    if request.method == "POST":
        # eth1 network
        cfg.setdefault("eth1", {})
        eth1_ip = request.form.get("eth1_ip", "").strip()
        cfg["eth1"]["ip_address"] = eth1_ip
        cfg["eth1"]["subnet_mask"] = request.form.get("eth1_mask", "255.255.255.0").strip()
        cfg["eth1"]["gateway"] = request.form.get("eth1_gateway", "").strip()
        cfg["eth1"]["dns"] = request.form.get("eth1_dns", "").strip()
        # BACnet — ip_address mirrors eth1
        cfg.setdefault("bacnet", {})
        cfg["bacnet"]["device_id"] = int(request.form.get("bacnet_device_id", 9001))
        cfg["bacnet"]["device_name"] = request.form.get("bacnet_device_name", "").strip()
        cfg["bacnet"]["ip_address"] = eth1_ip
        prefix = _mask_to_prefix(cfg["eth1"]["subnet_mask"])
        cfg["bacnet"]["network_mask"] = str(prefix)
        cfg["bacnet"]["bind_interface"] = "eth1"
        # DI inputs (14 channels)
        di_inputs = []
        for ch in range(1, 15):
            enabled = request.form.get(f"di_{ch}_enabled") == "on"
            name = request.form.get(f"di_{ch}_name", "").strip()
            if enabled and name:
                di_inputs.append({
                    "channel": ch,
                    "name": name,
                    "description": request.form.get(f"di_{ch}_desc", "").strip(),
                    "normal_state": request.form.get(f"di_{ch}_state", "open"),
                    "alarm_on_fault": request.form.get(f"di_{ch}_alarm") == "on",
                })
        cfg["di_inputs"] = di_inputs
        # MSTP settings
        cfg.setdefault("mstp", {})
        cfg["mstp"]["enabled"] = request.form.get("mstp_enabled") == "on"
        cfg["mstp"]["mac"] = int(request.form.get("mstp_mac", 127))
        cfg["mstp"]["baud"] = int(request.form.get("mstp_baud", 38400))
        cfg["mstp"]["mstp_network"] = int(request.form.get("mstp_network", 2))
        cfg["mstp"]["port"] = "/dev/ttyRS485"
        cfg["mstp"]["max_master"] = 127
        cfg["mstp"]["ip_network"] = 1
        save_config(cfg)
        return redirect(url_for("step4"))
    # GET — pass license and DI reader for template
    di_reader = app.config.get("di_reader")
    return render_template("step3.html", cfg=cfg, lic=_license,
                           dev_mode=_dev_mode(), di_reader=di_reader)


@app.route("/step4")
def step4():
    cfg = load_config()
    return render_template("step4.html", cfg=cfg)


@app.route("/step5")
def step5():
    cfg = load_config()
    return render_template("step5.html", cfg=cfg)


@app.route("/dashboard")
def dashboard():
    cfg = load_config()
    return render_template("dashboard.html", cfg=cfg)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/live_data")
def api_live_data():
    from data_store import store
    data = store.get()
    stale = store.is_stale(120)
    last = data.last_update
    return jsonify({
        "connection": {
            "epms_connected": data.poll_success,
            "bacnet_active": True,
            "last_poll_time": last if last > 0 else None,
            "last_poll_ago_s": round(_time.time() - last, 1) if last > 0 else None,
            "data_stale": stale,
        },
        "energy_flow": {
            "grid_power_kw": round(data.grid_power_kw, 1),
            "grid_energy_import_kwh": round(data.grid_energy_import_kwh, 1),
            "grid_energy_export_kwh": round(data.grid_energy_export_kwh, 1),
            "solar_power_kw": round(data.solar_power_kw, 1),
            "solar_energy_produced_kwh": round(data.solar_energy_produced_kwh, 1),
            "load_power_kw": round(data.load_power_kw, 1),
            "load_energy_consumed_kwh": round(data.load_energy_consumed_kwh, 1),
        },
        "battery": {
            "bess_soc_pct": round(data.bess_soc_pct, 1),
            "bess_power_kw": round(data.bess_power_kw, 1),
            "bess_power_setpoint_kw": round(data.bess_power_setpoint_kw, 1),
            "bess_capacity_kwh": round(data.bess_capacity_kwh, 1),
            "bess_max_charge_kw": round(data.bess_max_charge_kw, 1),
            "bess_max_discharge_kw": round(data.bess_max_discharge_kw, 1),
            "bess_total_charged_kwh": round(data.bess_total_charged_kwh, 1),
            "bess_total_discharged_kwh": round(data.bess_total_discharged_kwh, 1),
            "application_version": data.application_version,
        },
        "faults": {
            "bess_error_present": data.bess_error_present,
            "bess_comm_error": data.bess_comm_error,
            "bess_low_cell_voltage": data.bess_low_cell_voltage,
            "bess_high_cell_voltage": data.bess_high_cell_voltage,
            "bess_low_temp_error": data.bess_low_temp_error,
            "bess_high_temp_error": data.bess_high_temp_error,
        },
        "control": {
            "bess_active_power_cmd_kw": round(data.bess_active_power_cmd_kw, 1),
        },
    })


@app.route("/api/test_modbus")
def test_modbus():
    cfg = load_config()
    host = cfg.get("modbus", {}).get("host", "")
    port = cfg.get("modbus", {}).get("port", 502)
    if not host:
        return jsonify({"ok": False, "error": "No host configured"})
    if _dev_mode():
        return jsonify({"ok": True, "host": host, "port": port, "dev_mode": True})
    try:
        from pymodbus.client import ModbusTcpClient
        c = ModbusTcpClient(host=host, port=port, timeout=5)
        ok = c.connect()
        c.close()
        return jsonify({"ok": ok, "host": host, "port": port})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/bacnet_test")
def bacnet_test():
    """Check if bacpypes3 is bound and listening on the configured address."""
    import socket
    cfg = load_config()
    bacnet_ip = cfg.get("bacnet", {}).get("ip_address", "")
    if _dev_mode():
        # In dev mode, check if anything is listening on 47808
        try:
            r = subprocess.run(
                ["ss", "-uln"], capture_output=True, text=True, timeout=5,
            )
            listening = "47808" in r.stdout
            return jsonify({
                "ok": listening,
                "ip": bacnet_ip,
                "port": 47808,
                "dev_mode": True,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    # Production: try to bind a test socket — if it fails, bacpypes3 has the port
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((bacnet_ip, 47808))
        s.close()
        # If we CAN bind, bacpypes3 is NOT running
        return jsonify({"ok": False, "ip": bacnet_ip, "port": 47808,
                        "error": "BACnet server not listening"})
    except OSError:
        # Can't bind = port in use = bacpypes3 is running
        return jsonify({"ok": True, "ip": bacnet_ip, "port": 47808})


@app.route("/api/apply_network", methods=["POST"])
def apply_network():
    """Write netplan config and apply. In DEV_MODE, validate only."""
    cfg = load_config()
    eth0 = cfg.get("eth0", {})
    eth1 = cfg.get("eth1", {})

    # Validate
    errors = []
    if eth1.get("ip_address"):
        try:
            ipaddress.IPv4Address(eth1["ip_address"])
        except ValueError:
            errors.append(f"eth1 IP '{eth1['ip_address']}' is not valid")
    else:
        errors.append("eth1 IP address is required")

    if eth0.get("mode") == "static":
        if not eth0.get("ip_address"):
            errors.append("eth0 static IP address is required")
        else:
            try:
                ipaddress.IPv4Address(eth0["ip_address"])
            except ValueError:
                errors.append(f"eth0 IP '{eth0['ip_address']}' is not valid")

    if errors:
        return jsonify({"ok": False, "errors": errors})

    if _dev_mode():
        # Run dev_network_setup.sh so BACnet actually rebinds — full
        # end-to-end apply flow identical to production.
        dev_script = os.path.join(_PROJECT_DIR, "tools", "dev_network_setup.sh")
        if os.path.isfile(dev_script):
            try:
                r = subprocess.run(
                    ["bash", dev_script],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode != 0:
                    log.warning("dev_network_setup.sh failed: %s", r.stderr)
                    return jsonify({"ok": False, "dev_mode": True,
                                    "error": f"dev_network_setup.sh failed: {r.stderr}"})
                log.info("DEV_MODE: dev_network_setup.sh completed:\n%s", r.stdout)
                return jsonify({"ok": True, "dev_mode": True,
                                "message": "DEV_MODE: alias IP applied via dev_network_setup.sh",
                                "output": r.stdout})
            except Exception as e:
                log.warning("dev_network_setup.sh error: %s", e)
                return jsonify({"ok": False, "dev_mode": True, "error": str(e)})
        else:
            log.warning("DEV_MODE: tools/dev_network_setup.sh not found, skipping")
            return jsonify({"ok": True, "dev_mode": True,
                            "message": "DEV_MODE: config validated, netplan not applied (dev script not found)"})

    # Build netplan YAML
    eth0_prefix = _mask_to_prefix(eth0.get("subnet_mask", "255.255.255.0"))
    eth1_prefix = _mask_to_prefix(eth1.get("subnet_mask", "255.255.255.0"))

    netplan = {"network": {"version": 2, "ethernets": {}}}

    if eth0.get("mode") == "dhcp":
        netplan["network"]["ethernets"]["eth0"] = {"dhcp4": True}
    else:
        eth0_cfg = {
            "dhcp4": False,
            "addresses": [f"{eth0['ip_address']}/{eth0_prefix}"],
        }
        if eth0.get("gateway"):
            eth0_cfg["routes"] = [{"to": "default", "via": eth0["gateway"]}]
        netplan["network"]["ethernets"]["eth0"] = eth0_cfg

    eth1_cfg = {
        "dhcp4": False,
        "addresses": [f"{eth1['ip_address']}/{eth1_prefix}"],
    }
    if eth1.get("gateway"):
        eth1_cfg["routes"] = [{"to": "default", "via": eth1["gateway"], "metric": 200}]
    if eth1.get("dns"):
        eth1_cfg["nameservers"] = {"addresses": [eth1["dns"]]}
    netplan["network"]["ethernets"]["eth1"] = eth1_cfg

    # Write and apply
    netplan_path = "/etc/netplan/01-sbs-energylink.yaml"
    try:
        with open(netplan_path, "w") as f:
            yaml.dump(netplan, f, default_flow_style=False)
        r = subprocess.run(
            ["netplan", "apply"], capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return jsonify({"ok": False, "error": f"netplan apply failed: {r.stderr}"})
        return jsonify({"ok": True, "message": "Network configuration applied"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/status")
def api_status():
    import socket
    from data_store import store
    cfg = load_config()
    data = store.get()

    # Detect current interface IPs
    eth0_ip = _get_interface_ip("eth0")
    eth1_ip = _get_interface_ip("eth1")

    return jsonify({
        "configured": bool(cfg.get("site_name") and
                          cfg.get("site_name") != "Unconfigured Site"),
        "site_name": cfg.get("site_name", ""),
        "unit_id": cfg.get("unit_id_label", ""),
        "eth0_ip": eth0_ip,
        "eth1_ip": eth1_ip,
        "epms_host": cfg.get("modbus", {}).get("host", ""),
        "epms_connected": data.poll_success,
        "bacnet_device_id": cfg.get("bacnet", {}).get("device_id", 9001),
        "bacnet_ip": cfg.get("bacnet", {}).get("ip_address", ""),
        "data_stale": store.is_stale(),
        "dev_mode": _dev_mode(),
        "mstp": _get_mstp_status(),
        "license": {
            "part_number": _license.product,
            "serial_number": _license.serial,
            "tier": _license.tier,
            "tier_name": _license.tier_name,
            "valid": _license.valid,
        },
        "di_hardware": {
            "expected": True,
            "present": os.path.exists("/dev/piControl0"),
            "warning": None if os.path.exists("/dev/piControl0") or _dev_mode()
                       else "/dev/piControl0 not found — DI board missing or not detected",
        },
    })


@app.route("/api/confirm_status")
def confirm_status():
    """Step 4 uses this to poll both-sides status."""
    from data_store import store
    cfg = load_config()
    data = store.get()
    stale = store.is_stale(120)
    last = data.last_update

    return jsonify({
        "eth0": {
            "ip": _get_interface_ip("eth0"),
            "epms_connected": data.poll_success,
            "last_poll_time": last if last > 0 else None,
            "last_poll_ago_s": round(_time.time() - last, 1) if last > 0 else None,
        },
        "eth1": {
            "ip": _get_interface_ip("eth1"),
            "bacnet_ip": cfg.get("bacnet", {}).get("ip_address", ""),
            "bacnet_device_id": cfg.get("bacnet", {}).get("device_id", 9001),
            "bacnet_active": _bacnet_is_listening(),
        },
        "sample": {
            "bess_soc_pct": round(data.bess_soc_pct, 1),
            "bess_power_kw": round(data.bess_power_kw, 1),
            "grid_power_kw": round(data.grid_power_kw, 1),
            "solar_power_kw": round(data.solar_power_kw, 1),
            "load_power_kw": round(data.load_power_kw, 1),
        },
        "data_stale": stale,
        "all_ok": data.poll_success and _bacnet_is_listening() and not stale,
    })


@app.route("/api/profiles")
def api_profiles():
    """List available device profiles (Universal/Pro tiers)."""
    return jsonify({"profiles": list_profiles(), "tier": _license.tier})


@app.route("/api/profile/<filename>")
def api_profile(filename):
    """Load a specific device profile."""
    profile = load_profile(filename)
    if profile is None:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    return jsonify({"ok": True, "profile": profile})


@app.route("/api/test_register", methods=["POST"])
def api_test_register():
    """Read a single Modbus register live from the connected device.

    Available in Universal and Pro tiers. Request body:
    {"address": 200, "type": "INT16", "function_code": 4,
     "scale": 1.0, "count": 1}
    """
    if not _license.is_universal_or_pro:
        return jsonify({"ok": False, "error": "Requires Universal or Pro tier"})

    data = request.get_json(silent=True) or {}
    address = data.get("address")
    reg_type = data.get("type", "INT16")
    fc = data.get("function_code", 4)
    scale = float(data.get("scale", 1.0))

    if address is None:
        return jsonify({"ok": False, "error": "address is required"})

    cfg = load_config()
    host = cfg.get("modbus", {}).get("host", "")
    port = cfg.get("modbus", {}).get("port", 502)
    unit_id = cfg.get("modbus", {}).get("unit_id", 1)

    if _dev_mode():
        import random
        raw = random.randint(0, 65535)
        scaled = round(raw * scale, 2)
        return jsonify({"ok": True, "address": address, "raw": raw,
                        "scaled": scaled, "dev_mode": True})

    try:
        from pymodbus.client import ModbusTcpClient
        import struct
        c = ModbusTcpClient(host=host, port=port, timeout=5)
        if not c.connect():
            return jsonify({"ok": False, "error": f"Cannot connect to {host}:{port}"})

        count = 2 if reg_type in ("INT32", "FLOAT") else 1
        if fc == 3:
            result = c.read_holding_registers(address=int(address), count=count, slave=unit_id)
        else:
            result = c.read_input_registers(address=int(address), count=count, slave=unit_id)
        c.close()

        if result.isError():
            return jsonify({"ok": False, "error": f"Modbus error: {result}"})

        regs = result.registers
        if reg_type == "INT32" and len(regs) >= 2:
            raw = (regs[0] << 16) | regs[1]
            if raw >= 0x80000000:
                raw -= 0x100000000
        elif reg_type == "FLOAT" and len(regs) >= 2:
            raw = struct.unpack('>f', struct.pack('>HH', regs[0], regs[1]))[0]
        else:
            raw = regs[0]
            if raw >= 0x8000:
                raw -= 0x10000

        scaled = round(raw * scale, 4)
        return jsonify({"ok": True, "address": address, "raw": raw,
                        "scaled": scaled, "registers": regs})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/import_registers", methods=["POST"])
def api_import_registers():
    """Import registers from Excel (.xlsx) or CSV file (Pro tier only).

    Step 1 (detect): Upload file, returns detected columns.
    Step 2 (confirm): Send column mapping, imports all rows.
    """
    if not _license.is_pro:
        return jsonify({"ok": False, "error": "Requires Pro tier"})

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"})

    f = request.files["file"]
    fname = f.filename or ""

    try:
        if fname.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else "" for c in row])
            wb.close()
        elif fname.endswith(".csv"):
            import csv
            import io
            text = f.read().decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            rows = [list(r) for r in reader]
        else:
            return jsonify({"ok": False, "error": "Unsupported file type. Use .xlsx or .csv"})

        if len(rows) < 2:
            return jsonify({"ok": False, "error": "File must have a header row and at least one data row"})

        # Check if this is step 1 (detect) or step 2 (confirm with mapping)
        mapping_json = request.form.get("mapping")
        if not mapping_json:
            # Step 1: return columns and preview
            return jsonify({
                "ok": True,
                "step": "detect",
                "columns": rows[0],
                "preview": rows[1:6],
                "total_rows": len(rows) - 1,
            })

        # Step 2: apply mapping and import
        mapping = json.loads(mapping_json)
        headers = rows[0]
        registers = []
        for row in rows[1:]:
            if not row or not any(row):
                continue
            reg = {}
            for field, col_name in mapping.items():
                if col_name and col_name in headers:
                    idx = headers.index(col_name)
                    if idx < len(row):
                        reg[field] = row[idx]
            if reg.get("address") and reg.get("name"):
                registers.append({
                    "address": int(reg.get("address", 0)),
                    "name": reg.get("name", ""),
                    "type": reg.get("type", "INT16"),
                    "function_code": int(reg.get("function_code", 4)),
                    "scale": float(reg.get("scale", 1.0)),
                    "bacnet_type": reg.get("bacnet_type", "AI"),
                    "units": reg.get("units", "noUnits"),
                    "description": reg.get("description", ""),
                })

        return jsonify({
            "ok": True,
            "step": "imported",
            "count": len(registers),
            "registers": registers,
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/di_status")
def api_di_status():
    """Return current DI input states (for live display in wizard)."""
    di_reader = app.config.get("di_reader")
    if di_reader is None:
        return jsonify({"inputs": []})
    inputs = []
    for di in di_reader.inputs:
        inputs.append({
            "channel": di.channel,
            "name": di.name,
            "enabled": di.enabled,
            "raw_value": di.raw_value,
            "is_active": di.is_active,
            "normal_state": di.normal_state,
        })
    return jsonify({"inputs": inputs})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_interface_ip(iface: str) -> str:
    """Get the current IP of a network interface."""
    if _dev_mode():
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"
    try:
        r = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", iface],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            if "inet " in line:
                return line.split("inet ")[1].split("/")[0]
    except Exception:
        pass
    return ""


def _bacnet_is_listening() -> bool:
    """Check if something is listening on UDP 47808."""
    try:
        r = subprocess.run(
            ["ss", "-uln"], capture_output=True, text=True, timeout=5,
        )
        return "47808" in r.stdout
    except Exception:
        return False


def _ping(host: str) -> bool:
    if not host:
        return False
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", host],
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _restart(name: str):
    if _dev_mode():
        log.info(f"DEV_MODE: skipping systemctl restart {name}")
        return
    try:
        subprocess.run(["systemctl", "restart", name], timeout=10)
    except Exception as e:
        log.warning(f"Could not restart {name}: {e}")


def _resolve_bind_ip(config: dict) -> str:
    import socket

    if _dev_mode():
        return "0.0.0.0"

    explicit = config.get("webui_bind")
    if explicit:
        return explicit

    bind_ip = config.get("bacnet", {}).get("ip_address", "0.0.0.0")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((bind_ip, 0))
        s.close()
        return bind_ip
    except OSError:
        log.warning(f"Cannot bind to {bind_ip} — falling back to 0.0.0.0")
        return "0.0.0.0"


def run_webui(config: dict, mstp_router=None, di_reader=None):
    app.config["mstp_router"] = mstp_router
    app.config["di_reader"] = di_reader
    bind_ip = _resolve_bind_ip(config)
    port = config.get("webui_port", 80)
    log.info(f"Setup wizard on http://{bind_ip}:{port}")
    app.run(host=bind_ip, port=port, debug=False, use_reloader=False)
