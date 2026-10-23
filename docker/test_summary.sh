#!/bin/sh
# Names and summary layout, without Docker. The Average footer is the
# unaligned one test.sh writes (field 2, or field 4 for end-to-end total).
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC1091
. "$root/docker/scripts/names.sh"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

write_simple() {
    file=$1
    mkdir -p "$(dirname "$file")"
    printf '%s\n' "Transaction,Timestamp,Latency_ms" "1,2026-01-01-00:00:00,10" "Average,10" >"$file"
}

write_combined() {
    file=$1
    mkdir -p "$(dirname "$file")"
    printf '%s\n' "Transaction,Timestamp,CoAP_Latency_ms,HTTP_Latency_ms,Total_Latency_ms" \
        "1,2026-01-01-00:00:00,1,2,3" "Average,1,2,3" >"$file"
}

TRIAL=coap ENV_NAME=env1 LOSS=0 COAP_TYPE=confirmable
names_for_trial
test "$CSV_REL" = "env1/latencies/coap_confirmable_0pct.csv"
test "$PCAP_REL" = "env1/captures/coap_confirmable_0pct.pcapng"

TRIAL=http ENV_NAME=env1 LOSS=10
names_for_trial
test "$PCAP_REL" = "env1/captures/http_standard_10pct.pcapng"

TRIAL=coap_http ENV_NAME=env1 LOSS=5 COAP_TYPE=non-confirmable
names_for_trial
test "$CSV_REL" = "env1/latencies/coap_non-confirmable_http_5pct.csv"
test "$PCAP_REL" = "env1/captures/coap_http_non-confirmable_5pct.pcapng"

TRIAL=mqtt ENV_NAME=env2 LOSS=3 QOS=2
names_for_trial
test "$CSV_REL" = "env2/latencies/mqtt_qos2_3pct.csv"
test "$PCAP_REL" = "env2/captures/mqtt_qos2_3pct.pcapng"

TRIAL=coap_mqtt ENV_NAME=env2 LOSS=0 COAP_TYPE=confirmable QOS=1
names_for_trial
test "$CSV_REL" = "env2/latencies/coap_confirmable_mqtt_qos1_0pct.csv"
test "$PCAP_REL" = "env2/captures/coap_mqtt_confirmable_qos1_0pct.pcapng"

for loss in 0; do
    write_simple "$tmpdir/env1/latencies/coap_confirmable_${loss}pct.csv"
    write_simple "$tmpdir/env1/latencies/coap_non-confirmable_${loss}pct.csv"
    write_simple "$tmpdir/env1/latencies/http_${loss}pct.csv"
    write_combined "$tmpdir/env1/latencies/coap_confirmable_http_${loss}pct.csv"
    write_simple "$tmpdir/env2/latencies/coap_confirmable_${loss}pct.csv"
    for qos in 0 1 2; do
        write_simple "$tmpdir/env2/latencies/mqtt_qos${qos}_${loss}pct.csv"
        write_combined "$tmpdir/env2/latencies/coap_confirmable_mqtt_qos${qos}_${loss}pct.csv"
    done
done

"$root/docker/scripts/summarize.sh" "$tmpdir" "0" both
grep -q '^0,10,10,10,3$' "$tmpdir/summary/env1_summary.csv"
grep -q '^0,1,10,10,3$' "$tmpdir/summary/env2_summary.csv"
echo "names and summary ok"
