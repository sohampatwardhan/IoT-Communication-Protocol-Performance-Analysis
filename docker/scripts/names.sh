#!/bin/sh
# Shared trial names. Source this file; do not execute it.
# Requires TRIAL, ENV_NAME, and LOSS. COAP_TYPE and QOS are required only
# for the trials that use them. Sets CSV_REL, PCAP_REL, and BPF.
names_for_trial() {
    trial=${TRIAL:?TRIAL is required}
    env_name=${ENV_NAME:?ENV_NAME is required}
    loss=${LOSS:?LOSS is required}
    coap_type=${COAP_TYPE:-}
    qos=${QOS:-}
    case "$trial" in
        coap)
            if [ -z "$coap_type" ]; then
                echo "COAP_TYPE is required for a CoAP trial" >&2
                return 2
            fi
            CSV_REL="${env_name}/latencies/coap_${coap_type}_${loss}pct.csv"
            PCAP_REL="${env_name}/captures/coap_${coap_type}_${loss}pct.pcapng"
            BPF="port 5683"
            ;;
        http)
            CSV_REL="${env_name}/latencies/http_${loss}pct.csv"
            PCAP_REL="${env_name}/captures/http_standard_${loss}pct.pcapng"
            BPF="port 8080"
            ;;
        coap_http)
            if [ -z "$coap_type" ]; then
                echo "COAP_TYPE is required for a CoAP+HTTP trial" >&2
                return 2
            fi
            CSV_REL="${env_name}/latencies/coap_${coap_type}_http_${loss}pct.csv"
            PCAP_REL="${env_name}/captures/coap_http_${coap_type}_${loss}pct.pcapng"
            BPF="port 5683 or port 8080"
            ;;
        mqtt)
            if [ -z "$qos" ]; then
                echo "QOS is required for an MQTT trial" >&2
                return 2
            fi
            CSV_REL="${env_name}/latencies/mqtt_qos${qos}_${loss}pct.csv"
            PCAP_REL="${env_name}/captures/mqtt_qos${qos}_${loss}pct.pcapng"
            BPF="port 1883"
            ;;
        coap_mqtt)
            if [ -z "$coap_type" ] || [ -z "$qos" ]; then
                echo "COAP_TYPE and QOS are required for a CoAP+MQTT trial" >&2
                return 2
            fi
            CSV_REL="${env_name}/latencies/coap_${coap_type}_mqtt_qos${qos}_${loss}pct.csv"
            PCAP_REL="${env_name}/captures/coap_mqtt_${coap_type}_qos${qos}_${loss}pct.pcapng"
            BPF="port 5683 or port 1883"
            ;;
        *)
            echo "unknown TRIAL: $trial" >&2
            return 2
            ;;
    esac
}
