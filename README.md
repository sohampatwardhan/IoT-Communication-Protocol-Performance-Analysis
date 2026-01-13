# IoT Communication Protocol Performance Analysis

This repository contains automated test scripts for performance analysis of IoT communication protocols as part of **TELE 6510 'Fundamentals of the Internet of Things'** at Northeastern University.

## Repository Structure

```
iot-protocol-simulation/
├── README.md                          (this file)
├── .gitignore                         (version control settings)
├── assets/                            (architecture diagrams)
│   ├── http.png
│   └── mqtt.png
├── environment-1-coap-http/           (CoAP + HTTP tests)
│   ├── README.md
│   └── test.sh
├── environment-2-coap-mqtt/           (CoAP + MQTT tests)
│   ├── README.md
│   └── test.sh
├── comprehensive-test/                (test orchestration)
│   ├── README.md
│   └── lab_test.sh
└── utils/                             (shared utilities)
    ├── install-dependencies.sh
    └── network-control.sh
```

## Quick Start

> [!IMPORTANT]
> Follow these steps in order. Do not skip the dependency installation step.

### 1. Install Dependencies

```bash
chmod +x utils/install-dependencies.sh
sudo ./utils/install-dependencies.sh
```

### 2. Run All Tests

```bash
chmod +x comprehensive-test/lab_test.sh
./comprehensive-test/lab_test.sh
```

### 3. Run Individual Environments

**Environment 1 (CoAP + HTTP):**
```bash
cd environment-1-coap-http
chmod +x test.sh
./test.sh
```

**Environment 2 (CoAP + MQTT):**
```bash
cd environment-2-coap-mqtt
chmod +x test.sh
./test.sh
```

## What's Tested

### Environment 1: CoAP + HTTP
Tests latency and performance of CoAP and HTTP protocols under various packet loss conditions:
- CoAP Confirmable (with acknowledgment)
- CoAP Non-Confirmable (without acknowledgment)
- HTTP
- End-to-end combined scenarios

See [environment-1-coap-http/README.md](environment-1-coap-http/README.md) for details.

### Environment 2: CoAP + MQTT
Tests latency and performance of CoAP with MQTT at different quality-of-service levels:
- QoS 0: At most once
- QoS 1: At least once
- QoS 2: Exactly once

See [environment-2-coap-mqtt/README.md](environment-2-coap-mqtt/README.md) for details.

## Test Parameters

- **Packet Loss Rates**: 0%, 3%, 5%, 10%
- **Transactions per Test**: 30
- **Network Interface**: Loopback (localhost)

## Results

All results are automatically saved to `lab_results/`:

```
lab_results/
├── env1/
│   ├── captures/          # Wireshark packet captures
│   └── latencies/         # CSV latency measurements
├── env2/
│   ├── captures/          # Wireshark packet captures
│   └── latencies/         # CSV latency measurements
└── summary/
    ├── env1_summary.csv
    ├── env2_summary.csv
    └── FULL_REPORT.txt
```

> [!TIP]
> Save the `lab_results/` directory for your lab report submission. Review the summary CSV files for quick performance comparisons.

## System Requirements

> [!WARNING]
> These tests require specific system configurations. Ensure all requirements are met before attempting to run tests.

- **OS**: Linux (Ubuntu 20.04+ recommended)
- **RAM**: 2GB minimum
- **Disk Space**: 1GB for test results
- **Network**: Loopback interface (lo) - no external network required

## Lab Objectives

> [!IMPORTANT]
> These tests directly address the lab questions. Use the results to answer each question with supporting data and Wireshark traces.

These tests address the following lab questions:

1. **Request/Response Delay**: Measure average latency for device-to-application communication
2. **Packet Loss Impact**: Compare protocol performance under 0%, 3%, 5%, 10% packet loss
3. **Message Exchange**: Analyze exact messages exchanged via Wireshark captures
4. **Quality of Service**: Understand how QoS parameters affect latency and reliability

## Troubleshooting

> [!NOTE]
> Review this section if tests fail or produce unexpected results.

### Missing Dependencies
Run the installer again:
```bash
sudo ./utils/install-dependencies.sh
```

### Permission Denied
Make scripts executable:
```bash
chmod +x environment-1-coap-http/test.sh
chmod +x environment-2-coap-mqtt/test.sh
chmod +x comprehensive-test/lab_test.sh
```

### Network Issues
Ensure the loopback interface is available:
```bash
ip link show lo
```

> [!CAUTION]
> If the loopback interface is missing or down, network tests will fail. Contact your system administrator if you cannot bring up the interface.

## Course Information

- **Course**: TELE 6510 - Fundamentals of the Internet of Things
- **University**: Northeastern University
- **Instructor**: Jim O'Brien

## Lab Environments

### Environment 1: CoAP + HTTP
Build a simulated network environment that uses CoAP and HTTP to communicate from an
embedded device to an edge device, to an application.

![img](/assets/http.png)

Suggestions:

1. Install a CoAP server (i.e. libcoap)
2. Install a CoAP client (i.e. libcoap)
3. Install a HTTP server (i.e. node, httpd)
4. Install a HTTP client (i.e. wget, curl)
5. Emulate device, application, edge on VMs/computers.

Questions to answer:

1. Perform the following steps:

    - a. Capture (and paste) Wireshark traces between device and application.

    - b. What is the request/response delay at the application when sending a simple 10-byte (or less) readout? (use Wireshark timestamps, run 30 transaction and use the average).
2. For uniform 0%, 3%, 5% and 10% packet loss introduced at the access side, make a table packet loss vs latency for conﬁrmable and non-conﬁrmable CoAP.
3. Describe the messages that are exchanged between the device and the application.
4. How does quality aﬀect latency? Why?

---

### Environment 2: CoAP + MQTT

Build a simulated network environment that uses CoAP and MQTT to communicate from an
embedded device to an edge device, to an application.

![img](/assets/mqtt.png)

Suggestions:
1. Install a CoAP server (i.e. libcoap)
2. Install a CoAP client (i.e. libcoap)
3. Install an MQTT broker (i.e. MQTT mosquitto).
4. Install an MQTT publisher/subscriber (i.e. Paho MQTT or MQTT mosquito subscriber/publisher).
5. Emulate device, application, edge, broker on VMs/computers.

Questions to answer:

1. Perform the following steps:

    - a. Capture (and paste) Wireshark traces between device and application.

    - b. What is the delay between the device and the application when sending a simple 10-byte (or less) readout? (use Wireshark timestamps, run 30 transaction and use the average).

2. For uniform 0%, 3%, 5% and 10% packet loss introduced at the access side (up to you where). Make a table packet loss vs latency for conﬁrmable CoAP and each quality level at most once, at least once and exactly once of MQTT.
3. Describe the messages that are exchanged between the device and the application.
4. How does CoAP-based MQTT compare against HTTP for same network conditions?