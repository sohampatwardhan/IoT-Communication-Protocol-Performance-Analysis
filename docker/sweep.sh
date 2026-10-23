#!/bin/sh
# Run the loss sweep against an already-up Compose project named iot-lab.
# Bring the stack up from the host first:
#   docker compose up -d --build --wait
#
# Defaults match the lab: 0/3/5/10% loss, 30 transactions, 1 second apart,
# both environments. Examples:
#   ./docker/sweep.sh
#   LOSS_PCTS="0 3 5 10" TRANSACTIONS=30 SLEEP_S=1 SWEEP=both ./docker/sweep.sh
#   LOSS_PCTS=0 TRANSACTIONS=1 SLEEP_S=0 ./docker/sweep.sh
#
# SKIP_NETEM=1 skips tc and is only a connectivity check. Those numbers are
# not a loss sweep.
set -eu
if [ "${DEBUG:-0}" = "1" ]; then
    set -x
fi

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
# shellcheck disable=SC1091
. "$root/docker/scripts/names.sh"

LOSS_PCTS=${LOSS_PCTS:-0 3 5 10}
TRANSACTIONS=${TRANSACTIONS:-30}
SLEEP_S=${SLEEP_S:-1}
SWEEP=${SWEEP:-both}
CAPTURE_WARMUP=${CAPTURE_WARMUP:-1}
# dumpcap may still be holding the last packets when the client returns.
CAPTURE_DRAIN=${CAPTURE_DRAIN:-1}
SUB_WARMUP=${SUB_WARMUP:-1}
SKIP_NETEM=${SKIP_NETEM:-0}

case "$SWEEP" in
    env1 | env2 | both) ;;
    *)
        echo "SWEEP must be env1, env2, or both (got $SWEEP)" >&2
        exit 2
        ;;
esac

case "$TRANSACTIONS" in
    "" | *[!0-9]*)
        echo "TRANSACTIONS must be a positive integer" >&2
        exit 2
        ;;
esac

for loss in $LOSS_PCTS; do
    case "$loss" in
        "" | *[!0-9]*)
            echo "LOSS_PCTS entries must be integers from 0 to 100 (got $loss)" >&2
            exit 2
            ;;
    esac
    if [ "$loss" -gt 100 ]; then
        echo "LOSS_PCTS entries must be integers from 0 to 100 (got $loss)" >&2
        exit 2
    fi
done

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not on PATH. Install Docker and start the engine." >&2
    exit 1
fi

dc() {
    docker compose -f "$root/compose.yaml" "$@"
}

if ! dc ps --status running --format '{{.Service}}' | awk 'BEGIN { ok = 0 } $0 == "device" { ok = 1 } END { exit !ok }'; then
    echo "The iot-lab stack is not running. From the repository root:" >&2
    echo "  docker compose up -d --build --wait" >&2
    exit 1
fi

stop_sub() {
    dc exec -T application sh -c 'pkill -x mosquitto_sub 2>/dev/null || true'
}

stop_capture() {
    dc exec -T capture sh /opt/lab/scripts/capture-stop.sh || true
}

clear_loss() {
    dc exec -T device sh /opt/lab/scripts/netem.sh clear || true
    dc exec -T edge sh /opt/lab/scripts/netem.sh clear || true
}

cleanup() {
    stop_capture || true
    stop_sub || true
    if [ "$SKIP_NETEM" != "1" ]; then
        clear_loss || true
    fi
}
trap cleanup EXIT INT TERM

apply_loss() {
    loss=$1
    if [ "$SKIP_NETEM" = "1" ]; then
        echo "WARNING: SKIP_NETEM=1, so ${loss}% was not applied. Do not use these rows in the lab tables." >&2
        return 0
    fi
    echo "access loss ${loss}% on device egress and edge access egress"
    dc exec -T device sh /opt/lab/scripts/netem.sh "$loss"
    dc exec -T edge sh /opt/lab/scripts/netem.sh "$loss"
}

run_one() {
    TRIAL=$1
    ENV_NAME=$2
    COAP_TYPE=${3:-}
    QOS=${4:-}
    export TRIAL ENV_NAME COAP_TYPE QOS LOSS TRANSACTIONS SLEEP_S
    names_for_trial
    # Compose creates lab_results as root. Make the trial directories from
    # inside the container so a non-root host user can still run the sweep.
    dc exec -T device mkdir -p "/results/$(dirname "$PCAP_REL")" "/results/$(dirname "$CSV_REL")"
    echo "=== ${ENV_NAME} ${TRIAL} loss=${LOSS}% coap=${COAP_TYPE:-} qos=${QOS:-} ==="
    if [ "$TRIAL" = "mqtt" ] || [ "$TRIAL" = "coap_mqtt" ]; then
        stop_sub
        dc exec -d application mosquitto_sub -h 10.20.0.40 -t iot/time -q "$QOS"
        sleep "$SUB_WARMUP"
    fi
    stop_capture
    dc exec -d capture sh /opt/lab/scripts/capture-start.sh "/results/${PCAP_REL}" "$BPF"
    ready=0
    i=0
    while [ "$i" -lt 25 ]; do
        if dc exec -T capture grep -q 'Capturing on' /tmp/tshark.log 2>/dev/null; then
            ready=1
            break
        fi
        i=$((i + 1))
        sleep 0.2
    done
    if [ "$ready" != 1 ]; then
        echo "tshark did not start capturing. Capture log:" >&2
        dc exec -T capture cat /tmp/tshark.log >&2 || true
        exit 1
    fi
    # CAPTURE_WARMUP is extra settle time after "Capturing on".
    sleep "$CAPTURE_WARMUP"
    dc exec -T \
        -e TRIAL="$TRIAL" \
        -e ENV_NAME="$ENV_NAME" \
        -e COAP_TYPE="$COAP_TYPE" \
        -e QOS="$QOS" \
        -e LOSS="$LOSS" \
        -e TRANSACTIONS="$TRANSACTIONS" \
        -e SLEEP_S="$SLEEP_S" \
        device sh /opt/lab/scripts/trial.sh
    sleep "$CAPTURE_DRAIN"
    stop_capture
    if [ "$TRIAL" = "mqtt" ] || [ "$TRIAL" = "coap_mqtt" ]; then
        stop_sub
    fi
}

if [ "$SKIP_NETEM" = "1" ]; then
    dc exec -T device sh -c 'echo "SKIP_NETEM=1 at $(date -u +%Y-%m-%dT%H:%M:%SZ). Loss was not applied. Do not use these rows in the lab tables." > /results/NETEM_SKIPPED.txt'
fi

for LOSS in $LOSS_PCTS; do
    export LOSS
    apply_loss "$LOSS"
    if [ "$SWEEP" = "env1" ] || [ "$SWEEP" = "both" ]; then
        run_one coap env1 confirmable
        run_one coap env1 non-confirmable
        run_one http env1
        run_one coap_http env1 confirmable
    fi
    if [ "$SWEEP" = "env2" ] || [ "$SWEEP" = "both" ]; then
        run_one coap env2 confirmable
        for qos in 0 1 2; do
            run_one mqtt env2 "" "$qos"
            run_one coap_mqtt env2 confirmable "$qos"
        done
    fi
done

dc exec -T device sh /opt/lab/scripts/summarize.sh /results "$LOSS_PCTS" "$SWEEP"
dc exec -T device chmod -R a+rX /results || true
echo "sweep finished: $root/lab_results"
