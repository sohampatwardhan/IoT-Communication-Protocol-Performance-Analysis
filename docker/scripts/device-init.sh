#!/bin/sh
# Device: client only. CoAP, HTTP, and MQTT are addressed to the edge on the
# access network. Docker drops a packet whose destination is a container on
# the other bridge, so the device does not route to 10.20.0.0/24 itself.
set -eu
sysctl -w net.ipv4.conf.all.accept_redirects=0 >/dev/null 2>&1 || true
exec sleep infinity
