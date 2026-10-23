#!/bin/sh
# One loss point of one trial, inside the device container.
# Writes the same CSV shape as environment-*/test.sh, including the
# unaligned Average footer. Client failures are still timed, matching test.sh.
# Clock is date +%s.%N inside this container, so the host date command
# (macOS has no %N) is not used.
set -eu
. /opt/lab/scripts/names.sh

: "${TRIAL:?}"
: "${ENV_NAME:?}"
: "${LOSS:?}"
: "${TRANSACTIONS:?}"
SLEEP_S=${SLEEP_S:-1}
RESULTS_ROOT=${RESULTS_ROOT:-/results}
COAP_HOST=${COAP_HOST:-10.10.0.20}
HTTP_HOST=${HTTP_HOST:-10.10.0.20}
MQTT_HOST=${MQTT_HOST:-10.10.0.20}
COAP_TYPE=${COAP_TYPE:-}
QOS=${QOS:-}
RESOURCE=time

case "$TRANSACTIONS" in
    "" | *[!0-9]*)
        echo "TRANSACTIONS must be a positive integer" >&2
        exit 2
        ;;
esac
if [ "$TRANSACTIONS" -lt 1 ]; then
    echo "TRANSACTIONS must be a positive integer" >&2
    exit 2
fi

names_for_trial
csv="${RESULTS_ROOT}/${CSV_REL}"
mkdir -p "$(dirname "$csv")"

latency_ms() {
    echo "($2 - $1) * 1000" | bc
}

coap_get() {
    if [ "$COAP_TYPE" = "confirmable" ]; then
        coap-client -m get "coap://${COAP_HOST}:5683/${RESOURCE}" >/dev/null 2>&1 || true
    elif [ "$COAP_TYPE" = "non-confirmable" ]; then
        coap-client -m get -N "coap://${COAP_HOST}:5683/${RESOURCE}" >/dev/null 2>&1 || true
    else
        echo "COAP_TYPE must be confirmable or non-confirmable" >&2
        exit 2
    fi
}

http_get() {
    curl -sS "http://${HTTP_HOST}:8080/${RESOURCE}" >/dev/null 2>&1 || true
}

mqtt_pub() {
    mosquitto_pub -h "$MQTT_HOST" -t "iot/${RESOURCE}" -q "$QOS" -m "$1" >/dev/null 2>&1 || true
}

simple_loop() {
    # $1 is a shell function that performs one transaction.
    echo "Transaction,Timestamp,Latency_ms" >"$csv"
    i=1
    while [ "$i" -le "$TRANSACTIONS" ]; do
        start=$(date +%s.%N)
        "$1"
        end=$(date +%s.%N)
        lat=$(latency_ms "$start" "$end")
        echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$lat" >>"$csv"
        sleep "$SLEEP_S"
        i=$((i + 1))
    done
    avg=$(awk -F, 'NR>1 { sum += $3; count++ } END { if (count) print sum / count }' "$csv")
    echo "Average,$avg" >>"$csv"
}

do_coap() { coap_get; }
do_http() { http_get; }
do_mqtt() { mqtt_pub "$(date +%Y-%m-%d)"; }

case "$TRIAL" in
    coap)
        simple_loop do_coap
        ;;
    http)
        simple_loop do_http
        ;;
    mqtt)
        simple_loop do_mqtt
        ;;
    coap_http)
        echo "Transaction,Timestamp,CoAP_Latency_ms,HTTP_Latency_ms,Total_Latency_ms" >"$csv"
        i=1
        while [ "$i" -le "$TRANSACTIONS" ]; do
            start=$(date +%s.%N)
            coap_get
            coap_end=$(date +%s.%N)
            http_get
            end=$(date +%s.%N)
            coap_lat=$(latency_ms "$start" "$coap_end")
            http_lat=$(latency_ms "$coap_end" "$end")
            total_lat=$(latency_ms "$start" "$end")
            echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$coap_lat,$http_lat,$total_lat" >>"$csv"
            sleep "$SLEEP_S"
            i=$((i + 1))
        done
        avg_coap=$(awk -F, 'NR>1 { sum += $3; count++ } END { if (count) print sum / count }' "$csv")
        avg_http=$(awk -F, 'NR>1 { sum += $4; count++ } END { if (count) print sum / count }' "$csv")
        avg_total=$(awk -F, 'NR>1 { sum += $5; count++ } END { if (count) print sum / count }' "$csv")
        echo "Average,$avg_coap,$avg_http,$avg_total" >>"$csv"
        ;;
    coap_mqtt)
        echo "Transaction,Timestamp,CoAP_Latency_ms,MQTT_Latency_ms,Total_Latency_ms" >"$csv"
        i=1
        while [ "$i" -le "$TRANSACTIONS" ]; do
            start=$(date +%s.%N)
            coap_get
            coap_end=$(date +%s.%N)
            mqtt_pub "timestamp"
            end=$(date +%s.%N)
            coap_lat=$(latency_ms "$start" "$coap_end")
            mqtt_lat=$(latency_ms "$coap_end" "$end")
            total_lat=$(latency_ms "$start" "$end")
            echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$coap_lat,$mqtt_lat,$total_lat" >>"$csv"
            sleep "$SLEEP_S"
            i=$((i + 1))
        done
        avg_coap=$(awk -F, 'NR>1 { sum += $3; count++ } END { if (count) print sum / count }' "$csv")
        avg_mqtt=$(awk -F, 'NR>1 { sum += $4; count++ } END { if (count) print sum / count }' "$csv")
        avg_total=$(awk -F, 'NR>1 { sum += $5; count++ } END { if (count) print sum / count }' "$csv")
        echo "Average,$avg_coap,$avg_mqtt,$avg_total" >>"$csv"
        ;;
    *)
        echo "unknown TRIAL: $TRIAL" >&2
        exit 2
        ;;
esac

echo "wrote $csv"
awk -F, '$1 == "Average" { print }' "$csv"
