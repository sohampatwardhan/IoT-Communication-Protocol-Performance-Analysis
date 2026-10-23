#!/bin/sh
# Print the interface that holds an address on the access network 10.10.0.0/24.
# The device has 10.10.0.10. The edge has 10.10.0.20 and a core address;
# the core address is ignored.
set -eu
iface=$(ip -o -4 addr show | awk '$4 ~ /^10\.10\.0\./ { print $2; exit }')
if [ -z "$iface" ]; then
    echo "no interface has an address in 10.10.0.0/24" >&2
    ip -o -4 addr show >&2 || true
    exit 1
fi
printf '%s\n' "$iface"
