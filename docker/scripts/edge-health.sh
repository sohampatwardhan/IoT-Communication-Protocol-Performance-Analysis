#!/bin/sh
set -eu
python3 - <<'PY'
import socket
import sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)
s.sendto(bytes([0x40, 0x01, 0x00, 0x01]), ("127.0.0.1", 5683))
data, _addr = s.recvfrom(256)
sys.exit(0 if len(data) >= 4 and data[1] == 69 and data.endswith(b"0123456789") else 1)
PY
iptables -t nat -S POSTROUTING | grep -q MASQUERADE
iptables -t nat -S PREROUTING | grep -q 'dport 8080'
iptables -t nat -S PREROUTING | grep -q 'dport 1883'
