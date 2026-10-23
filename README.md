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
├── notebooks/                         (result collection notebook)
│   ├── protocol_performance.ipynb
│   ├── iot_results.py
│   ├── sample_lab_results/          (synthetic example only)
│   └── run-store/                   (timestamped CSV/JSON runs)
├── requirements.txt                   (notebook Python packages)
├── compose.yaml                       (device, edge, application, MQTT, capture, Jupyter)
├── docker/                            (images, netem sweep, CoAP edge server)
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

## Notebook: lab tables and saved runs

`notebooks/protocol_performance.ipynb` collects a run and builds the tables the lab asks for. It does not reimplement the trials.

- **Ingest** reads `lab_results/` after `test.sh` or `lab_test.sh` has finished: the latency CSVs and the `.pcapng` captures.
- **Live** runs `environment-1-coap-http/test.sh` and `environment-2-coap-mqtt/test.sh` from their own directories, then ingests `lab_results/`. Live mode needs the CoAP, HTTP, and MQTT tools, `tshark`, and passwordless `sudo` for `tc netem`. If those are missing, the notebook says so and ingests whatever results already exist. It does not invent timings.

Wireshark latency uses tshark, not a Python packet library:

```bash
tshark -r capture.pcapng -T fields -e frame.time_epoch -e coap.mid -e coap.type -e mqtt.msgtype ... -E separator=,
```

The notebook also passes decode-as for CoAP on UDP 5683, HTTP on TCP 8080, and MQTT on TCP 1883, which is what `test.sh` uses. `tshark` comes from `utils/install-dependencies.sh`. Parsing a file only needs read permission. Capturing on `lo`, which `test.sh` does, needs dumpcap permission or root. If `tshark` is missing, script-clock columns are still stored and the Wireshark columns are left empty.

Each run is a directory under `notebooks/run-store/<timestamp>/`:

- `metadata.json` records the time, environment, protocol, CoAP type or MQTT QoS, loss percent, payload size when known, transaction count, git commit, and host.
- `transactions.csv` and `summary.csv` are the versionable numbers. `lab_tables.json` is the loss-versus-latency tables.
- `captures/` holds the raw `.pcapng` files so they still open in Wireshark for the trace screenshots. Paths are linked from `metadata.json`. `*.pcapng` is gitignored.

`notebooks/sample_lab_results/` is **example data**: synthetic CSVs with 3 transactions and no captures, so the notebook can be opened before a lab run. It is labeled `EXAMPLE_DATA.json`. Do not put those numbers in the report.

```bash
python3 -m pip install -r requirements.txt
jupyter notebook notebooks/protocol_performance.ipynb
```

See `notebooks/run-store/README.md` for the column list. The scripts record a client-side clock and, separately, a capture. They do not record throughput. Packet loss is the configured netem rate. CoAP and HTTP payload sizes are measured only when tshark can see them. MQTT payload sizes configured by `test.sh` are the 10-byte date string and the 9-byte word `timestamp`.

## Containerized lab

Compose runs the same device → edge → application topology on one host. It is not Kubernetes. Two user-defined bridges keep the access hop separate from the core:

| Service | Role | Address |
| --- | --- | --- |
| `device` | `coap-client`, `curl`, `mosquitto_pub`, all addressed to the edge. | `10.10.0.10` on `access` |
| `edge` | CoAP `GET /time` returns the 10-byte body `0123456789`. DNATs TCP 8080 and 1883 to the core and masquerades the return path. | `10.10.0.20` on `access`, `10.20.0.20` on `core` |
| `application` | HTTP `GET /time` returns that same body. `mosquitto_sub` runs here during MQTT trials. | `10.20.0.30` on `core` |
| `mqtt` | Eclipse Mosquitto, anonymous, port 1883. | `10.20.0.40` on `core` |
| `capture` | `tshark` in the device network namespace (`NET_RAW` and `NET_ADMIN`). | shares `device` |
| `jupyter` | This notebook, with a Docker CLI on the host socket. | `127.0.0.1:8888` |

The device sends CoAP, HTTP, and MQTT to the edge (`10.10.0.20`). Docker drops a packet whose destination is a container IP unless it arrives on that container's own bridge, so the device cannot address `10.20.0.30` or `10.20.0.40` directly. The edge DNATs TCP 8080 to the application and TCP 1883 to the broker, and masquerades the source so the replies return across the access hop. CoAP is answered by the edge. Loss therefore applies to every device packet. The sweep does not call `test.sh` (those scripts use localhost and `tc` on `lo`). It writes the same CSV names, headers, and `Average` footer, so the notebook ingests `lab_results/` unchanged. The client clock is `date +%s.%N` inside the device container.

### Bring the stack up

From the repository root, on Linux or Docker Desktop:

```bash
docker compose up -d --build --wait
```

Jupyter is at <http://127.0.0.1:8888> (empty token, bound to localhost). Open `notebooks/protocol_performance.ipynb`. The socket mount is root-equivalent on the Docker host; do not publish Jupyter beyond localhost without setting `JUPYTER_TOKEN`.

### Run a sweep

The stack has to be up already. This applies `tc netem` on the access interface of **both** the device and the edge (both directions, without an IFB ingress qdisc), captures each trial to `lab_results/*/captures/*.pcapng`, and writes the latency CSVs.

```bash
sh docker/sweep.sh
LOSS_PCTS="0 3 5 10" TRANSACTIONS=30 SLEEP_S=1 SWEEP=both sh docker/sweep.sh
```

`SWEEP` is `env1`, `env2`, or `both`. A one-transaction check is:

```bash
LOSS_PCTS=0 TRANSACTIONS=1 SLEEP_S=0 sh docker/sweep.sh
```

Loss is installed for every point, including 0%. The script removes the qdiscs when it exits. In the notebook, leave `RUN_DOCKER_SWEEP = False` unless this stack is already up and `docker` can see it. The notebook runs `sh docker/sweep.sh`. It does not run `docker compose up`, because Compose would bind-mount the container's paths instead of this checkout.

Then ingest `lab_results/` (`MODE = "ingest"`). A real tree is preferred over the example fixture.

CoAP and HTTP bodies in this stack are exactly 10 bytes (`0123456789`). MQTT payloads match `test.sh`: `date +%Y-%m-%d` (10 bytes) on the MQTT-only trial and the word `timestamp` (9 bytes) on the combined trial.

### Packet loss and Docker Desktop

`tc netem` runs in the container network namespace, which uses the **Linux kernel under Docker**, not the macOS network stack. There is no `tc` on macOS. Docker Desktop (including Apple Silicon) runs a Linux VM; that VM is where netem is installed. The images are Debian and the official Mosquitto image, both published for amd64 and arm64. The compose file does not pin `linux/amd64`.

`cap_add: NET_ADMIN` is set on the device and the edge. The capture service adds `NET_RAW` as well. Privileged mode is not required. `network_mode: service:device` is supported on Docker Desktop.

Limits that change the numbers:

- **Both directions.** N% on the device egress and N% on the edge access egress drops more round trips than one qdisc of N% on `lo`. Independent loss on each direction hits about `1 - (1 - N/100)^2` of round trips. The original scripts put a single netem qdisc on `lo`. Say which setup a table came from.
- **No IFB.** Ingress netem needs the `ifb` module. Desktop's VM often does not have it, so the sweep does not use ingress. Egress on both ends is the substitute.
- **The kernel has to include `sch_netem`.** Containers share the host kernel. `NET_ADMIN` cannot add a scheduler the kernel was built without (`CONFIG_NET_SCH_NETEM`). The sweep runs `tc qdisc replace ... netem` and exits with the kernel error if that fails. Desktop's VM usually has `sch_netem`. A stripped or nested cloud kernel often does not.
- **The clock is noisier** than a bare-metal loopback test (hypervisor, virtio, and on Apple Silicon the arm64 VM). Compare 0/3/5/10% on the same machine. Do not mix a Desktop sweep and a Linux `lo` sweep in one table.
- **Access-side capture does not see the broker's PUBLISH to the subscriber.** That hop stays on the core bridge, after the edge DNAT. The device capture still has CoAP, the HTTP request and response (the edge forwards them), and the MQTT publisher handshake (`PUBACK` / `PUBCOMP`). The notebook's MQTT delivery column needs the forwarded PUBLISH, so it can be empty for these captures. The CSV client clock is still recorded. Do not treat a missing delivery cell as zero.
- **Two iptables backends.** If containers on the same Compose network cannot reach each other, check for a leftover `iptables-legacy` filter whose `FORWARD` policy is `DROP` while Docker is programming nftables. `sudo iptables-legacy -S FORWARD` shows it. A current Docker Engine that uses only one backend does not need this.
- **Stopping a capture sends SIGTERM** so tshark can flush the `.pcapng`. The files are gitignored, as are the CSVs under `lab_results/`.

`SKIP_NETEM=1 sh docker/sweep.sh` skips `tc` and is only a connectivity check. It writes `lab_results/NETEM_SKIPPED.txt`. Do not put those rows in the report.

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