# Environment 1: CoAP + HTTP

![img](/assets/http.png)

This environment tests the latency and performance characteristics of a network topology using **CoAP** (Constrained Application Protocol) and **HTTP** communication between an embedded device, edge device, and application.

## Architecture

```
Device (CoAP/HTTP Client) → Edge Device → Application Server
```

## Prerequisites

> [!IMPORTANT]
> Ensure all prerequisites are installed before running tests. Missing dependencies will cause test failures.

- libcoap development libraries (`libcoap-3-dev`)
- Node.js and npm (for HTTP server)
- tshark (for packet capture)
- Basic utilities: curl, bc

### Installation

```bash
sudo apt update
sudo apt install -y libcoap-3-dev curl wget bc
npm install -g http-server
```

> [!TIP]
> Consider running installation commands with `sudo` if you encounter permission errors.

## Running Tests

Execute the test script from this directory:

```bash
chmod +x test.sh
./test.sh
```

### What the script does:

> [!NOTE]
> The script automates the entire testing workflow including server setup, packet loss simulation, and result collection. This may take several minutes depending on system resources.

1. **Starts servers**: CoAP server and HTTP server on localhost
2. **Runs transactions** at different packet loss rates (0%, 3%, 5%, 10%)
3. **Tests three modes**:
   - CoAP Confirmable (with acknowledgment)
   - CoAP Non-Confirmable (no acknowledgment)
   - HTTP (standard HTTP requests)
4. **Captures network traffic** using tshark
5. **Measures latencies** and generates CSV reports
6. **Creates summary tables** comparing all modes

## Results

Results are saved to `../lab_results/env1/`:

- **Captures**: Wireshark packet capture files (`.pcapng`)
- **Latencies**: CSV files with transaction-level latency data

> [!NOTE]
> Summary table: `../lab_results/summary/env1_summary.csv`

## Lab Questions Addressed

This environment answers the following lab questions:

1. **Request/Response Delay**: Average latency for a 10-byte readout across 30 transactions
2. **Packet Loss Impact**: Comparison of CoAP (confirmable vs non-confirmable) vs HTTP under 0%, 3%, 5%, and 10% packet loss
3. **Message Exchange**: Network captures show exact messages exchanged between device and application
4. **Quality of Service Effect**: Demonstrates how confirmable vs non-confirmable affects latency

## Key Metrics

> [!TIP]
> Review these metrics carefully when analyzing results to understand performance trade-offs between protocols.

The tests measure:
- Individual transaction latencies (ms)
- Average latency per test condition
- Success/failure rates
- End-to-end vs individual protocol latencies
