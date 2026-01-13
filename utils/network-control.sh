#!/bin/bash

# Shared network control utilities for IoT Lab tests
# Source this file in your test scripts

# Network traffic control functions
set_packet_loss() {
    local loss_rate=$1
    
    echo -e "\e[1;34m[INFO]\e[0m Setting packet loss rate to $loss_rate%"
    if tc qdisc show dev lo | grep -q "netem"; then
        sudo tc qdisc change dev lo root netem loss ${loss_rate}%
    else
        sudo tc qdisc add dev lo root netem loss ${loss_rate}%
    fi
    echo -e "\e[1;32m[SUCCESS]\e[0m Packet loss set to $loss_rate%"
}

remove_packet_loss() {
    echo -e "\e[1;34m[INFO]\e[0m Removing packet loss settings"
    sudo tc qdisc del dev lo root 2>/dev/null
    echo -e "\e[1;32m[SUCCESS]\e[0m Packet loss settings removed"
}

# Generic server management helper
kill_process_by_name() {
    local process_name=$1
    if pgrep -f "$process_name" > /dev/null; then
        pkill -f "$process_name"
        sleep 1
        return 0
    fi
    return 1
}

# Validate required tools
check_requirements() {
    local required_tools=("coap-client" "tshark" "bc" "curl")
    local missing_tools=()
    
    for tool in "${required_tools[@]}"; do
        if ! command -v $tool &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        echo -e "\e[1;31m[ERROR]\e[0m Missing required tools: ${missing_tools[@]}"
        echo "Install them with: sudo apt install -y ${missing_tools[@]}"
        return 1
    fi
    return 0
}

# Calculate latency from timestamps
calculate_latency() {
    local start_time=$1
    local end_time=$2
    echo "($end_time - $start_time) * 1000" | bc
}
