#!/bin/bash

# Environment 2: CoAP + MQTT Testing Script
# For TELE 6510 Lab - Northeastern University

# Source shared utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/network-control.sh"

# Configuration
COAP_SERVER_ADDR="[::1]"
COAP_SERVER_PORT=5683
MQTT_BROKER="localhost"
RESOURCE_PATH="time"
NUM_TRANSACTIONS=30
OUTPUT_DIR="../lab_results/env2"
PACKET_LOSS_RATES=(0 3 5 10)
MQTT_QOS_LEVELS=(0 1 2)

# Create output directories
mkdir -p "$OUTPUT_DIR/captures"
mkdir -p "$OUTPUT_DIR/latencies"
mkdir -p "../lab_results/summary"

# Log functions
log_info() {
    echo -e "\e[1;34m[INFO]\e[0m $1"
}

log_success() {
    echo -e "\e[1;32m[SUCCESS]\e[0m $1"
}

log_error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

# Server management functions
start_coap_server() {
    log_info "Starting CoAP Server..."
    if pgrep -f "coap-server -A ::1" > /dev/null; then
        log_info "CoAP Server is already running"
    else
        coap-server -A ::1 -p $COAP_SERVER_PORT > /dev/null 2>&1 &
        COAP_SERVER_PID=$!
        sleep 2
        log_success "CoAP Server started with PID: $COAP_SERVER_PID"
    fi
}

start_mqtt_broker() {
    log_info "Starting MQTT Broker..."
    if pgrep -f "mosquitto -v" > /dev/null; then
        log_info "MQTT Broker is already running"
    else
        mosquitto -v > /dev/null 2>&1 &
        MQTT_BROKER_PID=$!
        sleep 2
        log_success "MQTT Broker started with PID: $MQTT_BROKER_PID"
    fi
}

stop_servers() {
    log_info "Stopping all servers..."
    [ ! -z "$COAP_SERVER_PID" ] && kill $COAP_SERVER_PID 2>/dev/null
    [ ! -z "$MQTT_BROKER_PID" ] && kill $MQTT_BROKER_PID 2>/dev/null
    log_success "All servers stopped"
}

# Capture management functions
start_capture() {
    local protocol=$1
    local config=$2
    local loss_rate=$3
    local capture_file="$OUTPUT_DIR/captures/${protocol}_${config}_${loss_rate}pct.pcapng"
    
    log_info "Starting capture for $protocol ($config) with $loss_rate% packet loss..."
    
    case $protocol in
        "coap") filter="port $COAP_SERVER_PORT" ;;
        "mqtt") filter="port 1883" ;;
        "coap_mqtt") filter="port $COAP_SERVER_PORT or port 1883" ;;
        *) log_error "Unknown protocol: $protocol"; return 1 ;;
    esac
    
    tshark -i lo -f "$filter" -w "$capture_file" > /dev/null 2>&1 &
    CAPTURE_PID=$!
    sleep 2
    
    echo $CAPTURE_PID
    echo $capture_file
}

stop_capture() {
    local pid=$1
    log_info "Stopping capture process (PID: $pid)..."
    kill $pid 2>/dev/null
    sleep 2
    log_success "Capture stopped"
}

# Test execution functions
run_coap_test() {
    local type=$1
    local loss_rate=$2
    local log_file="$OUTPUT_DIR/latencies/coap_${type}_${loss_rate}pct.csv"
    
    log_info "Running $NUM_TRANSACTIONS $type CoAP transactions with $loss_rate% packet loss..."
    
    read -r capture_pid capture_file <<< $(start_capture "coap" $type $loss_rate)
    
    echo "Transaction,Timestamp,Latency_ms" > "$log_file"
    
    for i in $(seq 1 $NUM_TRANSACTIONS); do
        log_info "CoAP Transaction $i of $NUM_TRANSACTIONS"
        start_time=$(date +%s.%N)
        
        if [ "$type" == "confirmable" ]; then
            coap-client -m get coap://$COAP_SERVER_ADDR:$COAP_SERVER_PORT/$RESOURCE_PATH > /dev/null 2>&1
        else
            coap-client -m get -N coap://$COAP_SERVER_ADDR:$COAP_SERVER_PORT/$RESOURCE_PATH > /dev/null 2>&1
        fi
        
        end_time=$(date +%s.%N)
        latency=$(echo "($end_time - $start_time) * 1000" | bc)
        
        echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$latency" >> "$log_file"
        sleep 1
    done
    
    avg_latency=$(awk -F, 'NR>1 {sum+=$3; count++} END {print sum/count}' "$log_file")
    echo "Average,$avg_latency" >> "$log_file"
    
    log_success "Average latency for $type CoAP with $loss_rate% packet loss: $avg_latency ms"
    
    stop_capture $capture_pid
    echo $avg_latency
}

run_mqtt_test() {
    local qos=$1
    local loss_rate=$2
    local log_file="$OUTPUT_DIR/latencies/mqtt_qos${qos}_${loss_rate}pct.csv"
    
    log_info "Running $NUM_TRANSACTIONS MQTT transactions with QoS $qos and $loss_rate% packet loss..."
    
    read -r capture_pid capture_file <<< $(start_capture "mqtt" "qos$qos" $loss_rate)
    
    mosquitto_sub -h $MQTT_BROKER -t "iot/$RESOURCE_PATH" -q $qos > /dev/null 2>&1 &
    MQTT_SUB_PID=$!
    sleep 2
    
    echo "Transaction,Timestamp,Latency_ms" > "$log_file"
    
    for i in $(seq 1 $NUM_TRANSACTIONS); do
        log_info "MQTT Transaction $i of $NUM_TRANSACTIONS (QoS $qos)"
        start_time=$(date +%s.%N)
        
        mosquitto_pub -h $MQTT_BROKER -t "iot/$RESOURCE_PATH" -m "$(date +%Y-%m-%d)" -q $qos > /dev/null 2>&1
        
        end_time=$(date +%s.%N)
        latency=$(echo "($end_time - $start_time) * 1000" | bc)
        
        echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$latency" >> "$log_file"
        sleep 1
    done
    
    avg_latency=$(awk -F, 'NR>1 {sum+=$3; count++} END {print sum/count}' "$log_file")
    echo "Average,$avg_latency" >> "$log_file"
    
    log_success "Average latency for MQTT QoS $qos with $loss_rate% packet loss: $avg_latency ms"
    
    kill $MQTT_SUB_PID 2>/dev/null
    stop_capture $capture_pid
    echo $avg_latency
}

run_coap_mqtt_test() {
    local coap_type=$1
    local mqtt_qos=$2
    local loss_rate=$3
    local log_file="$OUTPUT_DIR/latencies/coap_${coap_type}_mqtt_qos${mqtt_qos}_${loss_rate}pct.csv"
    
    log_info "Running $NUM_TRANSACTIONS combined CoAP ($coap_type) + MQTT (QoS $mqtt_qos) transactions with $loss_rate% packet loss..."
    
    read -r capture_pid capture_file <<< $(start_capture "coap_mqtt" "${coap_type}_qos${mqtt_qos}" $loss_rate)
    
    mosquitto_sub -h $MQTT_BROKER -t "iot/$RESOURCE_PATH" -q $mqtt_qos > /dev/null 2>&1 &
    MQTT_SUB_PID=$!
    sleep 2
    
    echo "Transaction,Timestamp,CoAP_Latency_ms,MQTT_Latency_ms,Total_Latency_ms" > "$log_file"
    
    for i in $(seq 1 $NUM_TRANSACTIONS); do
        log_info "CoAP + MQTT Transaction $i of $NUM_TRANSACTIONS"
        
        start_time=$(date +%s.%N)
        
        if [ "$coap_type" == "confirmable" ]; then
            coap-client -m get coap://$COAP_SERVER_ADDR:$COAP_SERVER_PORT/$RESOURCE_PATH > /dev/null 2>&1
        else
            coap-client -m get -N coap://$COAP_SERVER_ADDR:$COAP_SERVER_PORT/$RESOURCE_PATH > /dev/null 2>&1
        fi
        
        coap_end_time=$(date +%s.%N)
        
        mosquitto_pub -h $MQTT_BROKER -t "iot/$RESOURCE_PATH" -m "timestamp" -q $mqtt_qos > /dev/null 2>&1
        
        end_time=$(date +%s.%N)
        
        coap_latency=$(echo "($coap_end_time - $start_time) * 1000" | bc)
        mqtt_latency=$(echo "($end_time - $coap_end_time) * 1000" | bc)
        total_latency=$(echo "($end_time - $start_time) * 1000" | bc)
        
        echo "$i,$(date +%Y-%m-%d-%H:%M:%S),$coap_latency,$mqtt_latency,$total_latency" >> "$log_file"
        sleep 1
    done
    
    avg_coap_latency=$(awk -F, 'NR>1 {sum+=$3; count++} END {print sum/count}' "$log_file")
    avg_mqtt_latency=$(awk -F, 'NR>1 {sum+=$4; count++} END {print sum/count}' "$log_file")
    avg_total_latency=$(awk -F, 'NR>1 {sum+=$5; count++} END {print sum/count}' "$log_file")
    echo "Average,$avg_coap_latency,$avg_mqtt_latency,$avg_total_latency" >> "$log_file"
    
    log_success "Average latencies for CoAP ($coap_type) + MQTT (QoS $mqtt_qos) with $loss_rate% packet loss:"
    log_success "  CoAP: $avg_coap_latency ms"
    log_success "  MQTT: $avg_mqtt_latency ms"
    log_success "  Total: $avg_total_latency ms"
    
    kill $MQTT_SUB_PID 2>/dev/null
    stop_capture $capture_pid
    echo $avg_total_latency
}

generate_summary() {
    local summary_file="../lab_results/summary/env2_summary.csv"
    
    log_info "Generating summary table for Environment 2..."
    echo "Packet Loss %,QoS Level,Confirmable CoAP Latency (ms),MQTT Latency (ms),End-to-End Latency (ms)" > "$summary_file"
    
    for loss_rate in "${PACKET_LOSS_RATES[@]}"; do
        for qos in "${MQTT_QOS_LEVELS[@]}"; do
            conf_latency=$(grep "Average" "$OUTPUT_DIR/latencies/coap_confirmable_${loss_rate}pct.csv" | cut -d',' -f2)
            mqtt_latency=$(grep "Average" "$OUTPUT_DIR/latencies/mqtt_qos${qos}_${loss_rate}pct.csv" | cut -d',' -f2)
            e2e_latency=$(grep "Average" "$OUTPUT_DIR/latencies/coap_confirmable_mqtt_qos${qos}_${loss_rate}pct.csv" | cut -d',' -f4)
            echo "$loss_rate,$qos,$conf_latency,$mqtt_latency,$e2e_latency" >> "$summary_file"
        done
    done
    
    log_success "Environment 2 summary table generated at $summary_file"
}

main() {
    log_info "=== Starting Environment 2: CoAP + MQTT Testing ==="
    trap stop_servers EXIT
    
    start_coap_server
    start_mqtt_broker
    
    for loss_rate in "${PACKET_LOSS_RATES[@]}"; do
        set_packet_loss $loss_rate
        
        run_coap_test "confirmable" $loss_rate
        
        for qos in "${MQTT_QOS_LEVELS[@]}"; do
            run_mqtt_test $qos $loss_rate
            run_coap_mqtt_test "confirmable" $qos $loss_rate
        done
        
        if [ $loss_rate -ne 0 ]; then
            remove_packet_loss
        fi
    done
    
    generate_summary
    stop_servers
    
    log_success "=== Testing Complete ==="
    log_success "Results saved to $OUTPUT_DIR"
    log_success "Summary tables in ../lab_results/summary"
}

main
