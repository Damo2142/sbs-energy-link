#!/usr/bin/env bash
# build_mstp_router.sh — Build the bacnet-stack router-mstp binary
# for BACnet/IP-to-MSTP routing on the RevPi RS485 port.
#
# This compiles Steve Karg's bacnet-stack (GPL-2.0 with GCC exception)
# and installs the router-mstp binary to /usr/local/bin/.
#
# Run once on the RevPi (or any ARM/x86 Debian-based system):
#   sudo bash scripts/build_mstp_router.sh
set -euo pipefail

BACNET_STACK_REPO="https://github.com/bacnet-stack/bacnet-stack.git"
BACNET_STACK_TAG="bacnet-stack-1.4.2"
BUILD_DIR="/tmp/bacnet-stack-build"
INSTALL_BIN="/usr/local/bin/router-mstp"

echo "=== Building bacnet-stack router-mstp ==="

# Install build dependencies
echo "Installing build dependencies..."
apt-get update -qq
apt-get install -y -qq build-essential gcc make git

# Clone bacnet-stack
if [[ -d "$BUILD_DIR" ]]; then
    echo "Cleaning previous build directory..."
    rm -rf "$BUILD_DIR"
fi

echo "Cloning bacnet-stack ${BACNET_STACK_TAG}..."
git clone --depth 1 --branch "$BACNET_STACK_TAG" "$BACNET_STACK_REPO" "$BUILD_DIR" 2>&1 | tail -1

# Build router-mstp
echo "Building router-mstp..."
cd "$BUILD_DIR"
make router-mstp 2>&1 | tail -5

# Verify binary exists
if [[ ! -f "bin/router-mstp" ]]; then
    echo "ERROR: bin/router-mstp not found after build" >&2
    exit 1
fi

# Install
echo "Installing to ${INSTALL_BIN}..."
cp bin/router-mstp "$INSTALL_BIN"
chmod 755 "$INSTALL_BIN"

# Cleanup
echo "Cleaning build directory..."
rm -rf "$BUILD_DIR"

echo ""
echo "=== router-mstp installed successfully ==="
echo "Binary: ${INSTALL_BIN}"
echo "Version: $(${INSTALL_BIN} --version 2>&1 || echo 'unknown')"
echo ""
echo "Test with:"
echo "  BACNET_MSTP_IFACE=/dev/ttyRS485 BACNET_IFACE=eth1 router-mstp"
