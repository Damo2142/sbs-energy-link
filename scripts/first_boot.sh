#!/bin/bash
# SBS EnergyLink - First Boot Setup Script
# Run once on a fresh Ubuntu install to configure the device
# Usage: sudo bash first_boot.sh

set -e

echo "============================================"
echo " SBS EnergyLink - Device Setup"
echo "============================================"

# Install Python dependencies
echo "[1/6] Installing Python packages..."
pip3 install -r /opt/sbs-energylink/requirements.txt --break-system-packages

# Apply network configuration
echo "[2/6] Configuring network interfaces..."
cp /opt/sbs-energylink/scripts/network-config.yaml /etc/netplan/01-sbs-energylink.yaml
chmod 600 /etc/netplan/01-sbs-energylink.yaml
netplan apply

# Copy config template if no config exists
echo "[3/6] Setting up configuration..."
if [ ! -f /opt/sbs-energylink/config/config.yaml ]; then
    cp /opt/sbs-energylink/config/config.template.yaml \
       /opt/sbs-energylink/config/config.yaml
    echo "  Default config created — configure via web UI"
fi

# Install and enable systemd service
echo "[4/6] Installing systemd service..."
cp /opt/sbs-energylink/systemd/sbs-energylink.service \
   /etc/systemd/system/sbs-energylink.service
systemctl daemon-reload
systemctl enable sbs-energylink
systemctl start sbs-energylink

# Create log file
echo "[5/6] Setting up logging..."
touch /var/log/sbs-energylink.log
chmod 644 /var/log/sbs-energylink.log

# Set hostname
echo "[6/6] Setting hostname..."
hostnamectl set-hostname sbs-energylink

echo ""
echo "============================================"
echo " Setup complete!"
echo ""
echo " Commissioning UI: http://10.10.10.1"
echo "   (connect laptop to eth1 port)"
echo ""
echo " Service status:"
systemctl status sbs-energylink --no-pager -l
echo "============================================"
