#!/bin/sh
# Apply or clear loss on this container's access-network interface.
# Usage: netem.sh <0-100>    install root netem loss N% (0% included)
#        netem.sh clear      remove the root qdisc
# Both the device and the edge run this, so each direction of the access
# hop is an egress netem qdisc. Ingress IFB is not used.
set -eu

iface=$(/opt/lab/scripts/access-iface.sh)

if [ "${1:-}" = "clear" ]; then
    tc qdisc del dev "$iface" root 2>/dev/null || true
    exit 0
fi

loss=${1:?loss percent required}
case "$loss" in
    "" | *[!0-9]*)
        echo "loss must be an integer from 0 to 100 (got $loss)" >&2
        exit 2
        ;;
esac
if [ "$loss" -gt 100 ]; then
    echo "loss must be an integer from 0 to 100 (got $loss)" >&2
    exit 2
fi

if ! tc qdisc replace dev "$iface" root netem loss "${loss}%"; then
    cat >&2 <<EOF
tc netem failed on ${iface}.
sch_netem is not available to this kernel (CONFIG_NET_SCH_NETEM is unset, or the module cannot be loaded).
Containers share the host kernel. cap_add NET_ADMIN does not add a scheduler the kernel was built without.
On Docker Desktop, netem runs inside Desktop's Linux VM, not on macOS. That VM usually includes sch_netem. A nested or stripped cloud kernel often does not.
EOF
    exit 1
fi
tc qdisc show dev "$iface"
