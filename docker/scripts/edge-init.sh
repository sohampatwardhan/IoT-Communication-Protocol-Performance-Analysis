#!/bin/sh
# Edge: CoAP server on the access side, and NAT toward the core so HTTP and
# MQTT from the device also cross the lossy access hop.
set -eu
access_if=$(/opt/lab/scripts/access-iface.sh)
core_if=$(ip -o -4 addr show | awk '$4 ~ /^10\.20\.0\.20\// { print $2; exit }')
if [ -z "$core_if" ]; then
    echo "core interface for 10.20.0.20 not found" >&2
    ip -o -4 addr show >&2 || true
    exit 1
fi

# Compose sets ip_forward, rp_filter, and send_redirects before this process
# starts. Those /proc nodes are often read-only afterwards, so a second
# sysctl -w fails even when the value is already correct.
if [ "$(cat /proc/sys/net/ipv4/ip_forward)" != "1" ]; then
    echo "net.ipv4.ip_forward is not 1. The edge service sets that sysctl." >&2
    exit 1
fi
sysctl -w net.ipv4.conf.default.rp_filter=0 >/dev/null 2>&1 || true
sysctl -w net.ipv4.conf.all.accept_redirects=0 >/dev/null 2>&1 || true

# Docker's raw table drops a packet addressed to a container IP unless it
# arrives on that container's own bridge. The device therefore talks only to
# this edge. DNAT sends HTTP and MQTT on to the core, and MASQUERADE brings
# the replies back. Both directions still cross the access hop, which is
# where netem is applied.
iptables -t nat -C PREROUTING -i "$access_if" -p tcp --dport 8080 -j DNAT --to-destination 10.20.0.30:8080 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "$access_if" -p tcp --dport 8080 -j DNAT --to-destination 10.20.0.30:8080
iptables -t nat -C PREROUTING -i "$access_if" -p tcp --dport 1883 -j DNAT --to-destination 10.20.0.40:1883 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "$access_if" -p tcp --dport 1883 -j DNAT --to-destination 10.20.0.40:1883
iptables -t nat -C POSTROUTING -s 10.10.0.0/24 -o "$core_if" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s 10.10.0.0/24 -o "$core_if" -j MASQUERADE
iptables -C FORWARD -i "$access_if" -o "$core_if" -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$access_if" -o "$core_if" -j ACCEPT
iptables -C FORWARD -i "$core_if" -o "$access_if" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || iptables -A FORWARD -i "$core_if" -o "$access_if" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

python3 /opt/lab/coap_server.py 0.0.0.0 5683 &
exec sleep infinity
