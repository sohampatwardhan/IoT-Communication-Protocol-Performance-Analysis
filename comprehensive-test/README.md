# Comprehensive Lab Test Orchestration

This directory contains the main test orchestrator script for running the entire IoT lab.

## Overview

The `lab_test.sh` script automates the execution of both test environments and consolidates results into comprehensive reports.

## Running All Tests

From this directory:

```bash
chmod +x lab_test.sh
./lab_test.sh
```

Or from the repository root:

```bash
./comprehensive-test/lab_test.sh
```

## What It Does

1. **Verifies setup**: Checks that both environment directories exist
2. **Runs Environment 1**: CoAP + HTTP tests (see `../environment-1-coap-http/`)
3. **Runs Environment 2**: CoAP + MQTT tests (see `../environment-2-coap-mqtt/`)
4. **Generates report**: Creates a consolidated report with results from both environments
5. **Displays summary**: Shows key metrics and file locations

## Time Estimate

Expected runtime: **30-60 minutes**

- Environment 1: ~15-30 minutes (4 packet loss rates × 3 modes × 30 transactions)
- Environment 2: ~15-30 minutes (4 packet loss rates × 3 QoS levels × 30 transactions)

## Output

Results are consolidated in `../lab_results/`:

```
lab_results/
├── env1/
│   ├── captures/        # Wireshark .pcapng files
│   └── latencies/       # CSV files with latency data
├── env2/
│   ├── captures/        # Wireshark .pcapng files
│   └── latencies/       # CSV files with latency data
└── summary/
    ├── env1_summary.csv
    ├── env2_summary.csv
    └── FULL_REPORT.txt  # Consolidated report
```

## Notebook

After this script finishes, open `notebooks/protocol_performance.ipynb` to ingest `lab_results/`, attach Wireshark timestamps with `tshark`, and write a timestamped run under `notebooks/run-store/`. The raw `.pcapng` files are kept with that run for the Wireshark screenshots. See the repository README.

## Prerequisites

All prerequisites from both environments must be installed:

```bash
# From repository root
chmod +x utils/install-dependencies.sh
./utils/install-dependencies.sh
```

Or manually:

```bash
sudo apt update
sudo apt install -y libcoap-3-dev mosquitto mosquitto-clients tshark curl wget bc
npm install -g http-server
```

## Troubleshooting

### Test stops unexpectedly

Check that:
- All required tools are installed
- CoAP server and MQTT broker can start
- You have sufficient disk space for packet captures
- Network interfaces aren't busy

### Permission denied

Some network operations require sudo. You may be prompted for your password during tests.

### Network interface not found

The scripts use the loopback interface (`lo`) by default. If you need to use a different interface, edit the respective `test.sh` files.

## Individual Environment Tests

To run environments separately:

```bash
# Environment 1 only
./environment-1-coap-http/test.sh

# Environment 2 only
./environment-2-coap-mqtt/test.sh
```
