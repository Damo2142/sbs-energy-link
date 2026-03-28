# SBS EnergyLink — Claude Code Project Guide

*Last updated: 2026-03-28*

## What This Project Is

SBS EnergyLink is a standalone Python appliance that reads Tesla BESS (Battery
Energy Storage System) data via Modbus TCP and presents it as a native BACnet/IP
device on any customer BAS network. It runs on a RevPi Connect 4 industrial
Linux computer mounted in an electrical panel.

**There is no JACE.** EnergyLink IS the BACnet device. Any vendor BAS (Tridium,
Honeywell, Siemens, Johnson Controls, etc.) discovers it directly via standard
BACnet/IP Who-Is on UDP port 47808.

**Data flow:**
```
Tesla EPMS ──Modbus TCP──► EnergyLink ──BACnet/IP──► Any BAS
     eth0                                    eth1
                              │
                         RevPi DI module
                       (14x 24VDC inputs)
```

---

## Hardware Platform

**Compute module:** Revolution Pi Connect 4 (Item 100376, ~$435) — Raspberry
Pi CM4-based industrial controller. DIN rail mount, Debian Linux, dual Ethernet
(eth0/eth1), RS485 port (`/dev/ttyRS485`), hardware watchdog, 24VDC powered,
-20 to 55C operating range.

**DI expansion:** RevPi DI module (Item 100195, ~$160) — snaps onto the
Connect 4 via PiBridge connector. 14 digital inputs at 24VDC. Accessed via
`revpimodio2` library at `/dev/piControl0`.

**No JACE. No Fitlet3. No OnLogic.** The RevPi is the complete platform.

**Hardware BOM:** ~$885 total (Connect 4 + DI module + DIN enclosure + 24V PSU
+ terminal blocks).

**Two product SKUs:**
- **EnergyLink Base** (~$2,500 sell) — Connect 4 only, no DI module, 23 BESS points
- **EnergyLink Complete** (~$3,200 sell) — Connect 4 + DI module, 23 BESS + 14 DI points

Assembly time: ~2.5 hours including commissioning.

**Development:** Any Ubuntu machine with Python 3.10+. Single NIC is fine —
dev defaults handle the rest.

---

## Network Design

```
┌─────────────────────────────────────────────────┐
│              RevPi Connect 4                     │
│                                                  │
│  eth0 ◄──── EPMS / Tesla network (Modbus TCP)   │
│  eth1 ────► BAS / building network (BACnet/IP)   │
│  RS485 ───► future BACnet MSTP (reserved)        │
│                                                  │
│  PiBridge ◄── RevPi DI (14x 24VDC inputs)       │
└─────────────────────────────────────────────────┘
```

- **eth0:** Faces Tesla EPMS network. Modbus TCP client reads BESS registers.
  DHCP or static IP, configured in wizard Step 2.
- **eth1:** Faces customer BAS network. BACnet/IP server on UDP 47808.
  Static IP, configured in wizard Step 3.
- **RS485:** `/dev/ttyRS485` with switchable 120 ohm termination. Reserved for
  future BACnet MSTP via `misty` library (bridges bacpypes3 onto MSTP).
  Same points available on both IP and MSTP simultaneously when enabled.

---

## Project Structure

```
sbs-energylink/
├── CLAUDE.md                    ← You are here
├── README.md
├── requirements.txt             ← pymodbus, bacpypes3, flask, PyYAML, schedule, revpimodio2
│
├── src/
│   ├── main.py                  ← Entry point — threads: poller, BACnet, DI, web UI
│   ├── poller.py                ← Modbus TCP reader (Tesla EPMS registers)
│   ├── bacnet_server.py         ← bacpypes3 BACnet/IP server, 23 BESS + up to 14 DI objects
│   ├── data_store.py            ← Thread-safe shared state (BESSData dataclass)
│   ├── revpi_di.py              ← RevPi DI module reader (14x 24VDC inputs)
│   ├── mstp_router.py           ← Manages bacnet-stack router-mstp subprocess
│   └── web_ui.py                ← Flask: 5-step wizard + dashboard + APIs
│
├── config/
│   ├── config.yaml              ← Active site config (written by wizard)
│   └── config.template.yaml     ← Factory defaults
│
├── templates/
│   ├── step1.html               ← Site info: name, unit ID, engineer, date
│   ├── step2.html               ← EPMS connection + eth0 network config
│   ├── step3.html               ← BACnet Device ID + DI config table + RS485 MSTP settings
│   ├── step4.html               ← Confirm both sides green + apply network
│   ├── step5.html               ← Handoff: IP:47808 + Device ID + point list + JACE link
│   └── dashboard.html           ← Read-only live data, auto-refresh 15s
│
├── tools/
│   ├── modbus_simulator.py      ← Standalone Modbus TCP server (port 5020)
│   ├── dev_network_setup.sh     ← Add alias IP for BACnet testing in dev
│   └── dev_network_teardown.sh  ← Remove alias IP, revert config
│
├── systemd/
│   └── sbs-energylink.service   ← Systemd unit (production)
│
├── scripts/
│   ├── first_boot.sh            ← One-time device provisioning
│   ├── build_mstp_router.sh     ← Compile bacnet-stack router-mstp binary
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

## Development Workflow

**Dev server:** Ubuntu on `192.168.0.26`, Python 3.12, single NIC (`ens18`).
DEV_MODE is not needed for basic operation — defaults work on the dev server.

**Quick start — two terminals:**

```bash
# Terminal 1 — Modbus simulator (fake EPMS on port 5020)
cd ~/projects/sbs-energylink
source venv/bin/activate
python tools/modbus_simulator.py

# Terminal 2 — EnergyLink
cd ~/projects/sbs-energylink
source venv/bin/activate
python src/main.py --sim --loglevel DEBUG --port 8080
```

**What you get:**
- Setup wizard: http://192.168.0.26:8080 (or http://localhost:8080)
- Dashboard: http://192.168.0.26:8080/dashboard
- BACnet server: 192.168.0.26:47808 (UDP) — Device ID 9001
- All APIs: `/api/status`, `/api/live_data`, `/api/confirm_status`,
  `/api/test_modbus`, `/api/bacnet_test`, `/api/apply_network`

**BACnet testing from Windows:** Use YABE (Yet Another BACnet Explorer).
Point it at `192.168.0.26:47808`. Device 9001 appears with all objects
(device + network-port + 16 AI + 6 BI + 1 AV, plus DI-sourced BI:7-20
when configured).

---

## DEV_MODE

Set `DEV_MODE=1` environment variable for development. It affects:

| Component | Production | DEV_MODE=1 |
|-----------|-----------|------------|
| Flask bind | eth1 config IP | `0.0.0.0` (all interfaces) |
| BACnet bind | config `ip_address`/`network_mask` | Auto-detect default interface IP + `/24` mask |
| `/api/test_modbus` | Connects to real EPMS | Returns mock success |
| `/api/apply_network` | Writes netplan + `netplan apply` | Runs `tools/dev_network_setup.sh` (adds alias IP, updates config) |
| `_ping_jace` / pings | Real ICMP | Skipped, returns True |
| `systemctl restart` | Runs | Skipped |
| RevPi DI inputs | Reads `/dev/piControl0` via revpimodio2 | Simulates random toggling |

The `--port` flag overrides the web UI port (default 80, use 8080 for dev).
The `--sim` flag generates fake BESS data without needing a real Modbus source.

**Dev network helper scripts** (`tools/`):
- `dev_network_setup.sh` — Adds `192.168.0.27/24` alias IP to main interface,
  updates `config.yaml` BACnet IP, so YABE can discover the device on that IP.
  Called automatically by `/api/apply_network` in DEV_MODE.
- `dev_network_teardown.sh` — Removes alias, reverts config to `192.168.0.26`.

---

## Architecture

### Threading Model (main.py)

```
main thread          → signal handling, health logging
├── simulator thread → (--sim only) generates fake BESSData every 5s
├── revpi_di thread  → reads DI module inputs (starts before BACnet)
├── bacnet thread    → asyncio event loop running bacpypes3
│                      _run_async() → _start_bacnet() then update loop
├── mstp thread      → manages router-mstp subprocess (if enabled)
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
  broadcasts hit the correct LAN broadcast address.

### RevPi DI Module (revpi_di.py)

Reads 14 digital inputs from the RevPi DI expansion module via `revpimodio2`
at `/dev/piControl0`. Each input is configurable in the wizard with:
- Name and description
- Normal state (normally open / normally closed) — `is_active` property
  handles NO/NC inversion automatically
- Alarm on fault flag

`DIInput` dataclass per channel; `RevPiDIReader` runs in its own thread
(started before BACnet so objects are ready). In DEV_MODE or when
revpimodio2 is unavailable, simulates with ~10% random toggling per cycle.
DI values feed into BACnet objects BI:7 through BI:20. Channels without
a name in config are disabled (no BACnet object created).

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
di_inputs:
  - { channel: 1, name: "...", description: "...", normal_state: "open", alarm_on_fault: false }
  - ... (up to 14 entries)
mstp:    { enabled: false, port: "/dev/ttyRS485", baud: 38400, mac: 1, max_master: 127 }
poll_interval_seconds / stale_data_timeout_seconds / bacnet_refresh_seconds
webui_port
```

The wizard's step 3 mirrors `eth1.ip_address` into `bacnet.ip_address`
and converts the subnet mask to a CIDR prefix for `bacnet.network_mask`.

---

## BACnet Object List

### BESS Points (23 objects, same every site)

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

### DI Module Points (up to 14 objects, site-configurable)

| Object  | Source        | Notes                                    |
|---------|---------------|------------------------------------------|
| BI:7    | DI channel 1  | Name/description set in wizard Step 3    |
| BI:8    | DI channel 2  | Normal state: open or closed             |
| ...     | ...           | Alarm on fault flag per input            |
| BI:20   | DI channel 14 | Only created if configured in wizard     |

All objects live in the same BACnet device (ID 9001). bacpypes3 also
auto-creates `device:9001` and `network-port:1` objects.

---

## Setup Wizard (5 Steps)

| Step | Route | Purpose |
|------|-------|---------|
| 1 | `/step1` | Site name, unit ID, engineer name, install date |
| 2 | `/step2` | eth0 config (DHCP/static) + EPMS Modbus host/port/unit + test button |
| 3 | `/step3` | BACnet Device ID/Name + DI input config table (14 rows: name, description, normal state, alarm flag) + RS485 MSTP settings (disabled by default) |
| 4 | `/step4` | Confirm both sides: live status polling, 5 sample values, Apply Network button. Continue enabled only when both sides green |
| 5 | `/step5` | Handoff: shows `eth1_ip:47808`, Device ID, full point list, JACE link, dashboard link |

**Dashboard** (`/dashboard`): Read-only live view of all points (BESS + DI),
grouped by Battery Status, Energy Flow, Faults, Digital Inputs, and Control.
Auto-refreshes via `/api/live_data` every 15 seconds. Banner: "For
commissioning and fallback use only."

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | Site config + both interface IPs + connection status |
| `/api/live_data` | GET | All point values (BESS + DI) + connection + staleness |
| `/api/confirm_status` | GET | Step 4 uses this: eth0/eth1 status, sample values, `all_ok` |
| `/api/test_modbus` | GET | Test Modbus connection to EPMS |
| `/api/bacnet_test` | GET | Check if bacpypes3 is listening on 47808 |
| `/api/apply_network` | POST | Production: write netplan + apply. DEV_MODE: run dev_network_setup.sh |

---

## RS485 / BACnet MSTP

The RevPi Connect 4 has a built-in RS485 port at `/dev/ttyRS485` with
switchable 120 ohm termination. EnergyLink acts as a BACnet router —
same device, same points, accessible on both BACnet/IP and MSTP.

**Architecture — no external hardware router needed:**
```
MSTP controllers ──RS485──► router-mstp ──BACnet/IP──► bacpypes3 app
  (BAS devices)              (C process)                (Python process)
  Network 2                  routes NPDUs               Network 1 (eth1)
```

**Implementation:** Uses Steve Karg's `bacnet-stack` (GPL-2.0, v1.4.2)
`router-mstp` binary — a proven C implementation that handles the MSTP
token-passing state machine and serial I/O. The router bridges two BACnet
networks: network 1 (BACnet/IP on eth1) and network 2 (MSTP on RS485).
Our Python bacpypes3 device on network 1 becomes fully discoverable from
MSTP devices through the router. Who-Is/I-Am, ReadProperty, WriteProperty
and all other BACnet services are forwarded transparently.

**Build:** `sudo bash scripts/build_mstp_router.sh` — clones bacnet-stack,
compiles `router-mstp`, installs to `/usr/local/bin/`.

**Manager:** `src/mstp_router.py` (`MSTProuter` class) manages the
router-mstp subprocess — starts it with the correct environment variables,
monitors the process, restarts with exponential backoff on crash. In
DEV_MODE the router is skipped (no RS485 hardware on dev server).

**Config** (`config.yaml`):
```yaml
mstp:
  enabled: false              # set true to start MSTP router
  port: "/dev/ttyRS485"       # RevPi onboard RS485
  baud: 38400                 # standard BACnet MSTP baud rate
  mac: 127                    # MSTP MAC address (0-127)
  max_master: 127             # highest MAC on the trunk
  ip_network: 1               # BACnet network number for IP side
  mstp_network: 2             # BACnet network number for MSTP side
```

**RS485 wiring (RevPi X2 terminal):**
```
P   → Data+ (MSTP bus D+)
N   → Data- (MSTP bus D-)
GND → Functional earth (MSTP bus shield)
```
120 ohm termination switchable via DIP switch on the RevPi.

**Status:** `/api/status` includes `mstp` object with enabled, running,
serial_port, baud, mac, binary_installed, serial_port_exists, and
last_error fields.

---

## Current Working State (2026-03-28)

**Core product is feature-complete for initial RevPi testing.** All
remaining items are wizard UI polish and hardware validation.

**Working:**
- [x] BACnet/IP server — binds on dev (192.168.0.26:47808), all 23 BESS
      objects created, Who-Is/I-Am/ReadProperty verified working
- [x] Simulation mode — realistic cycling BESS data via `--sim`
- [x] Flask wizard — all 5 steps render, POST/redirect works, config saves
- [x] Dashboard — live auto-refresh of all points (BESS + DI)
- [x] All API endpoints return valid JSON, zero 500 errors
- [x] DEV_MODE — auto-detect interface IP, mock Modbus, dev_network_setup.sh
      for alias IP apply flow, MSTP skipped cleanly
- [x] RevPi DI module (`src/revpi_di.py`) — 14 channels via revpimodio2,
      DEV_MODE simulates with ~10% random toggling, NO/NC inversion via
      `is_active`, config-driven enable, BI:7-20 created in BACnet server,
      di_reader thread starts before BACnet in main.py
- [x] BACnet MSTP (`src/mstp_router.py`) — bacnet-stack router-mstp C
      binary bridges BACnet/IP (network 1, eth1) ↔ MSTP (network 2,
      /dev/ttyRS485). MSTProuter manages subprocess with exponential backoff
      restart. Build script at `scripts/build_mstp_router.sh`. DEV_MODE
      skips (no RS485 on dev). Config template has full `mstp:` section.
      `/api/status` includes MSTP status (enabled, running, mac, baud,
      binary_installed, serial_port_exists, last_error)

**TODO (UI polish + hardware validation):**
- [ ] Step 3 template — DI input configuration table UI (14 rows: name,
      description, normal state open/closed, alarm on fault flag)
- [ ] Step 3 template — MSTP settings section (enable toggle, baud, MAC,
      max master) — all config plumbing done, just needs the HTML form
- [ ] Build and test router-mstp on real RevPi hardware with RS485
- [ ] Netplan apply — needs testing on real RevPi hardware
- [ ] YABE discovery on Proxmox — likely needs bridge mode on VM NIC
      (not NAT), investigate and document
- [ ] Production first_boot.sh — update for RevPi hardware detection,
      include build_mstp_router.sh in provisioning
- [ ] systemd service file needs update for new config structure
- [ ] Write unit tests (test_energylink.py exists but needs content)
- [ ] Watchdog — restart poller if stale > 5 minutes
- [ ] Build image script (`scripts/build_image.sh`)
- [ ] Integrator setup sheet PDF generation

---

## Key Design Decisions

1. **No JACE** — EnergyLink is the BACnet device. Any BAS discovers it directly.
2. **RevPi Connect 4** — Industrial Raspberry Pi with dual Ethernet, RS485,
   DIN rail, and PiBridge expansion. Replaces OnLogic/Fitlet3 proposals.
3. **BACnet on eth1, Modbus on eth0** — network isolation by design.
4. **23 BESS points + 14 DI points** — BESS points fixed every site, DI points
   site-configurable via wizard. All in one BACnet device.
5. **bacpypes3, not BAC0** — direct asyncio BACnet stack, no wrapper.
6. **MSTP via bacnet-stack C router** — Python stays clean on BACnet/IP,
   Steve Karg's proven C code handles MSTP token passing on RS485. No
   external hardware router needed — one box does everything.
7. **Wizard configures everything** — NICs, BACnet, DI inputs, MSTP settings.
8. **Dashboard is a fallback** — primary data display is the integrator's BAS.
9. **DEV_MODE detects real interface** — bacpypes3 needs a real IP, not 0.0.0.0.
10. **Simulation mode always works** — `--sim` flag for dev without hardware.
11. **Two SKUs** — Base (no DI, ~$2,500) and Complete (with DI, ~$3,200).

---

## Dependencies

| Package      | Version   | Purpose                              |
|--------------|-----------|--------------------------------------|
| pymodbus     | 3.6.4     | Modbus TCP client                    |
| bacpypes3    | >=0.0.102 | BACnet/IP server                     |
| flask        | 3.0.2     | Setup wizard + dashboard             |
| PyYAML       | 6.0.1     | Config file read/write               |
| schedule     | 1.2.1     | Poll interval management             |
| revpimodio2  | —         | RevPi DI module access (production)  |

**External (C, built from source):**

| Package      | Version | Purpose                              |
|--------------|---------|--------------------------------------|
| bacnet-stack | 1.4.2   | BACnet/IP-to-MSTP router binary      |

Install Python deps: `pip install -r requirements.txt` (use venv at `./venv/`).
Build MSTP router: `sudo bash scripts/build_mstp_router.sh`.
`revpimodio2` only required on RevPi hardware; ignored in dev.

---

## Pricing

| Component | Cost |
|-----------|------|
| RevPi Connect 4 (Item 100376) | ~$435 |
| RevPi DI module (Item 100195) | ~$160 |
| DIN enclosure + 24V PSU + terminal blocks | ~$290 |
| **Hardware total** | **~$885** |
| Assembly + commissioning (2.5 hours) | included in sell price |

| SKU | Contents | Sell Price |
|-----|----------|------------|
| EnergyLink Base | Connect 4 only, 23 BESS points | ~$2,500 |
| EnergyLink Complete | Connect 4 + DI module, 23 BESS + 14 DI points | ~$3,000-3,200 |

---

## Physical Install Sequence

1. Mount DIN rail enclosure in electrical panel, connect 24VDC power
2. Snap RevPi DI module onto Connect 4 via PiBridge (Complete SKU only)
3. Wire 24VDC field contacts to DI terminal blocks (Complete SKU only)
4. Plug laptop into either Ethernet port (DHCP)
5. Open browser to setup wizard
6. Step 1: Enter site info
7. Step 2: Configure eth0 — point at EPMS, test green
8. Step 3: Configure eth1 — set site IP, BACnet Device ID, name DI inputs
9. Step 4: Hit Apply — box reconfigures both interfaces
10. Unplug laptop
11. Plug eth0 into EPMS/Tesla network
12. Plug eth1 into BAS/building network
13. (Optional) Connect RS485 to MSTP trunk
14. BAS discovers Device 9001 with all configured points — done
