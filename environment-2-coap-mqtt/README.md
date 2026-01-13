# Environment 2: CoAP + MQTT

This environment tests the latency and performance characteristics of a network topology using **CoAP** (Constrained Application Protocol) and **MQTT** (Message Queuing Telemetry Transport) communication between an embedded device, edge device, and application.

## Architecture

```
Device (CoAP Client) → Edge Device (MQTT Broker) → Application (MQTT Subscriber)
```

## Prerequisites

- libcoap development libraries (`libcoap-3-dev`)
- Mosquitto MQTT broker and clients (`mosquitto`, `mosquitto-clients`)
- tshark (for packet capture)
- Basic utilities: bc

### Installation

```bash
sudo apt update
sudo apt install -y libcoap-3-dev mosquitto mosquitto-clients bc
```

## Running Tests

Execute the test script from this directory:

```bash
chmod +x test.sh
./test.sh
```

### What the script does:

1. **Starts servers**: CoAP server and MQTT broker on localhost
2. **Runs transactions** at different packet loss rates (0%, 3%, 5%, 10%)
3. **Tests CoAP with MQTT at three QoS levels**:
   - QoS 0: At most once (fire and forget)
   - QoS 1: At least once (with acknowledgment)
   - QoS 2: Exactly once (with handshake)
4. **Captures network traffic** using tshark
5. **Measures latencies** at both CoAP and MQTT stages
6. **Creates summary tables** comparing QoS levels

## Results

Results are saved to `../lab_results/env2/`:

- **Captures**: Wireshark packet capture files (`.pcapng`)
- **Latencies**: CSV files with transaction-level latency data

Summary table: `../lab_results/summary/env2_summary.csv`

## Lab Questions Addressed

This environment answers the following lab questions:

1. **Request/Response Delay**: Average latency for a 10-byte readout across 30 transactions
2. **Packet Loss Impact**: Comparison of CoAP + MQTT at different QoS levels under 0%, 3%, 5%, and 10% packet loss
3. **Message Exchange**: Network captures show exact messages exchanged between device, broker, and application
4. **MQTT vs HTTP**: Latency comparison shows how MQTT compares to HTTP for same network conditions

## Key Metrics

The tests measure:
- CoAP transaction latency (device to edge)
- MQTT publish latency (edge to broker)
- End-to-end latency (device through broker to subscriber)
- Impact of QoS levels on latency and reliability
- Average latencies per test condition

## MQTT Quality of Service Levels

- **QoS 0**: Minimal overhead, no delivery guarantees
- **QoS 1**: Higher latency, guarantees message reaches at least once
- **QoS 2**: Highest latency, guarantees exactly-once delivery with handshake
