# SBS EnergyLink — Tesla BESS to BACnet Integration Appliance

**Version:** 1.0  
**Author:** SBS Controls (an Ameresco company)  
**Target Site:** JPMC Discovery BESS — 2100 E Elliot Road, Tempe AZ (and all future sites)

---

## What This Does

Reads Tesla BESS / EPMS data via **Modbus TCP** and presents it as a native
**BACnet/IP device** to any BAS (Niagara, Siemens, JCI, Schneider, etc.).

23 points total — 16 Analog Inputs, 6 Binary Inputs, 1 writable Analog Value.

---

## Project Structure

```
sbs-energylink/
├── src/
│   ├── main.py           # Entry point — starts all services
│   ├── poller.py         # Modbus TCP reader (Tesla registers 200-217, 300)
│   ├── bacnet_server.py  # BACnet/IP server (BAC0 library)
│   ├── data_store.py     # Thread-safe shared state
│   └── web_ui.py         # Flask commissioning UI
├── config/
│   ├── config.yaml            # Site config (written by UI)
│   └── config.template.yaml   # Factory defaults
├── templates/
│   └── index.html             # Commissioning web page
├── systemd/
│   └── sbs-energylink.service # Auto-start service
├── scripts/
│   ├── first_boot.sh          # One-time device setup
│   └── network-config.yaml    # Dual Ethernet netplan config
└── .vscode/
    ├── settings.json
    └── launch.json            # Debug configs including sim mode
```

---

## Quick Start (Development)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run in simulation mode (no hardware needed)
python src/main.py --sim

# 3. Open commissioning UI
#    http://localhost  (or http://10.10.10.1 on device)
```

Or use VS Code: **Run → "Run EnergyLink (Simulation)"**

---

## Network Architecture

```
TESLA/EPMS NETWORK          SBS ENERGYLINK BOX          JACE / BAS
192.168.x.x                                             10.10.10.2
    │                                                       │
    └── eth0 ──────────────────────────── eth1 ────────────┘
        Modbus TCP only              BACnet/IP only
        (reads registers)            (UDP port 47808)
```

- **eth0** — faces Tesla/customer network. Modbus TCP outbound only.
- **eth1** — faces JACE directly. BACnet/IP and commissioning UI only.
- No routing between interfaces. Completely isolated.

---

## BACnet Point List

| Object | Name | Units | Register |
|--------|------|-------|----------|
| AI:1  | App_Version               | —    | 200 |
| AI:2  | BESS_Capacity_kWh         | kWh  | 201 (INT32) |
| AI:3  | BESS_Power_kW             | kW   | 202 |
| AI:4  | BESS_Power_Setpoint_kW    | kW   | 203 |
| AI:5  | BESS_Max_Charge_kW        | kW   | 204 |
| AI:6  | BESS_Max_Discharge_kW     | kW   | 205 |
| AI:7  | BESS_SOC_Pct              | %    | 206 |
| AI:8  | BESS_Total_Charged_kWh    | kWh  | 209 (INT32) |
| AI:9  | BESS_Total_Discharged_kWh | kWh  | 210 (INT32) |
| AI:10 | Grid_Power_kW             | kW   | 211 |
| AI:11 | Grid_Energy_Import_kWh    | kWh  | 212 (INT32) |
| AI:12 | Grid_Energy_Export_kWh    | kWh  | 213 (INT32) |
| AI:13 | Solar_Power_kW            | kW   | 214 |
| AI:14 | Solar_Energy_Produced_kWh | kWh  | 215 (INT32) |
| AI:15 | Load_Power_kW             | kW   | 216 |
| AI:16 | Load_Energy_Consumed_kWh  | kWh  | 217 (INT32) |
| BI:1  | BESS_Error_Present        | —    | 207 |
| BI:2  | BESS_Comm_Error           | —    | 208 bit 0 |
| BI:3  | BESS_Low_Cell_Voltage     | —    | 208 bit 1 |
| BI:4  | BESS_High_Cell_Voltage    | —    | 208 bit 2 |
| BI:5  | BESS_Low_Temp_Error       | —    | 208 bit 3 |
| BI:6  | BESS_High_Temp_Error      | —    | 208 bit 4 |
| AV:1  | BESS_Active_Power_Cmd_kW  | kW   | 300 (R/W) |

---

## Hardware BOM (per panel)

| Item | Part | Cost |
|------|------|------|
| Compute | OnLogic Factor 201 (DIN, Ubuntu, dual ETH) | ~$450 |
| BAS Controller | Tridium JACE 8000 | ~$1,200 |
| Power Supply | Phoenix Contact 24VDC 30W | ~$85 |
| Enclosure | Hoffman 16x16x8 NEMA 4 | ~$180 |
| Hardware/terminals | DIN rail, blocks, glands, cable | ~$112 |
| **Total BOM** | | **~$2,027** |

**Sell price target: ~$4,950 hardware + $1,200 commissioning = ~$6,150/site**

---

## Deployment

```bash
# On target device (first time only)
sudo bash scripts/first_boot.sh

# Service management
systemctl status sbs-energylink
systemctl restart sbs-energylink
journalctl -u sbs-energylink -f
```

---

## Contact

**Patrick Zhen** — Ameresco (project contact, JPMC Discovery)  
pzhen@ameresco.com | +1 480-499-9148
