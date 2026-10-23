#!/bin/sh
# Build lab_results/summary from the Average footers, same columns as test.sh.
# Usage: summarize.sh <results-root> "<loss percents>" <env1|env2|both>
set -eu
root=${1:?results root required}
losses=${2:?loss percents required}
which=${3:?env1, env2, or both}

avg_field() {
    file=$1
    field=$2
    if [ ! -f "$file" ]; then
        echo "missing $file" >&2
        exit 1
    fi
    awk -F, -v f="$field" '
        $1 == "Average" { print $f; found = 1 }
        END { if (!found) exit 1 }
    ' "$file"
}

mkdir -p "$root/summary"

if [ "$which" = "env1" ] || [ "$which" = "both" ]; then
    out="$root/summary/env1_summary.csv"
    echo "Packet Loss %,Confirmable CoAP Latency (ms),Non-confirmable CoAP Latency (ms),HTTP Latency (ms),End-to-End Latency (ms)" >"$out"
    for loss in $losses; do
        conf=$(avg_field "$root/env1/latencies/coap_confirmable_${loss}pct.csv" 2)
        non=$(avg_field "$root/env1/latencies/coap_non-confirmable_${loss}pct.csv" 2)
        http=$(avg_field "$root/env1/latencies/http_${loss}pct.csv" 2)
        e2e=$(avg_field "$root/env1/latencies/coap_confirmable_http_${loss}pct.csv" 4)
        echo "$loss,$conf,$non,$http,$e2e" >>"$out"
    done
    echo "wrote $out"
fi

if [ "$which" = "env2" ] || [ "$which" = "both" ]; then
    out="$root/summary/env2_summary.csv"
    echo "Packet Loss %,QoS Level,Confirmable CoAP Latency (ms),MQTT Latency (ms),End-to-End Latency (ms)" >"$out"
    for loss in $losses; do
        for qos in 0 1 2; do
            conf=$(avg_field "$root/env2/latencies/coap_confirmable_${loss}pct.csv" 2)
            mqtt=$(avg_field "$root/env2/latencies/mqtt_qos${qos}_${loss}pct.csv" 2)
            e2e=$(avg_field "$root/env2/latencies/coap_confirmable_mqtt_qos${qos}_${loss}pct.csv" 4)
            echo "$loss,$qos,$conf,$mqtt,$e2e" >>"$out"
        done
    done
    echo "wrote $out"
fi
