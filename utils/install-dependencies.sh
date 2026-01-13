#!/bin/bash

# Install dependencies for IoT Lab
# For TELE 6510 Lab - Northeastern University

set -e

echo "╔═══════════════════════════════════════════════════════╗"
echo "║            IoT Lab Dependencies Installer             ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "This script should be run with sudo for system package installation."
    echo "Re-running with sudo..."
    exec sudo "$0" "$@"
fi

echo "[1/5] Updating package lists..."
apt-get update > /dev/null

echo "[2/5] Installing system packages..."
packages_to_install=(
    "build-essential"      # Build tools
    "libcoap-3-dev"       # CoAP libraries
    "mosquitto"           # MQTT broker
    "mosquitto-clients"   # MQTT clients
    "wireshark-common"    # Wireshark (minimal)
    "tshark"              # Command-line packet capture
    "curl"                # HTTP client
    "wget"                # Download utility
    "bc"                  # Calculator (for latency math)
)

apt-get install -y "${packages_to_install[@]}" > /dev/null

echo "[3/5] Installing Node.js and npm..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null
    apt-get install -y nodejs > /dev/null
else
    echo "  ✓ Node.js already installed"
fi

echo "[4/5] Installing http-server globally..."
if ! npm list -g http-server &> /dev/null; then
    npm install -g http-server > /dev/null
else
    echo "  ✓ http-server already installed"
fi

echo "[5/5] Verifying installations..."
echo ""

# Verify tools
tools=(
    "gcc"
    "coap-client"
    "mosquitto_pub"
    "mosquitto_sub"
    "tshark"
    "curl"
    "wget"
    "bc"
    "node"
    "npm"
)

all_ok=true
for tool in "${tools[@]}"; do
    if command -v $tool &> /dev/null; then
        version=$($tool --version 2>&1 | head -n1)
        echo "  ✓ $tool: $version"
    else
        echo "  ✗ $tool: NOT FOUND"
        all_ok=false
    fi
done

echo ""
if [ "$all_ok" = true ]; then
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║            ✓ All dependencies installed successfully            ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "You're ready to run the lab tests!"
    echo "Start with: ./comprehensive-test/lab_test.sh"
else
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║         ✗ Some dependencies are missing                        ║"
    echo "║   Please install them manually and try again                   ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    exit 1
fi
