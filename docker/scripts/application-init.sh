#!/bin/sh
# Application: HTTP GET /time returns the same 10-byte body as CoAP.
# mosquitto_sub is started per MQTT trial by sweep.sh.
set -eu
python3 -m http.server 8080 --bind 0.0.0.0 --directory /opt/lab/http >/tmp/http.log 2>&1 &
exec sleep infinity
