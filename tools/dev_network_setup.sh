#!/usr/bin/env bash
# dev_network_setup.sh — Add alias IP 192.168.0.27/24 to main interface
# for testing BACnet eth1 communication in DEV_MODE.
# Does NOT touch netplan. Uses transient 'ip addr add' (lost on reboot).
set -euo pipefail

DEV_IP="192.168.0.27"
DEV_CIDR="${DEV_IP}/24"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${PROJECT_DIR}/config/config.yaml"

# --- Auto-detect main network interface ---
IFACE=$(ip route show default | awk '{print $5; exit}')
if [[ -z "$IFACE" ]]; then
    echo "ERROR: Could not detect default network interface" >&2
    exit 1
fi
echo "Detected main interface: ${IFACE}"

# --- Add alias IP if not already present ---
if ip addr show dev "$IFACE" | grep -q "inet ${DEV_CIDR}"; then
    echo "${DEV_CIDR} already assigned to ${IFACE}, skipping add"
else
    echo "Adding ${DEV_CIDR} to ${IFACE}..."
    sudo ip addr add "${DEV_CIDR}" dev "$IFACE"
fi

# --- Update config.yaml: set bacnet ip_address to DEV_IP ---
if command -v python3 &>/dev/null; then
    python3 -c "
import yaml, sys
cfg_path = '${CONFIG}'
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)
cfg.setdefault('bacnet', {})['ip_address'] = '${DEV_IP}'
cfg.setdefault('bacnet', {})['network_mask'] = '24'
with open(cfg_path, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('Updated config.yaml: bacnet.ip_address = ${DEV_IP}')
"
else
    echo "WARNING: python3 not found, config.yaml not updated" >&2
fi

# --- Restart BACnet server (systemd or running process) ---
SERVICE="sbs-energylink.service"
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    echo "Restarting ${SERVICE} so BACnet rebinds to ${DEV_IP}..."
    sudo systemctl restart "$SERVICE"
elif pgrep -f "python.*main.py" >/dev/null 2>&1; then
    echo "NOTE: EnergyLink is running outside systemd."
    echo "      Restart it manually so BACnet rebinds to ${DEV_IP}."
    echo "      (Kill the process and re-run: DEV_MODE=1 python src/main.py --sim --port 8080)"
fi

# --- Confirm ---
echo ""
echo "=== Dev network setup complete ==="
ip addr show dev "$IFACE" | grep "inet "
echo ""
echo "BACnet should bind to ${DEV_IP}:47808 on next start."
echo "YABE: point at ${DEV_IP}:47808 to discover Device 9001."
