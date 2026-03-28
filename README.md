# SBS EnergyLink

**Tesla BESS to BACnet Integration Appliance**

One box reads Tesla Battery Energy Storage System data via Modbus TCP and
broadcasts it as a native BACnet device on both BACnet/IP and BACnet MSTP
simultaneously. Any BAS -- Tridium, Honeywell, Siemens, Johnson Controls,
Schneider -- discovers it directly. No JACE, no gateway, no middleware.

```
Tesla EPMS ──Modbus TCP──► EnergyLink ──BACnet/IP──► Any BAS (eth1)
     eth0                       │       ──BACnet MSTP─► Any BAS (RS485)
                                │
                          RevPi DI module
                        (14x 24VDC alarm inputs)
```

---

## Features

- **23 BESS data points** — 16 Analog Inputs, 6 Binary Inputs (fault flags),
  1 writable Analog Value (power command). Same point list every site.
- **14 digital alarm inputs** — RevPi DI expansion module, 24VDC. Each input
  configurable with name, description, normally open/closed, alarm flag.
  Appears as BACnet BI:7 through BI:20.
- **Dual BACnet networks** — BACnet/IP on eth1 and BACnet MSTP on RS485,
  served simultaneously from the same device (ID 9001). MSTP routing via
  Steve Karg's bacnet-stack (proven C implementation, no external hardware).
- **5-step setup wizard** — Browser-based commissioning UI. Configure both
  NICs, Modbus target, BACnet settings, DI input names, and MSTP parameters.
  Apply network config with one button.
- **Live dashboard** — Read-only view of all points, auto-refresh every 15s.
  For commissioning verification and fallback monitoring.
- **Simulation mode** — `--sim` flag generates realistic cycling BESS data.
  Full development without any hardware.
- **DEV_MODE** — Auto-detects network interface, mocks Modbus, simulates DI
  inputs, skips MSTP. Full-featured development on any Ubuntu machine.

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

**Two SKUs:**

| SKU | Contents | Sell Price |
|-----|----------|------------|
| EnergyLink Base | Connect 4 only, 23 BESS points | ~$3,000 |
| EnergyLink Complete | Connect 4 + DI module, 23 BESS + 14 DI points | ~$3,200 |

Assembly and commissioning: ~2.5 hours per unit.

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

# Terminal 2 — EnergyLink
python src/main.py --sim --loglevel DEBUG --port 8080
```

**Open in browser:** http://localhost:8080

**What you get:**
- Setup wizard at http://localhost:8080 (5-step commissioning flow)
- Dashboard at http://localhost:8080/dashboard (live point values)
- BACnet server on UDP 47808 (Device ID 9001, all objects)
- APIs: `/api/status`, `/api/live_data`, `/api/confirm_status`,
  `/api/test_modbus`, `/api/bacnet_test`, `/api/apply_network`

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
│   └── web_ui.py                ← Flask: 5-step wizard + dashboard + REST APIs
│
├── config/
│   ├── config.yaml              ← Active site config (written by wizard)
│   └── config.template.yaml     ← Factory defaults with all sections documented
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
2. Snap RevPi DI module onto Connect 4 via PiBridge (Complete SKU only)
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
| revpimodio2 | RevPi DI access (prod only)|

**External (C, built from source):**

| Package      | Purpose                         |
|--------------|---------------------------------|
| bacnet-stack | BACnet/IP-to-MSTP router binary |

---

## License

Proprietary -- SBS Controls (an Ameresco company).

## Contact

**Dave** -- SBS Controls
Project lead, system architecture, commissioning
