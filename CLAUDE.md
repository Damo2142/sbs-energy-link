# SBS EnergyLink — Claude Code Project Guide

*Last updated: 2026-03-27*

## What This Project Is

SBS EnergyLink is a standalone Python appliance that reads Tesla BESS (Battery
Energy Storage System) data via Modbus TCP and presents it as a native BACnet/IP
device on any customer BAS network. It runs on a dual-Ethernet industrial Linux
box mounted in an electrical panel.

**There is no JACE.** EnergyLink IS the BACnet device. Any vendor BAS (Tridium,
Honeywell, Siemens, Johnson Controls, etc.) discovers it directly via standard
BACnet/IP Who-Is on UDP port 47808.

**Data flow:**
```
Tesla EPMS ──Modbus TCP──► EnergyLink ──BACnet/IP──► Any BAS
     eth0                                    eth1
```

---

## Project Structure

```
sbs-energylink/
├── CLAUDE.md                    ← You are here
├── README.md
├── requirements.txt             ← pymodbus, bacpypes3, flask, PyYAML, schedule
│
├── src/
│   ├── main.py                  ← Entry point — threads: poller, BACnet, web UI
│   ├── poller.py                ← Modbus TCP reader (Tesla EPMS registers)
│   ├── bacnet_server.py         ← bacpypes3 BACnet/IP server, all 23 objects
│   ├── data_store.py            ← Thread-safe shared state (BESSData dataclass)
│   └── web_ui.py                ← Flask: 5-step wizard + dashboard + APIs
│
├── config/
│   ├── config.yaml              ← Active site config (written by wizard)
│   └── config.template.yaml     ← Factory defaults
│
├── templates/
│   ├── step1.html               ← Site info: name, unit ID, engineer, date
│   ├── step2.html               ← EPMS connection + eth0 network config
│   ├── step3.html               ← BAS network (eth1) + BACnet device settings
│   ├── step4.html               ← Confirm both sides green + apply network
│   ├── step5.html               ← Handoff: IP:47808 + Device ID + 23 point list
│   └── dashboard.html           ← Read-only live data, auto-refresh 15s
│
├── systemd/
│   └── sbs-energylink.service   ← Systemd unit (production)
│
├── scripts/
│   ├── first_boot.sh            ← One-time device provisioning
│   └── network-config.yaml      ← Netplan template (production)
│
├── docs/
│   └── integrator-setup-sheet.md
│
└── tests/
    ├── __init__.py
    └── test_energylink.py
```

---

## Development Environment

**Dev server:** Ubuntu on `192.168.0.26`, Python 3.12, single NIC (`ens18`).

**Quick start — two terminals:**

```bash
# Terminal 1 — Start EnergyLink with simulated BESS data
cd ~/projects/sbs-energylink
source venv/bin/activate
DEV_MODE=1 python src/main.py --sim --loglevel DEBUG --port 8080

# Terminal 2 — (optional) run tests or curl
curl http://localhost:8080/api/status | python3 -m json.tool
```

**What you get:**
- Setup wizard: http://192.168.0.26:8080 (or http://localhost:8080)
- Dashboard: http://192.168.0.26:8080/dashboard
- BACnet server: 192.168.0.26:47808 (UDP) — Device ID 9001, 23 points
- All APIs: `/api/status`, `/api/live_data`, `/api/confirm_status`,
  `/api/test_modbus`, `/api/bacnet_test`, `/api/apply_network`

**BACnet testing from Windows:** Use YABE (Yet Another BACnet Explorer).
Point it at `192.168.0.26:47808`. Device 9001 appears with 25 objects
(device + network-port + 16 AI + 6 BI + 1 AV).

---

## DEV_MODE

Set `DEV_MODE=1` environment variable for development. It affects:

| Component | Production | DEV_MODE=1 |
|-----------|-----------|------------|
| Flask bind | eth1 config IP | `0.0.0.0` (all interfaces) |
| BACnet bind | config `ip_address`/`network_mask` | Auto-detect default interface IP + `/24` mask |
| `/api/test_modbus` | Connects to real EPMS | Returns mock success |
| `/api/apply_network` | Writes netplan + `netplan apply` | Validates only, no write |
| `_ping_jace` / pings | Real ICMP | Skipped, returns True |
| `systemctl restart` | Runs | Skipped |

The `--port` flag overrides the web UI port (default 80, use 8080 for dev).
The `--sim` flag generates fake BESS data without needing a real Modbus source.

---

## Architecture

### Threading Model (main.py)

```
main thread          → signal handling, health logging
├── simulator thread → (--sim only) generates fake BESSData every 5s
├── bacnet thread    → asyncio event loop running bacpypes3
│                      _run_async() → _start_bacnet() then update loop
└── webui thread     → Flask app.run() — all routes and APIs
```

All threads share a single `DataStore` singleton (`data_store.store`).
The poller/simulator writes; BACnet server and web UI read.

### BACnet Server (bacnet_server.py)

Uses **bacpypes3** (not BAC0). Key imports:
```python
from bacpypes3.app import Application
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject
from bacpypes3.local.binary import BinaryInputObject
```

Application created via `Application.from_args(argparse.Namespace(...))`.
Objects stored in dicts by instance number (`_ai_objects`, `_bi_objects`,
`_av_objects`) for fast updates.

**Bind address resolution** (`_resolve_bind_address`):
- Production: uses `config["bacnet"]["ip_address"]` and `network_mask`
- DEV_MODE: tries config IP first; if unavailable, detects the machine's
  default-route IP via `socket.connect(("8.8.8.8", 80))` and reads the
  actual subnet mask from `ip -o -4 addr show`. This ensures BACnet
  broadcasts hit the correct LAN broadcast address (e.g., `.255` not `.27`).

### Web UI (web_ui.py)

Flask app with absolute template/config paths derived from `__file__`.
All routes pass `cfg=load_config()` to templates. Nav bar on every page
links between "Setup Wizard" and "Live Data".

### Config (config.yaml)

Written by the wizard. Key sections:
```yaml
site_name / unit_id_label / engineer_name / install_date
eth0:    { mode, ip_address, subnet_mask, gateway }
modbus:  { host, port, unit_id }
eth1:    { ip_address, subnet_mask, gateway, dns }
bacnet:  { device_id, device_name, ip_address, network_mask, bind_interface }
poll_interval_seconds / stale_data_timeout_seconds / bacnet_refresh_seconds
webui_port
```

The wizard's step 3 mirrors `eth1.ip_address` into `bacnet.ip_address`
and converts the subnet mask to a CIDR prefix for `bacnet.network_mask`.

---

## BACnet Object List (23 points, same every site)

| Object | Name                      | Units | Modbus Reg | Notes        |
|--------|---------------------------|-------|------------|--------------|
| AI:1   | App_Version               | —     | 200        |              |
| AI:2   | BESS_Capacity_kWh         | kWh   | 201-202    | INT32        |
| AI:3   | BESS_Power_kW             | kW    | 202        |              |
| AI:4   | BESS_Power_Setpoint_kW    | kW    | 203        |              |
| AI:5   | BESS_Max_Charge_kW        | kW    | 204        |              |
| AI:6   | BESS_Max_Discharge_kW     | kW    | 205        |              |
| AI:7   | BESS_SOC_Pct              | %     | 206        | Key point    |
| AI:8   | BESS_Total_Charged_kWh    | kWh   | 209-210    | INT32        |
| AI:9   | BESS_Total_Discharged_kWh | kWh   | 210-211    | INT32        |
| AI:10  | Grid_Power_kW             | kW    | 211        |              |
| AI:11  | Grid_Energy_Import_kWh    | kWh   | 212-213    | INT32        |
| AI:12  | Grid_Energy_Export_kWh    | kWh   | 213-214    | INT32        |
| AI:13  | Solar_Power_kW            | kW    | 214        |              |
| AI:14  | Solar_Energy_Produced_kWh | kWh   | 215-216    | INT32        |
| AI:15  | Load_Power_kW             | kW    | 216        |              |
| AI:16  | Load_Energy_Consumed_kWh  | kWh   | 217-218    | INT32        |
| BI:1   | BESS_Error_Present        | —     | 207        | 0=OK 1=Error |
| BI:2   | BESS_Comm_Error           | —     | 208 bit 0  | Fault flag   |
| BI:3   | BESS_Low_Cell_Voltage     | —     | 208 bit 1  | Fault flag   |
| BI:4   | BESS_High_Cell_Voltage    | —     | 208 bit 2  | Fault flag   |
| BI:5   | BESS_Low_Temp_Error       | —     | 208 bit 3  | Fault flag   |
| BI:6   | BESS_High_Temp_Error      | —     | 208 bit 4  | Fault flag   |
| AV:1   | BESS_Active_Power_Cmd_kW  | kW    | 300        | READ/WRITE   |

bacpypes3 also auto-creates a `network-port:1` object, making 25 total
objects visible in BACnet discovery tools.

---

## Setup Wizard (5 Steps)

| Step | Route | Purpose |
|------|-------|---------|
| 1 | `/step1` | Site name, unit ID, engineer name, install date |
| 2 | `/step2` | eth0 config (DHCP/static) + EPMS Modbus host/port/unit + test button |
| 3 | `/step3` | eth1 static IP/mask/gateway/DNS + BACnet Device ID/Name + test button |
| 4 | `/step4` | Confirm both sides: live status polling, 5 sample values, Apply Network button. Continue enabled only when both sides green |
| 5 | `/step5` | Handoff: shows `eth1_ip:47808`, Device ID, 23-point list, dashboard link |

**Dashboard** (`/dashboard`): Read-only live view of all 23 points, grouped
by Battery Status, Energy Flow, Faults, and Control. Auto-refreshes via
`/api/live_data` every 15 seconds. Banner: "For commissioning and fallback
use only."

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | Site config + both interface IPs + connection status |
| `/api/live_data` | GET | All 23 point values + connection + staleness |
| `/api/confirm_status` | GET | Step 4 uses this: eth0/eth1 status, sample values, `all_ok` |
| `/api/test_modbus` | GET | Test Modbus connection to EPMS |
| `/api/bacnet_test` | GET | Check if bacpypes3 is listening on 47808 |
| `/api/apply_network` | POST | Write netplan config + `netplan apply` |

---

## Current Working State (2026-03-27)

**Working:**
- [x] BACnet server binds on 192.168.0.26:47808 (dev), all 23 objects created
- [x] Raw BACnet Who-Is/I-Am verified working (responds with Device 9001)
- [x] ReadProperty for objectList returns all 25 objects correctly
- [x] Simulation mode generates realistic cycling BESS data
- [x] Flask wizard all 5 steps render, POST/redirect works, config saves
- [x] Dashboard with live auto-refresh of all 23 points
- [x] All API endpoints return valid JSON, zero 500 errors
- [x] DEV_MODE auto-detects interface IP and /24 mask for BACnet
- [x] Nav bar on all pages (wizard + dashboard)

**Known issues:**
- YABE (Windows BACnet explorer) discovers the device but fails to read
  Object List via GUI — raw protocol works fine, likely YABE-side issue
  (Windows Firewall or multi-instance port conflict)

**TODO:**
- [ ] Netplan apply integration — `/api/apply_network` writes but needs
      production testing on dual-NIC hardware
- [ ] Modbus simulator at `tools/modbus_simulator.py` (port 5020) — not
      yet created, currently using `--sim` flag instead
- [ ] Production first_boot.sh needs update to remove JACE references
- [ ] systemd service file needs update for new config structure
- [ ] Write unit tests (test_energylink.py exists but needs content)
- [ ] Watchdog — restart poller if stale > 5 minutes
- [ ] Build image script (`scripts/build_image.sh`)
- [ ] Integrator setup sheet PDF generation

---

## Key Design Decisions

1. **No JACE** — EnergyLink is the BACnet device. Any BAS discovers it directly.
2. **BACnet on eth1, Modbus on eth0** — network isolation by design.
3. **Same 23 points every site** — consistency for BAS template integration.
4. **bacpypes3, not BAC0** — direct asyncio BACnet stack, no wrapper.
5. **Wizard configures both NICs** — full network setup through the browser.
6. **Dashboard is a fallback** — primary data display is the integrator's BAS.
7. **DEV_MODE detects real interface** — bacpypes3 needs a real IP, not 0.0.0.0.
8. **Simulation mode always works** — `--sim` flag for dev without hardware.

---

## Dependencies

| Package    | Version   | Purpose                    |
|------------|-----------|----------------------------|
| pymodbus   | 3.6.4     | Modbus TCP client          |
| bacpypes3  | >=0.0.102 | BACnet/IP server           |
| flask      | 3.0.2     | Setup wizard + dashboard   |
| PyYAML     | 6.0.1     | Config file read/write     |
| schedule   | 1.2.1     | Poll interval management   |

Install: `pip install -r requirements.txt` (use venv at `./venv/`).

---

## Hardware

**Compute module:** OnLogic Factor 201 — DIN rail mount, Ubuntu 22.04 LTS,
dual Intel i225 GbE, fanless, -20 to 70C, 8GB RAM, 64GB eMMC.

**No JACE.** Hardware BOM is compute module + 24V PSU + DIN enclosure +
terminal blocks. Approximate cost ~$854, sell price ~$2,500 installed.

**Development:** Any Ubuntu machine with Python 3.10+. Single NIC is fine
— DEV_MODE handles the rest.

---

## Physical Install Sequence

1. Mount panel, connect 120VAC power
2. Plug laptop into either Ethernet port (DHCP)
3. Open browser to setup wizard
4. Step 2: Configure eth0 — point at EPMS, test green
5. Step 3: Configure eth1 — set site IP, BACnet Device ID
6. Step 4: Hit Apply — box reconfigures both interfaces
7. Unplug laptop
8. Plug eth0 into EPMS network
9. Plug eth1 into BAS/building network
10. BAS discovers Device 9001 with 23 points — done
