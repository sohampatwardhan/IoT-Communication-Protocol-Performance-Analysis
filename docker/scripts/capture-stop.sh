#!/bin/sh
# SIGTERM, not SIGKILL, so tshark can flush the pcapng. Safe when nothing
# is capturing.
if pgrep -x tshark >/dev/null 2>&1; then
    pkill -TERM -x tshark 2>/dev/null || true
    i=0
    while pgrep -x tshark >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge 30 ]; then
            pkill -KILL -x tshark 2>/dev/null || true
            break
        fi
        sleep 0.1
    done
fi
if pgrep -x dumpcap >/dev/null 2>&1; then
    pkill -TERM -x dumpcap 2>/dev/null || true
fi
rm -f /tmp/tshark.log
exit 0
