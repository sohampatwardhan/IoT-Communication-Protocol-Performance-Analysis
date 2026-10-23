"""Write a small synthetic lab_results tree for the notebook.

The numbers are not measurements. They only exercise the same CSV layout that
``environment-*/test.sh`` writes, with 3 transactions instead of 30 and with
no packet captures. ``EXAMPLE_DATA.json`` marks the tree.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 6510
TRANSACTIONS = 3
LOSSES = (0, 3, 5, 10)

# (base_ms, extra_ms per 1% loss). Noise is small so the loss ordering stays obvious.
_PROFILES = {
    ("coap", "confirmable"): (14.0, 2.2),
    ("coap", "non-confirmable"): (6.0, 0.35),
    ("http", ""): (22.0, 1.1),
    ("mqtt", 0): (5.0, 0.25),
    ("mqtt", 1): (11.0, 1.4),
    ("mqtt", 2): (20.0, 2.8),
}


def write_example_fixture(destination: Path) -> Path:
    destination = Path(destination)
    if destination.exists():
        for child in destination.rglob("*"):
            if child.is_file():
                child.unlink()
    rng = random.Random(SEED)
    env1_latency = destination / "env1" / "latencies"
    env2_latency = destination / "env2" / "latencies"
    summary_dir = destination / "summary"
    for folder in (env1_latency, env2_latency, summary_dir):
        folder.mkdir(parents=True, exist_ok=True)

    env1_simple = {
        "coap_confirmable": _series(rng, "coap", "confirmable"),
        "coap_non-confirmable": _series(rng, "coap", "non-confirmable"),
        "http": _series(rng, "http", ""),
    }
    for loss in LOSSES:
        _write_simple(env1_latency / f"coap_confirmable_{loss}pct.csv", env1_simple["coap_confirmable"][loss])
        _write_simple(
            env1_latency / f"coap_non-confirmable_{loss}pct.csv",
            env1_simple["coap_non-confirmable"][loss],
        )
        _write_simple(env1_latency / f"http_{loss}pct.csv", env1_simple["http"][loss])
        coap_part = _series(rng, "coap", "confirmable")[loss]
        http_part = _series(rng, "http", "")[loss]
        _write_combined(
            env1_latency / f"coap_confirmable_http_{loss}pct.csv",
            coap_part,
            http_part,
            "HTTP_Latency_ms",
        )

    env2_coap = _series(rng, "coap", "confirmable")
    env2_mqtt = {qos: _series(rng, "mqtt", qos) for qos in (0, 1, 2)}
    for loss in LOSSES:
        _write_simple(env2_latency / f"coap_confirmable_{loss}pct.csv", env2_coap[loss])
        for qos in (0, 1, 2):
            _write_simple(env2_latency / f"mqtt_qos{qos}_{loss}pct.csv", env2_mqtt[qos][loss])
            coap_part = _series(rng, "coap", "confirmable")[loss]
            mqtt_part = _series(rng, "mqtt", qos)[loss]
            _write_combined(
                env2_latency / f"coap_confirmable_mqtt_qos{qos}_{loss}pct.csv",
                coap_part,
                mqtt_part,
                "MQTT_Latency_ms",
            )

    _write_env1_summary(summary_dir / "env1_summary.csv", env1_latency)
    _write_env2_summary(summary_dir / "env2_summary.csv", env2_latency)
    (destination / "EXAMPLE_DATA.json").write_text(
        json.dumps(
            {
                "example_data": True,
                "do_not_use_for_lab_report": True,
                "description": (
                    "Synthetic latency CSVs in the shape environment-*/test.sh writes. "
                    "Not measured. No packet captures. Three transactions per series, "
                    "not the lab's 30."
                ),
                "transactions_per_series": TRANSACTIONS,
                "seed": SEED,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (destination / "README.md").write_text(
        """# Example data (not a measurement)

These CSVs are **synthetic**. They copy the column layout of `environment-1-coap-http/test.sh` and `environment-2-coap-mqtt/test.sh` so the notebook can be opened before any lab run exists.

- Not captured on a network, and not timed with Wireshark or `date`.
- 3 transactions per series, not the lab's 30.
- No `.pcapng` files.
- Do not paste these numbers into the TELE 6510 report.

Regenerate with:

```bash
python notebooks/iot_results.py write-example
```
""",
        encoding="utf-8",
    )
    return destination


def _series(rng: random.Random, kind: str, variant) -> dict[int, list[float]]:
    base, slope = _PROFILES[(kind, variant)]
    out = {}
    for loss in LOSSES:
        samples = []
        for index in range(TRANSACTIONS):
            noise = rng.uniform(-0.3, 0.3)
            samples.append(round(base + slope * loss + noise + index * 0.05, 6))
        out[loss] = samples
    return out


def _write_simple(path: Path, samples: list[float]) -> None:
    lines = [
        "# EXAMPLE DATA — synthetic, not a measurement. See README in the sample_lab_results directory.",
        "Transaction,Timestamp,Latency_ms",
    ]
    for index, latency in enumerate(samples, start=1):
        lines.append(f"{index},2026-01-15-12:00:{index:02d},{latency:.6f}")
    lines.append(f"Average,{_mean(samples):.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_combined(path: Path, first: list[float], second: list[float], second_column: str) -> None:
    lines = [
        "# EXAMPLE DATA — synthetic, not a measurement. See README in the sample_lab_results directory.",
        f"Transaction,Timestamp,CoAP_Latency_ms,{second_column},Total_Latency_ms",
    ]
    totals = []
    for index, (coap_ms, hop_ms) in enumerate(zip(first, second), start=1):
        total = coap_ms + hop_ms
        totals.append(total)
        lines.append(
            f"{index},2026-01-15-12:00:{index:02d},{coap_ms:.6f},{hop_ms:.6f},{total:.6f}"
        )
    lines.append(f"Average,{_mean(first):.6f},{_mean(second):.6f},{_mean(totals):.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _average_field(path: Path, index: int) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Average,"):
            return line.split(",")[index]
    raise RuntimeError(f"no Average row in {path}")


def _write_env1_summary(path: Path, latency_dir: Path) -> None:
    lines = [
        "# EXAMPLE DATA — synthetic, not a measurement.",
        "Packet Loss %,Confirmable CoAP Latency (ms),Non-confirmable CoAP Latency (ms),HTTP Latency (ms),End-to-End Latency (ms)",
    ]
    for loss in LOSSES:
        fields = [
            _average_field(latency_dir / f"coap_confirmable_{loss}pct.csv", 1),
            _average_field(latency_dir / f"coap_non-confirmable_{loss}pct.csv", 1),
            _average_field(latency_dir / f"http_{loss}pct.csv", 1),
            _average_field(latency_dir / f"coap_confirmable_http_{loss}pct.csv", 3),
        ]
        lines.append(f"{loss}," + ",".join(fields))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_env2_summary(path: Path, latency_dir: Path) -> None:
    lines = [
        "# EXAMPLE DATA — synthetic, not a measurement.",
        "Packet Loss %,QoS Level,Confirmable CoAP Latency (ms),MQTT Latency (ms),End-to-End Latency (ms)",
    ]
    for loss in LOSSES:
        for qos in (0, 1, 2):
            fields = [
                _average_field(latency_dir / f"coap_confirmable_{loss}pct.csv", 1),
                _average_field(latency_dir / f"mqtt_qos{qos}_{loss}pct.csv", 1),
                _average_field(latency_dir / f"coap_confirmable_mqtt_qos{qos}_{loss}pct.csv", 3),
            ]
            lines.append(f"{loss},{qos}," + ",".join(fields))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
