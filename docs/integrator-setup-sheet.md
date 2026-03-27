# SBS EnergyLink — Integrator Setup Sheet

**For the BAS / Niagara Integrator**  
Complete these steps after the SBS EnergyLink panel has been commissioned by the installer.

---

## What Is Already Done

The SBS EnergyLink appliance has been configured and is running. It is:

- Reading BESS data from the EPMS via Modbus TCP
- Broadcasting 23 BACnet/IP points on the private network link to the JACE
- The JACE (Port 1) is pre-configured and reachable at `10.10.10.2`

**You do not need to touch Port 1 or the EnergyLink appliance.**

---

## What You Need to Do (3 Things)

### 1. Configure JACE Port 2 for Your BAS Network

Access the JACE web UI:

```
URL:      http://10.10.10.2
Login:    admin
Password: [printed on panel label]
```

In Niagara Platform → Network Configuration → set Port 2:
- IP address for your BAS network
- Subnet mask
- Default gateway (if routing required)
- BACnet network number (must be unique on your BACnet network)
- BBMD address (if routing BACnet across subnets)

### 2. Load the SBS EnergyLink Station Template

In Niagara Workbench:
1. Connect to the JACE at `10.10.10.2`
2. Open Software Manager → confirm Niagara 4.12+
3. Drag `SBS-EnergyLink.bog` onto the station
4. All 23 BACnet point mappings load automatically

### 3. Run BACnet Discovery on Port 2

1. In the Niagara station, open the BACnet Network on Port 2
2. Run Device Discovery
3. The SBS EnergyLink device appears with Device ID `9001`
   _(or the ID shown on the EnergyLink status page)_
4. All 23 points are pre-mapped in the template — they populate automatically

---

## BACnet Device Details

| Setting       | Value                          |
|---------------|--------------------------------|
| Device ID     | 9001 (default — see label)     |
| Device Name   | SBS-EnergyLink-001             |
| IP Address    | 10.10.10.1 (Port 1 network)    |
| BACnet Port   | 47808 (standard)               |
| Protocol      | BACnet/IP                      |

---

## The 23 BACnet Points

| Object | Point Name                | Units |
|--------|---------------------------|-------|
| AI:1   | App_Version               | —     |
| AI:2   | BESS_Capacity_kWh         | kWh   |
| AI:3   | BESS_Power_kW             | kW    |
| AI:4   | BESS_Power_Setpoint_kW    | kW    |
| AI:5   | BESS_Max_Charge_kW        | kW    |
| AI:6   | BESS_Max_Discharge_kW     | kW    |
| AI:7   | BESS_SOC_Pct              | %     |
| AI:8   | BESS_Total_Charged_kWh    | kWh   |
| AI:9   | BESS_Total_Discharged_kWh | kWh   |
| AI:10  | Grid_Power_kW             | kW    |
| AI:11  | Grid_Energy_Import_kWh    | kWh   |
| AI:12  | Grid_Energy_Export_kWh    | kWh   |
| AI:13  | Solar_Power_kW            | kW    |
| AI:14  | Solar_Energy_Produced_kWh | kWh   |
| AI:15  | Load_Power_kW             | kW    |
| AI:16  | Load_Energy_Consumed_kWh  | kWh   |
| BI:1   | BESS_Error_Present        | —     |
| BI:2   | BESS_Comm_Error           | —     |
| BI:3   | BESS_Low_Cell_Voltage     | —     |
| BI:4   | BESS_High_Cell_Voltage    | —     |
| BI:5   | BESS_Low_Temp_Error       | —     |
| BI:6   | BESS_High_Temp_Error      | —     |
| AV:1   | BESS_Active_Power_Cmd_kW  | kW (R/W) |

---

## Verify It's Working

On the JACE, the following should show valid values within 60 seconds:
- `BESS_SOC_Pct` — battery state of charge (0–100%)
- `BESS_Power_kW` — positive = charging, negative = discharging
- `BESS_Error_Present` — should be FALSE / inactive

If points show `null` or reliability fault after 2 minutes:
1. Check JACE Port 1 is connected to the EnergyLink panel
2. Verify EnergyLink appliance LED is green (API connected)
3. Confirm BACnet network discovery ran on the correct Port 2 network

---

## Support

SBS Controls — BMS Team  
For technical support contact your SBS project manager.
