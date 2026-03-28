#!/bin/bash
# SBS EnergyLink - First Boot Setup Script
# Run once on a fresh RevPi to provision the device.
# Usage: sudo bash first_boot.sh
set -e

INSTALL_DIR="/opt/sbs-energylink"
LICENSE_DIR="/etc/sbs-energylink"
LICENSE_FILE="${LICENSE_DIR}/license.key"

VALID_PARTS=("SBS-EL-BESS-001" "SBS-EL-UNIV-001" "SBS-EL-PRO-001")

echo "============================================"
echo " SBS EnergyLink - Device Provisioning"
echo "============================================"
echo ""

# --- License / Part Number ---
echo "[1/8] Product License Setup"
echo ""

if [ -f "$LICENSE_FILE" ]; then
    echo "  Existing license found:"
    cat "$LICENSE_FILE"
    echo ""
    read -p "  Overwrite? (y/N): " overwrite
    if [[ "$overwrite" != "y" && "$overwrite" != "Y" ]]; then
        echo "  Keeping existing license."
    else
        rm -f "$LICENSE_FILE"
    fi
fi

if [ ! -f "$LICENSE_FILE" ]; then
    echo "  Valid part numbers:"
    echo "    SBS-EL-BESS-001  — EnergyLink BESS (Tesla Megapack only)"
    echo "    SBS-EL-UNIV-001  — EnergyLink Universal (any Modbus device)"
    echo "    SBS-EL-PRO-001   — EnergyLink Pro (Universal + Excel import)"
    echo ""

    while true; do
        read -p "  Enter part number: " PART_NUM
        PART_NUM=$(echo "$PART_NUM" | tr '[:lower:]' '[:upper:]')
        valid=false
        for p in "${VALID_PARTS[@]}"; do
            if [[ "$PART_NUM" == "$p" ]]; then valid=true; break; fi
        done
        if $valid; then break; fi
        echo "  ERROR: Invalid part number. Try again."
    done

    # Determine tier from part number
    case "$PART_NUM" in
        SBS-EL-BESS-001) TIER="bess" ;;
        SBS-EL-UNIV-001) TIER="universal" ;;
        SBS-EL-PRO-001)  TIER="pro" ;;
    esac

    # Serial number
    read -p "  Enter serial number (or press Enter for auto): " SERIAL
    if [ -z "$SERIAL" ]; then
        # Auto-generate based on MAC address last 4 hex digits
        MAC_TAIL=$(cat /sys/class/net/eth0/address 2>/dev/null | tr -d ':' | tail -c 5 | tr '[:lower:]' '[:upper:]')
        SERIAL="SBS-EL-${MAC_TAIL:-0001}"
    fi

    # Write license file
    mkdir -p "$LICENSE_DIR"
    cat > "$LICENSE_FILE" <<LICEOF
PRODUCT=${PART_NUM}
SERIAL=${SERIAL}
TIER=${TIER}
ISSUED=$(date +%Y-%m-%d)
SITE=
LICEOF
    chmod 644 "$LICENSE_FILE"
    echo ""
    echo "  License written:"
    cat "$LICENSE_FILE"
fi
echo ""

# --- Python Dependencies ---
echo "[2/8] Installing Python packages..."
pip3 install -r ${INSTALL_DIR}/requirements.txt --break-system-packages 2>&1 | tail -3

# --- MSTP Router Binary ---
echo "[3/8] Building BACnet MSTP router..."
if [ -f "${INSTALL_DIR}/scripts/build_mstp_router.sh" ]; then
    bash "${INSTALL_DIR}/scripts/build_mstp_router.sh" 2>&1 | tail -5
else
    echo "  build_mstp_router.sh not found, skipping"
fi

# --- Network Configuration ---
echo "[4/8] Configuring network interfaces..."
cp ${INSTALL_DIR}/scripts/network-config.yaml /etc/netplan/01-sbs-energylink.yaml
chmod 600 /etc/netplan/01-sbs-energylink.yaml
netplan apply

# --- Config Template ---
echo "[5/8] Setting up configuration..."
if [ ! -f ${INSTALL_DIR}/config/config.yaml ]; then
    cp ${INSTALL_DIR}/config/config.template.yaml \
       ${INSTALL_DIR}/config/config.yaml
    echo "  Default config created — configure via web UI"
fi

# --- Systemd Service ---
echo "[6/8] Installing systemd service..."
cp ${INSTALL_DIR}/systemd/sbs-energylink.service \
   /etc/systemd/system/sbs-energylink.service
systemctl daemon-reload
systemctl enable sbs-energylink
systemctl start sbs-energylink

# --- Logging ---
echo "[7/8] Setting up logging..."
touch /var/log/sbs-energylink.log
chmod 644 /var/log/sbs-energylink.log

# --- Hostname ---
echo "[8/8] Setting hostname..."
hostnamectl set-hostname sbs-energylink

echo ""
echo "============================================"
echo " SBS EnergyLink Provisioning Complete"
echo ""
echo " Product:  $(grep PRODUCT ${LICENSE_FILE} | cut -d= -f2)"
echo " Serial:   $(grep SERIAL ${LICENSE_FILE} | cut -d= -f2)"
echo " Tier:     $(grep TIER ${LICENSE_FILE} | cut -d= -f2)"
echo ""
echo " Commissioning UI: http://<device-ip>"
echo "   (connect laptop to either Ethernet port)"
echo ""
echo " Service status:"
systemctl status sbs-energylink --no-pager -l 2>/dev/null || true
echo "============================================"
