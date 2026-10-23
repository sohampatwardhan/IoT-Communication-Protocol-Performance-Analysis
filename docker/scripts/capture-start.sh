#!/bin/sh
# Foreground tshark on the access interface. sweep.sh starts this with
# docker compose exec -d and stops it with SIGTERM so the pcapng is flushed.
set -eu
out=${1:?capture path required}
bpf=${2:?bpf filter required}
echo "starting out=$out bpf=$bpf" >/tmp/tshark.log
iface=$(/opt/lab/scripts/access-iface.sh 2>>/tmp/tshark.log) || exit 1
mkdir -p "$(dirname "$out")" 2>>/tmp/tshark.log || exit 1
echo "tshark iface=$iface bpf=$bpf out=$out" >>/tmp/tshark.log
exec tshark -i "$iface" -f "$bpf" -F pcapng -w "$out" >>/tmp/tshark.log 2>&1
