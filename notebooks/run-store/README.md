# Run store

`notebooks/protocol_performance.ipynb` writes one directory per ingest or live run:

```
notebooks/run-store/<YYYYMMDDTHHMMSSZ>/
├── metadata.json       # timestamp, git commit, host, parameters, capture links
├── transactions.csv    # one row per transaction
├── summary.csv         # means and payload sizes per condition
├── lab_tables.json     # Environment 1 and 2 tables, script clock and tshark
├── captures/           # raw .pcapng (gitignored), open these in Wireshark
│   └── README.md
└── figures/            # plots from the notebook (gitignored)
```

`index.jsonl` and `latest.json` in this directory are a short catalog. They are rewritten when a run is added.

CSV and JSON are the versionable record. Commit a run directory if you want that history in git. Do not expect the `.pcapng` files to be committed: `*.pcapng` is gitignored. `metadata.json` still lists each capture under `captures[].stored_as` and `captures[].original_path`.

## What a row means

`transactions.csv` is the source of truth. `summary.csv` and `lab_tables.json` are rebuilt from it.

Identity columns, taken from the `test.sh` filenames:

| Column | Meaning |
| --- | --- |
| `environment` | `env1` (CoAP + HTTP) or `env2` (CoAP + MQTT) |
| `scenario` | `coap`, `http`, `mqtt`, `coap_http`, or `coap_mqtt` |
| `coap_type` | `confirmable`, `non-confirmable`, or empty |
| `mqtt_qos` | `0`, `1`, `2`, or empty |
| `packet_loss_pct` | Configured `tc netem` loss: 0, 3, 5, or 10. This is an input, not a measured loss count. |
| `transaction` | 1-based index from the script, or capture order when there is no CSV row |
| `example_data` | `True` only for the synthetic fixture |

Timing columns. They are left blank when that source did not produce a number. Blank is not zero.

| Column | Meaning |
| --- | --- |
| `script_latency_ms` | Headline delay from `test.sh`: the client clock around the command, or the sum of the two commands for a combined trial |
| `script_coap_latency_ms`, `script_http_latency_ms`, `script_mqtt_latency_ms` | Component clocks when the script recorded them |
| `tshark_latency_ms` | Headline delay from `frame.time_epoch` |
| `tshark_latency_kind` | `coap_rtt`, `http_rtt`, `mqtt_delivery`, or `e2e` |
| `tshark_mqtt_handshake_latency_ms` | PUBLISH to PUBACK (QoS 1) or PUBCOMP (QoS 2). Not the device-to-application delay |
| `coap_payload_bytes`, `http_payload_bytes`, `mqtt_payload_bytes` | Measured from the capture. Empty when tshark did not report a length |
| `mqtt_payload_bytes_configured` | `10` for MQTT-only (`date +%Y-%m-%d` in `test.sh`) or `9` for the combined publish (`timestamp`). This is the script text, not a measurement |

The lab asks for 30 transactions and Wireshark timestamps. `n_script` / `n_tshark` in `summary.csv` are the counts actually stored. The tshark tables in `lab_tables.json` are the ones that use packet timestamps. The script tables are the fallback when a capture could not be timed.

## Lab tables

`lab_tables.json` has script and tshark copies of:

- Environment 1 request/response delay, including the confirmable CoAP + HTTP end-to-end mean
- Environment 1 packet loss versus confirmable and non-confirmable CoAP
- Environment 2 device-to-application delay for MQTT QoS 0, 1, and 2
- Environment 2 packet loss versus confirmable CoAP and each MQTT QoS
- CoAP-based MQTT versus HTTP at the same loss rates

Missing loss rates stay null. They are not filled with 0.
