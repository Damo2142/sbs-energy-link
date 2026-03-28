# SBS EnergyLink

**Modbus to BACnet Integration Appliance**

One box reads any Modbus TCP or RTU device and broadcasts as a native BACnet
device on both BACnet/IP and BACnet MSTP simultaneously. Any BAS -- Tridium,
Honeywell, Siemens, Johnson Controls, Schneider -- discovers it directly.
No JACE, no gateway, no middleware.

```
Inputs:   eth0 ──Modbus TCP──► EnergyLink ──BACnet/IP──► Any BAS (eth1)
          RS485 ──Modbus RTU──►      │      ──BACnet MSTP─► Legacy BAS (RS485)
                                     │
Local:    RevPi DI module (14x 24VDC alarm inputs)
```

---

## Features

- **23 BESS data points** — 16 Analog Inputs, 6 Binary Inputs (fault flags),
  1 writable Analog Value (power command). Same point list every site.
- **14 digital alarm inputs** — RevPi DI expansion module (standard in every
  unit), 24VDC. Configurable name, description, NO/NC, alarm flag per input.
  Appears as BACnet BI:7 through BI:20.
- **Modbus RTU support** — Read up to 32 serial devices on the RS485 trunk,
  each with its own Modbus address and device profile. Points added to BACnet.
- **RS485 three modes** — Disabled, Modbus RTU Client, or BACnet MSTP.
  Mutually exclusive (one physical port). Configured in wizard Step 3.
- **Dual BACnet networks** — BACnet/IP on eth1 and BACnet MSTP on RS485
  (when not used for RTU). Same device ID 9001, same points on both networks.
  MSTP via Steve Karg's bacnet-stack (proven C, no external hardware router).
- **Three software tiers** — BESS (Tesla only), Universal (any Modbus device
  with profile selector and live register test), Pro (Universal + Excel/CSV
  import with column mapping wizard). License file set at first boot.
- **7 built-in device profiles** — Tesla BESS, Electro Industries Shark 200,
  SMA Solar Inverter, Cummins Generator, Carrier Chiller, ABB VFD, Honeywell
  Gas Meter. Drop a new YAML in `config/device_profiles/` to add more.
- **5-step setup wizard** — Configure NICs, Modbus target, BACnet settings,
  14 DI input names with NO/NC and alarm flags, MSTP parameters. License
  tier badge shown on every page. Apply network config with one button.
- **Excel/CSV import** (Pro tier) — Upload a register map spreadsheet, map
  columns to fields, preview first 5 rows, then import all registers.
- **Live register test** (Universal/Pro) — Read a single Modbus register from
  the connected device, see raw and scaled values instantly.
- **Live dashboard** — Read-only view of all points, auto-refresh every 15s.
- **Modbus simulator** — Standalone TCP server on port 5020 with cycling BESS
  data and periodic fault simulation for end-to-end testing.
- **DEV_MODE** — Auto-detects network interface, mocks Modbus, simulates DI
  inputs, skips MSTP, defaults to PRO tier. Full development on any Ubuntu box.

---

## Hardware

**Revolution Pi Connect 4** (Item 100376) — Industrial Raspberry Pi with
dual Ethernet, RS485, DIN rail mount, hardware watchdog, 24VDC power.

**RevPi DI Module** (Item 100195) — 14 digital inputs at 24VDC, snaps onto
Connect 4 via PiBridge.

| Component | Cost |
|-----------|------|
| RevPi Connect 4 | ~$435 |
| RevPi DI module | ~$160 |
| DIN enclosure + 24V PSU + terminal blocks | ~$290 |
| **Total hardware BOM** | **~$885** |

**Three product tiers** (identical hardware, software license differentiates):

| Part Number | Tier | Features | Sell Price |
|-------------|------|----------|------------|
| SBS-EL-BESS-001 | BESS | Tesla Megapack only, locked register map | ~$2,800 |
| SBS-EL-UNIV-001 | Universal | Any Modbus device, profile selector, register builder | ~$3,200 |
| SBS-EL-PRO-001 | Pro | Universal + Excel/CSV import with column mapping | ~$3,800 |

All tiers include RevPi Connect 4 + DI module (DI board is standard in every
unit). Assembly and commissioning: ~2.5 hours per unit.

---

## Quick Start (Development)

**Requirements:** Ubuntu with Python 3.10+, single NIC is fine.

```bash
# Clone and set up
git clone <repo-url> sbs-energylink
cd sbs-energylink
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — Modbus simulator (fake EPMS on port 5020)
python tools/modbus_simulator.py

# Terminal 2 — EnergyLink (DEV_MODE auto-detected, defaults to PRO tier)
python src/main.py --sim --port 8080
```

**Open in browser:** http://localhost:8080

**What you get:**
- Setup wizard at http://localhost:8080 (PRO tier badge, all features)
- Dashboard at http://localhost:8080/dashboard (live point values)
- BACnet server on UDP 47808 (Device ID 9001, all objects)
- Modbus simulator on TCP 5020 (cycling BESS data with fault sim)
- All APIs: `/api/status`, `/api/live_data`, `/api/profiles`,
  `/api/test_register`, `/api/import_registers`, `/api/di_status`,
  `/api/confirm_status`, `/api/test_modbus`, `/api/bacnet_test`,
  `/api/apply_network`

**BACnet testing from Windows:** Use [YABE](https://sourceforge.net/projects/yetanotherbacnetexplorer/)
pointed at `<dev-server-ip>:47808`. Device 9001 appears with all configured
objects.

---

## Project Structure

```
sbs-energylink/
├── README.md
├── CLAUDE.md                    ← Detailed project guide for Claude Code
├── requirements.txt             ← pymodbus, bacpypes3, flask, PyYAML, schedule
│
├── src/
│   ├── main.py                  ← Entry point — threads: poller, DI, BACnet, MSTP, web UI
│   ├── poller.py                ← Modbus TCP reader (Tesla EPMS registers 200-218, 300)
│   ├── bacnet_server.py         ← bacpypes3 BACnet/IP server (AI:1-16, BI:1-20, AV:1)
│   ├── data_store.py            ← Thread-safe shared state (BESSData dataclass)
│   ├── revpi_di.py              ← RevPi DI module reader (14x 24VDC inputs via revpimodio2)
│   ├── mstp_router.py           ← Manages bacnet-stack router-mstp C subprocess
│   ├── rtu_poller.py            ← Modbus RTU client for RS485 serial devices
│   ├── license.py               ← License/tier system (BESS/Universal/Pro)
│   ├── profiles.py              ← Device profile loader (config/device_profiles/*.yaml)
│   └── web_ui.py                ← Flask: 5-step wizard + dashboard + REST APIs
│
├── config/
│   ├── config.yaml              ← Active site config (written by wizard)
│   ├── config.template.yaml     ← Factory defaults with all sections documented
│   └── device_profiles/         ← Modbus register profiles (drop-in YAML)
│       ├── tesla_bess.yaml      ← Tesla Megapack / EPMS
│       ├── shark_200_meter.yaml ← Electro Industries Shark 200
│       ├── sma_solar_inverter.yaml ← SMA solar inverter
│       ├── cummins_generator.yaml  ← Cummins generator
│       ├── carrier_chiller.yaml    ← Carrier chiller
│       ├── abb_vfd.yaml           ← ABB ACS580/ACS880 VFD
│       └── honeywell_gas_meter.yaml ← Honeywell Elster gas meter
│
├── templates/
│   ├── step1.html               ← Site info: name, unit ID, engineer, date
│   ├── step2.html               ← EPMS Modbus connection + eth0 network config
│   ├── step3.html               ← BACnet settings + DI input config + MSTP settings
│   ├── step4.html               ← Confirm both sides green + apply network
│   ├── step5.html               ← Integrator handoff: IPs, Device ID, point list
│   └── dashboard.html           ← Read-only live data, auto-refresh 15s
│
├── tools/
│   ├── modbus_simulator.py      ← Standalone Modbus TCP server (port 5020)
│   ├── dev_network_setup.sh     ← Add alias IP for BACnet testing in dev
│   └── dev_network_teardown.sh  ← Remove alias IP, revert config
│
├── scripts/
│   ├── first_boot.sh            ← One-time device provisioning
│   ├── build_mstp_router.sh     ← Compile bacnet-stack router-mstp binary
│   └── network-config.yaml      ← Netplan template (production dual-NIC)
│
├── systemd/
│   └── sbs-energylink.service   ← Systemd unit for production auto-start
│
├── docs/
│   └── integrator-setup-sheet.md
│
└── tests/
    ├── __init__.py
    └── test_energylink.py
```

---

## BACnet Point List

### BESS Points (23 objects, same every site)

| Object | Name                      | Units | Source       |
|--------|---------------------------|-------|--------------|
| AI:1   | App_Version               | --    | Reg 200      |
| AI:2   | BESS_Capacity_kWh         | kWh   | Reg 201-202 (INT32) |
| AI:3   | BESS_Power_kW             | kW    | Reg 202      |
| AI:4   | BESS_Power_Setpoint_kW    | kW    | Reg 203      |
| AI:5   | BESS_Max_Charge_kW        | kW    | Reg 204      |
| AI:6   | BESS_Max_Discharge_kW     | kW    | Reg 205      |
| AI:7   | BESS_SOC_Pct              | %     | Reg 206      |
| AI:8   | BESS_Total_Charged_kWh    | kWh   | Reg 209-210 (INT32) |
| AI:9   | BESS_Total_Discharged_kWh | kWh   | Reg 210-211 (INT32) |
| AI:10  | Grid_Power_kW             | kW    | Reg 211      |
| AI:11  | Grid_Energy_Import_kWh    | kWh   | Reg 212-213 (INT32) |
| AI:12  | Grid_Energy_Export_kWh    | kWh   | Reg 213-214 (INT32) |
| AI:13  | Solar_Power_kW            | kW    | Reg 214      |
| AI:14  | Solar_Energy_Produced_kWh | kWh   | Reg 215-216 (INT32) |
| AI:15  | Load_Power_kW             | kW    | Reg 216      |
| AI:16  | Load_Energy_Consumed_kWh  | kWh   | Reg 217-218 (INT32) |
| BI:1   | BESS_Error_Present        | --    | Reg 207      |
| BI:2   | BESS_Comm_Error           | --    | Reg 208 bit 0 |
| BI:3   | BESS_Low_Cell_Voltage     | --    | Reg 208 bit 1 |
| BI:4   | BESS_High_Cell_Voltage    | --    | Reg 208 bit 2 |
| BI:5   | BESS_Low_Temp_Error       | --    | Reg 208 bit 3 |
| BI:6   | BESS_High_Temp_Error      | --    | Reg 208 bit 4 |
| AV:1   | BESS_Active_Power_Cmd_kW  | kW    | Reg 300 (R/W) |

### Digital Input Points (up to 14, site-configurable)

| Object  | Source          | Notes |
|---------|-----------------|-------|
| BI:7    | DI channel 1    | Name and normal state (NO/NC) set in wizard |
| BI:8    | DI channel 2    | Alarm on fault flag per input |
| ...     | ...             | Only created for configured channels |
| BI:20   | DI channel 14   | |

All objects live in BACnet Device 9001. bacpypes3 auto-creates `device:9001`
and `network-port:1`, visible in discovery tools.

---

## BACnet MSTP (RS485)

EnergyLink acts as a BACnet router -- same device, same points, accessible on
both BACnet/IP (eth1) and BACnet MSTP (RS485) simultaneously.

```
MSTP controllers ──RS485──> router-mstp ──BACnet/IP──> bacpypes3 app
  (BAS devices)              (C process)                (Python app)
  Network 2                  routes NPDUs               Network 1
```

Uses Steve Karg's [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack)
`router-mstp` binary. No external hardware router needed.

**Build the router binary (run once on RevPi):**

```bash
sudo bash scripts/build_mstp_router.sh
```

This clones bacnet-stack v1.4.2, compiles `router-mstp`, and installs it to
`/usr/local/bin/`. The Python `MSTProuter` class manages the process
automatically when `mstp.enabled: true` in config.

**RS485 wiring (RevPi X2 terminal):**
```
P   --> Data+ (MSTP bus D+)
N   --> Data- (MSTP bus D-)
GND --> Functional earth (MSTP bus shield)
```

120 ohm termination via DIP switch on the RevPi.

---

## Deployment to RevPi

```bash
# Copy project to RevPi
scp -r sbs-energylink/ pi@<revpi-ip>:~/

# SSH in and provision
ssh pi@<revpi-ip>
cd ~/sbs-energylink
sudo bash scripts/first_boot.sh

# Build MSTP router (if using RS485)
sudo bash scripts/build_mstp_router.sh

# Service management
sudo systemctl status sbs-energylink
sudo systemctl restart sbs-energylink
sudo journalctl -u sbs-energylink -f
```

After first boot, open the setup wizard in a browser and walk through the
5-step commissioning flow. The device is production-ready after Step 5.

---

## Network Architecture

```
┌─────────────────────────────────────────────────┐
│              RevPi Connect 4                     │
│                                                  │
│  eth0 <---- EPMS / Tesla network (Modbus TCP)    │
│  eth1 ----> BAS / building network (BACnet/IP)   │
│  RS485 ---> BACnet MSTP trunk (optional)         │
│                                                  │
│  PiBridge <-- RevPi DI (14x 24VDC inputs)        │
└─────────────────────────────────────────────────┘
```

- **eth0** -- Tesla/EPMS network. Modbus TCP client reads BESS registers.
- **eth1** -- Customer BAS network. BACnet/IP server on UDP 47808.
- **RS485** -- BACnet MSTP trunk via router-mstp. Same points as IP.
- **No routing between eth0 and eth1.** Networks are fully isolated.

---

## Physical Install

1. Mount DIN rail enclosure in electrical panel, connect 24VDC power
2. Snap RevPi DI module onto Connect 4 via PiBridge (standard in all units)
3. Wire 24VDC field contacts to DI terminal blocks
4. Plug laptop into either Ethernet port
5. Open browser to setup wizard
6. Step 1: Enter site info
7. Step 2: Configure eth0, point at EPMS, test green
8. Step 3: Configure eth1, set BACnet Device ID, name DI inputs, set MSTP
9. Step 4: Hit Apply -- box reconfigures both interfaces
10. Unplug laptop, plug eth0 into EPMS, eth1 into BAS
11. (Optional) Connect RS485 to MSTP trunk
12. BAS discovers Device 9001 with all configured points -- done

---

## Dependencies

**Python** (in `requirements.txt`):

| Package     | Purpose                    |
|-------------|----------------------------|
| pymodbus    | Modbus TCP client          |
| bacpypes3   | BACnet/IP server           |
| flask       | Setup wizard + dashboard   |
| PyYAML      | Config file read/write     |
| schedule    | Poll interval management   |
| openpyxl    | Excel import (Pro tier)    |
| revpimodio2 | RevPi DI access (prod only)|

**External (C, built from source):**

| Package      | Purpose                         |
|--------------|---------------------------------|
| bacnet-stack | BACnet/IP-to-MSTP router binary |

---

## License System

Each unit ships with a printed label showing part number, serial number,
and QR code linking to the wizard. The serial on the label matches the
license file.

**License file** at `/etc/sbs-energylink/license.key`:
```
PRODUCT=SBS-EL-UNIV-001
SERIAL=SBS-EL-0042
TIER=universal
ISSUED=2026-03-28
SITE=
```

- `first_boot.sh` prompts for part number (validates against 3 valid SKUs)
  and serial number (auto-generates from MAC if not entered)
- Application reads license on startup and sets tier automatically
- DEV_MODE with no license file defaults to PRO (all features for testing)
- Missing license in production defaults to BESS (safe default)
- `/api/status` includes license info (part_number, serial, tier, valid)
- Wizard shows part number, serial, and tier badge on every page

---

## Adding Device Profiles

Drop a YAML file in `config/device_profiles/` and it appears in the wizard
profile selector automatically. No code changes needed.

**Profile format:**
```yaml
name: "Device Name"
manufacturer: "Manufacturer"
model: "Model Number"
protocol: "Modbus TCP"
default_port: 502
default_unit_id: 1

registers:
  - address: 200
    name: "Point_Name"
    type: INT16          # INT16, INT32, FLOAT, COIL
    function_code: 4     # 3=holding, 4=input
    scale: 1.0           # multiply raw value by this
    bacnet_type: AI       # AI, BI, AV, BV
    units: "kilowatts"   # BACnet engineering units
    description: "Human readable description"
    writable: false       # true for command points (AV)
```

**Built-in profiles:** Tesla BESS (17 registers), Shark 200 meter (14),
SMA solar inverter (9), Cummins generator (16), Carrier chiller (14),
ABB VFD (14), Honeywell gas meter (10).

---

## API Endpoints

| Endpoint | Method | Tier | Purpose |
|----------|--------|------|---------|
| `/api/status` | GET | All | Site config, IPs, license, MSTP, DI hardware |
| `/api/live_data` | GET | All | All point values + connection + staleness |
| `/api/confirm_status` | GET | All | Step 4 polling: both-sides status |
| `/api/test_modbus` | GET | All | Test Modbus connection to EPMS |
| `/api/bacnet_test` | GET | All | Check BACnet server on 47808 |
| `/api/apply_network` | POST | All | Apply netplan (prod) or dev alias (dev) |
| `/api/profiles` | GET | All | List available device profiles |
| `/api/profile/<file>` | GET | All | Load profile with full register list |
| `/api/di_status` | GET | All | Live DI input states |
| `/api/test_register` | POST | Universal+ | Read single register, raw + scaled |
| `/api/import_registers` | POST | Pro | Excel/CSV upload, column map, import |

---

## License

Proprietary -- SBS Controls (an Ameresco company).

## Contact

**Dave** -- SBS Controls
Project lead, system architecture, commissioning
