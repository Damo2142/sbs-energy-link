#!/usr/bin/env bash
# dev_network_teardown.sh — Remove alias IP 192.168.0.27/24 and revert
# BACnet config back to 192.168.0.26 (dev machine's real IP).
set -euo pipefail

DEV_IP="192.168.0.27"
DEV_CIDR="${DEV_IP}/24"
REVERT_IP="192.168.0.26"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${PROJECT_DIR}/config/config.yaml"

# --- Auto-detect main network interface ---
IFACE=$(ip route show default | awk '{print $5; exit}')
if [[ -z "$IFACE" ]]; then
    echo "ERROR: Could not detect default network interface" >&2
    exit 1
fi
echo "Detected main interface: ${IFACE}"

# --- Remove alias IP ---
if ip addr show dev "$IFACE" | grep -q "inet ${DEV_CIDR}"; then
    echo "Removing ${DEV_CIDR} from ${IFACE}..."
    sudo ip addr del "${DEV_CIDR}" dev "$IFACE"
else
    echo "${DEV_CIDR} not found on ${IFACE}, nothing to remove"
fi

# --- Revert config.yaml: set bacnet ip_address back to REVERT_IP ---
if command -v python3 &>/dev/null; then
    python3 -c "
import yaml
cfg_path = '${CONFIG}'
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)
cfg.setdefault('bacnet', {})['ip_address'] = '${REVERT_IP}'
cfg.setdefault('bacnet', {})['network_mask'] = '24'
with open(cfg_path, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print('Reverted config.yaml: bacnet.ip_address = ${REVERT_IP}')
"
else
    echo "WARNING: python3 not found, config.yaml not updated" >&2
fi

# --- Confirm ---
echo ""
echo "=== Dev network teardown complete ==="
ip addr show dev "$IFACE" | grep "inet "
echo ""
echo "Restart EnergyLink so BACnet rebinds to ${REVERT_IP}."
