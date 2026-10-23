"""Collect TELE 6510 protocol-test results and map them onto the lab questions.

The shell scripts under ``environment-1-coap-http`` and ``environment-2-coap-mqtt``
already run the trials. They write per-transaction latency CSVs and tshark
``.pcapng`` captures under ``lab_results/``. This module does not reimplement
those trials. Live mode runs the existing ``test.sh`` files. Ingest mode reads
what they wrote.

Wireshark timing comes from ``tshark -T fields`` (frame.time_epoch and the
CoAP / HTTP / MQTT fields), not from a Python packet library. Each run keeps
the raw ``.pcapng`` next to its tables so it still opens in Wireshark.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 1
LAB_TRANSACTION_COUNT = 30
LOSS_RATES = (0, 3, 5, 10)
COAP_PORT = 5683
HTTP_PORT = 8080
MQTT_PORT = 1883

Q_ENV1_1 = (
    "What is the request/response delay at the application when sending a simple "
    "10-byte (or less) readout? (use Wireshark timestamps, run 30 transactions "
    "and use the average)."
)
Q_ENV1_2 = (
    "For uniform 0%, 3%, 5% and 10% packet loss introduced at the access side, "
    "make a table packet loss vs latency for confirmable and non-confirmable CoAP."
)
Q_ENV2_1 = (
    "What is the delay between the device and the application when sending a simple "
    "10-byte (or less) readout? (use Wireshark timestamps, run 30 transactions "
    "and use the average)."
)
Q_ENV2_2 = (
    "For uniform 0%, 3%, 5% and 10% packet loss introduced at the access side, "
    "make a table packet loss vs latency for confirmable CoAP and each MQTT quality "
    "level (at most once, at least once, exactly once)."
)
Q_ENV2_4 = (
    "How does CoAP-based MQTT compare against HTTP for the same network conditions?"
)

# What environment-*/test.sh actually sends. Payload lengths below are the
# MQTT application payloads hardcoded in those scripts. CoAP and HTTP body
# sizes are whatever the servers return; they are measured only from a capture.
SCRIPT_DEFAULTS = {
    "packet_loss_rates_pct": list(LOSS_RATES),
    "transactions_per_condition": LAB_TRANSACTION_COUNT,
    "inter_transaction_sleep_s": 1,
    "resource_path": "time",
    "interface": "lo",
    "coap_server": "[::1]:5683",
    "http_url": "http://localhost:8080/time",
    "mqtt_broker": "localhost:1883",
    "mqtt_topic": "iot/time",
    "mqtt_payload_bytes_configured": {
        "mqtt": 10,
        "coap_mqtt": 9,
    },
    "mqtt_payload_notes": {
        "mqtt": 'run_mqtt_test publishes `$(date +%Y-%m-%d)`, which is 10 bytes.',
        "coap_mqtt": 'run_coap_mqtt_test publishes the literal "timestamp", which is 9 bytes.',
        "coap": "coap-client GETs /time. The script does not set the response body size.",
        "http": "curl GETs /time. The script does not set the response body size.",
    },
}

TEST_PROCEDURE = {
    "env1": {
        "name": "CoAP + HTTP",
        "script": "environment-1-coap-http/test.sh",
        "coap_confirmable": "coap-client -m get coap://[::1]:5683/time",
        "coap_nonconfirmable": "coap-client -m get -N coap://[::1]:5683/time",
        "http": "curl http://localhost:8080/time",
        "combined": "Confirmable CoAP GET, then curl, in that order.",
        "capture": "tshark -i lo with a port filter, written to a .pcapng file.",
        "packet_loss": "tc netem loss on lo at 0%, 3%, 5%, and 10% (utils/network-control.sh).",
    },
    "env2": {
        "name": "CoAP + MQTT",
        "script": "environment-2-coap-mqtt/test.sh",
        "coap": "confirmable coap-client GET coap://[::1]:5683/time",
        "mqtt": "mosquitto_sub -t iot/time -q <qos>, then mosquitto_pub -t iot/time -q <qos> -m $(date +%Y-%m-%d)",
        "combined": 'Confirmable CoAP GET, then mosquitto_pub -m "timestamp" -q <qos>.',
        "qos": {"0": "at most once", "1": "at least once", "2": "exactly once"},
        "capture": "tshark -i lo with a port filter, written to a .pcapng file.",
        "packet_loss": "tc netem loss on lo at 0%, 3%, 5%, and 10%.",
    },
}

TIMING_DEFINITIONS = {
    "script_clock": (
        "test.sh takes date +%s.%N immediately before and after each client "
        "command and stores the difference in milliseconds. That includes "
        "process startup, not only on-wire time. The lab asks for Wireshark "
        "timestamps; use this when no capture timing is available."
    ),
    "tshark": (
        "frame.time_epoch from `tshark -r <pcapng> -T fields`. "
        "CoAP latency is the request frame to the matching response (same token, "
        "else same message id, else the next response). "
        "HTTP latency is the request to the response on the same tcp.stream. "
        "MQTT device-to-application latency is the client PUBLISH (TCP destination "
        "port 1883) to the broker's PUBLISH toward the subscriber (TCP source port "
        "1883). The QoS handshake (PUBLISH to PUBACK or PUBCOMP) is stored separately "
        "and is not the headline delay. "
        "Combined end-to-end latency is the CoAP request epoch to the HTTP response "
        "epoch or the MQTT delivery epoch, paired in order."
    ),
}

ENV_SCRIPTS = {
    "env1": "environment-1-coap-http/test.sh",
    "env2": "environment-2-coap-mqtt/test.sh",
}
ENV1_TOOLS = ("coap-client", "coap-server", "curl", "http-server", "bc", "tshark", "tc")
ENV2_TOOLS = (
    "coap-client",
    "coap-server",
    "mosquitto",
    "mosquitto_pub",
    "mosquitto_sub",
    "bc",
    "tshark",
    "tc",
)
TOOL_NAMES = (
    "coap-client",
    "coap-server",
    "curl",
    "http-server",
    "mosquitto",
    "mosquitto_pub",
    "mosquitto_sub",
    "tshark",
    "bc",
    "tc",
    "bash",
    "sudo",
)

PROTOCOL_LABEL = {
    "coap": "CoAP",
    "http": "HTTP",
    "mqtt": "MQTT",
    "coap_http": "CoAP+HTTP",
    "coap_mqtt": "CoAP+MQTT",
}

TSHARK_FIELDS = (
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "ip.src",
    "ip.dst",
    "ipv6.src",
    "ipv6.dst",
    "tcp.srcport",
    "tcp.dstport",
    "udp.srcport",
    "udp.dstport",
    "tcp.stream",
    "coap.type",
    "coap.code",
    "coap.mid",
    "coap.token",
    "coap.opt.uri_path",
    "data.len",
    "http.request.method",
    "http.request.uri",
    "http.response.code",
    "http.content_length",
    "mqtt.msgtype",
    "mqtt.qos",
    "mqtt.msgid",
    "mqtt.topic",
    "mqtt.msg",
    "mqtt.len",
)

TRANSACTION_COLUMNS = (
    "run_id",
    "example_data",
    "environment",
    "scenario",
    "protocol",
    "coap_type",
    "mqtt_qos",
    "packet_loss_pct",
    "transaction",
    "script_timestamp",
    "script_latency_ms",
    "script_coap_latency_ms",
    "script_http_latency_ms",
    "script_mqtt_latency_ms",
    "script_total_latency_ms",
    "script_reported_average_ms",
    "script_reported_coap_average_ms",
    "script_reported_http_average_ms",
    "script_reported_mqtt_average_ms",
    "tshark_index",
    "tshark_request_epoch",
    "tshark_response_epoch",
    "tshark_latency_ms",
    "tshark_latency_kind",
    "tshark_coap_latency_ms",
    "tshark_http_latency_ms",
    "tshark_mqtt_delivery_latency_ms",
    "tshark_mqtt_handshake_latency_ms",
    "coap_payload_bytes",
    "http_payload_bytes",
    "mqtt_payload_bytes",
    "mqtt_payload_bytes_configured",
    "capture_file",
    "source_csv",
    "alignment_note",
)

SUMMARY_COLUMNS = (
    "run_id",
    "example_data",
    "environment",
    "scenario",
    "protocol",
    "coap_type",
    "mqtt_qos",
    "packet_loss_pct",
    "n_script",
    "n_tshark",
    "mean_script_ms",
    "mean_tshark_ms",
    "median_script_ms",
    "median_tshark_ms",
    "min_script_ms",
    "max_script_ms",
    "min_tshark_ms",
    "max_tshark_ms",
    "stdev_script_ms",
    "stdev_tshark_ms",
    "mean_script_coap_ms",
    "mean_script_http_ms",
    "mean_script_mqtt_ms",
    "mean_tshark_coap_ms",
    "mean_tshark_http_ms",
    "mean_tshark_mqtt_delivery_ms",
    "mean_tshark_mqtt_handshake_ms",
    "script_reported_average_ms",
    "coap_payload_bytes_measured",
    "http_payload_bytes_measured",
    "mqtt_payload_bytes_measured",
    "mqtt_payload_bytes_configured",
    "capture_file",
    "source_csv",
)

_COAP_TYPE = r"confirmable|non-confirmable"
_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"^coap_(?P<coap_type>{_COAP_TYPE})_mqtt_qos(?P<qos>\d+)_(?P<loss>\d+)pct\.csv$"), "coap_mqtt"),
    (re.compile(rf"^coap_(?P<coap_type>{_COAP_TYPE})_http_(?P<loss>\d+)pct\.csv$"), "coap_http"),
    (re.compile(rf"^coap_(?P<coap_type>{_COAP_TYPE})_(?P<loss>\d+)pct\.csv$"), "coap"),
    (re.compile(rf"^mqtt_qos(?P<qos>\d+)_(?P<loss>\d+)pct\.csv$"), "mqtt"),
    (re.compile(rf"^http_(?P<loss>\d+)pct\.csv$"), "http"),
    (re.compile(rf"^coap_mqtt_(?P<coap_type>{_COAP_TYPE})_qos(?P<qos>\d+)_(?P<loss>\d+)pct\.pcap(?:ng)?$"), "coap_mqtt"),
    (re.compile(rf"^coap_http_(?P<coap_type>{_COAP_TYPE})_(?P<loss>\d+)pct\.pcap(?:ng)?$"), "coap_http"),
    (re.compile(rf"^coap_(?P<coap_type>{_COAP_TYPE})_(?P<loss>\d+)pct\.pcap(?:ng)?$"), "coap"),
    (re.compile(rf"^mqtt_qos(?P<qos>\d+)_(?P<loss>\d+)pct\.pcap(?:ng)?$"), "mqtt"),
    (re.compile(rf"^http_standard_(?P<loss>\d+)pct\.pcap(?:ng)?$"), "http"),
)

_MQTT_TYPE_NAMES = (
    ("PUBCOMP", 7),
    ("PUBREL", 6),
    ("PUBREC", 5),
    ("PUBACK", 4),
    ("PUBLISH", 3),
    ("CONNACK", 2),
    ("CONNECT", 1),
    ("UNSUBSCRIBE", 10),
    ("UNSUBACK", 11),
    ("SUBSCRIBE", 8),
    ("SUBACK", 9),
    ("PINGRESP", 13),
    ("PINGREQ", 12),
    ("DISCONNECT", 14),
)


class IngestError(Exception):
    """The source tree has nothing this notebook can store."""


class ParseError(ValueError):
    """One latency CSV is not in the shape test.sh writes."""


class TsharkError(RuntimeError):
    """tshark could not export fields for a capture."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_store() -> Path:
    return repo_root() / "notebooks" / "run-store"


def default_source(repo: Path | None = None) -> Path:
    """Prefer a real ``lab_results`` tree, otherwise the labeled example fixture."""
    root = repo or repo_root()
    lab = root / "lab_results"
    if _has_results(lab):
        return lab
    return root / "notebooks" / "sample_lab_results"


def _has_results(path: Path) -> bool:
    if not path.is_dir():
        return False
    if any(path.glob("env*/latencies/*.csv")):
        return True
    if any(path.glob("env*/captures/*.pcap")) or any(path.glob("env*/captures/*.pcapng")):
        return True
    return False


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_result_name(filename: str) -> dict | None:
    """Map a ``test.sh`` latency CSV or capture filename onto its conditions."""
    for pattern, scenario in _NAME_PATTERNS:
        match = pattern.match(filename)
        if not match:
            continue
        groups = match.groupdict()
        qos = groups.get("qos")
        return {
            "scenario": scenario,
            "protocol": PROTOCOL_LABEL[scenario],
            "coap_type": groups.get("coap_type") or "",
            "mqtt_qos": int(qos) if qos is not None else None,
            "packet_loss_pct": int(groups["loss"]),
        }
    return None


def environment_from_path(path: Path) -> str:
    parts = set(path.parts)
    if "env1" in parts:
        return "env1"
    if "env2" in parts:
        return "env2"
    raise ParseError(f"Cannot tell env1 from env2 for {path}")


def configured_mqtt_payload(scenario: str) -> int | None:
    return SCRIPT_DEFAULTS["mqtt_payload_bytes_configured"].get(scenario)


def _cell(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return None
    return float(text)


def _parse_int(value: object) -> int | None:
    number = _parse_float(value)
    if number is None or math.isnan(number):
        return None
    return int(number)


def _read_csv_rows(path: Path) -> list[list[str]]:
    lines = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(line)
    if not lines:
        raise ParseError(f"{path} has no CSV rows")
    return list(csv.reader(io.StringIO("\n".join(lines))))


def _blank_measurement() -> dict:
    return {
        "request_epoch": None,
        "response_epoch": None,
        "latency_ms": None,
        "kind": "",
        "coap_latency_ms": None,
        "http_latency_ms": None,
        "mqtt_delivery_latency_ms": None,
        "mqtt_handshake_latency_ms": None,
        "coap_payload_bytes": None,
        "http_payload_bytes": None,
        "mqtt_payload_bytes": None,
        "alignment_note": "",
    }


def parse_script_csv(path: Path) -> dict:
    """Parse one latency CSV written by ``test.sh``.

    The scripts append an ``Average,...`` footer that does not include the
    timestamp column, so it is not aligned with the header. Stats are computed
    from the transaction rows. The footer is kept only as
    ``script_reported_average_*``.
    """
    meta = parse_result_name(path.name)
    if meta is None:
        raise ParseError(f"Unrecognized latency file name: {path.name}")
    meta = dict(meta)
    meta["environment"] = environment_from_path(path)
    table = _read_csv_rows(path)
    header = [cell.strip() for cell in table[0]]
    rows = []
    reported: dict[str, float | None] = {}
    skipped = 0
    for raw in table[1:]:
        if not raw or not raw[0].strip():
            continue
        if raw[0].strip().lower() == "average":
            reported = _parse_average_footer(raw, meta["scenario"])
            continue
        record = {header[i]: raw[i].strip() if i < len(raw) else "" for i in range(len(header))}
        transaction = record.get("Transaction", "")
        if not transaction.isdigit():
            skipped += 1
            continue
        try:
            rows.append(_script_row(record, meta, int(transaction)))
        except ValueError:
            skipped += 1
    rows.sort(key=lambda item: item["transaction"])
    return {"meta": meta, "rows": rows, "reported": reported, "skipped": skipped, "source": path}


def _parse_average_footer(cells: list[str], scenario: str) -> dict[str, float | None]:
    numbers = [_parse_float(cell) for cell in cells[1:]]
    reported: dict[str, float | None] = {
        "headline": None,
        "coap": None,
        "http": None,
        "mqtt": None,
    }
    if scenario == "coap_http":
        reported["coap"] = numbers[0] if len(numbers) > 0 else None
        reported["http"] = numbers[1] if len(numbers) > 1 else None
        reported["headline"] = numbers[2] if len(numbers) > 2 else None
    elif scenario == "coap_mqtt":
        reported["coap"] = numbers[0] if len(numbers) > 0 else None
        reported["mqtt"] = numbers[1] if len(numbers) > 1 else None
        reported["headline"] = numbers[2] if len(numbers) > 2 else None
    elif numbers:
        reported["headline"] = numbers[0]
    return reported


def _script_row(record: dict, meta: dict, transaction: int) -> dict:
    latency = _parse_float(record.get("Latency_ms"))
    coap = _parse_float(record.get("CoAP_Latency_ms"))
    http = _parse_float(record.get("HTTP_Latency_ms"))
    mqtt = _parse_float(record.get("MQTT_Latency_ms"))
    total = _parse_float(record.get("Total_Latency_ms"))
    scenario = meta["scenario"]
    if scenario in {"coap_http", "coap_mqtt"}:
        headline = total
    else:
        headline = latency
        if scenario == "coap":
            coap = latency
        elif scenario == "http":
            http = latency
        elif scenario == "mqtt":
            mqtt = latency
    if headline is None:
        raise ValueError("missing latency")
    return {
        "transaction": transaction,
        "script_timestamp": record.get("Timestamp", ""),
        "script_latency_ms": headline,
        "script_coap_latency_ms": coap,
        "script_http_latency_ms": http,
        "script_mqtt_latency_ms": mqtt,
        "script_total_latency_ms": total if scenario in {"coap_http", "coap_mqtt"} else headline,
    }


def build_tshark_command(pcap: Path, binary: str = "tshark") -> list[str]:
    """Field export used to turn a lab capture into per-transaction timestamps.

    HTTP is decoded on port 8080 and CoAP on 5683 because those are the ports
    ``test.sh`` uses, and Wireshark's defaults would miss HTTP on 8080.
    """
    command = [
        binary,
        "-r",
        str(pcap),
        "-d",
        f"udp.port=={COAP_PORT},coap",
        "-d",
        f"tcp.port=={HTTP_PORT},http",
        "-d",
        f"tcp.port=={MQTT_PORT},mqtt",
        "-Y",
        "coap or http or mqtt",
        "-T",
        "fields",
        "-E",
        "separator=,",
        "-E",
        "quote=d",
        "-E",
        "header=y",
        "-E",
        "occurrence=f",
    ]
    for field in TSHARK_FIELDS:
        command.extend(["-e", field])
    return command


def tshark_command_template() -> str:
    return " ".join(build_tshark_command(Path("{pcapng}")))


def tshark_status() -> dict:
    path = shutil.which("tshark")
    if not path:
        return {
            "available": False,
            "path": None,
            "version": None,
            "reason": (
                "tshark is not on PATH. Install it with utils/install-dependencies.sh "
                "(apt package tshark). Script-clock columns can still be ingested. "
                "Wireshark-timestamp columns stay empty. Any .pcapng files are still "
                "stored so you can open them in Wireshark on a machine that has it."
            ),
        }
    try:
        proc = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "path": path, "version": None, "reason": str(exc)}
    first = ((proc.stdout or proc.stderr or "").splitlines() or [""])[0].strip()
    if proc.returncode != 0:
        return {
            "available": False,
            "path": path,
            "version": first or None,
            "reason": (proc.stderr or proc.stdout or "tshark -v failed").strip()[-500:],
        }
    return {"available": True, "path": path, "version": first, "reason": ""}


def _capture_permission_note() -> tuple[str, bool]:
    """Return a capture-permission note and whether it should block live mode."""
    status = tshark_status()
    if not status["available"]:
        return (
            "tshark is not installed, so capture permission was not checked. "
            "Parsing a pcapng needs tshark; opening the same file in Wireshark does not.",
            False,
        )
    try:
        proc = subprocess.run(
            [status["path"], "-D"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            f"Could not list capture interfaces ({exc}). Reading an existing pcapng does not need capture permission.",
            True,
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return (
            "tshark -D failed, so this user may not be allowed to capture. "
            "Reading an existing pcapng still works. test.sh captures on lo and "
            "needs dumpcap permission or root. "
            + detail,
            True,
        )
    if re.search(r"\blo\b", proc.stdout):
        return (
            "tshark can see interfaces from this process. Live captures use -i lo. "
            "If test.sh cannot open lo, join the wireshark group or run the capture as root.",
            False,
        )
    return ("tshark -D did not list lo. environment test.sh captures with `tshark -i lo`.", True)


def check_tools() -> dict:
    """Report which lab binaries exist. Does not start brokers or change netem."""
    found = {name: shutil.which(name) for name in TOOL_NAMES}
    sudo_ok = False
    sudo_detail = "sudo is not installed"
    if found.get("sudo"):
        proc = subprocess.run(["sudo", "-n", "true"], capture_output=True, text=True, check=False)
        sudo_ok = proc.returncode == 0
        if not sudo_ok:
            sudo_detail = (proc.stderr or proc.stdout or "sudo needs a password").strip()
        else:
            sudo_detail = ""
    tshark = tshark_status()
    blockers = []
    ready = []
    for env, required in (("env1", ENV1_TOOLS), ("env2", ENV2_TOOLS)):
        missing = [tool for tool in required if not found.get(tool)]
        if missing:
            blockers.append(f"{env} missing: {', '.join(missing)}")
            continue
        if not sudo_ok:
            continue
        ready.append(env)
    if not sudo_ok:
        blockers.append(
            "Packet loss uses sudo tc/netem (utils/network-control.sh). "
            f"Non-interactive sudo is not available ({sudo_detail})."
        )
    capture_note, capture_blocks_live = _capture_permission_note()
    if capture_blocks_live:
        blockers.append(capture_note)
        ready = []
    return {
        "tools": found,
        "sudo_noninteractive": sudo_ok,
        "sudo_detail": sudo_detail,
        "tshark": tshark,
        "capture_note": capture_note,
        "live_ready_environments": ready,
        "live_blockers": [item for item in blockers if item],
    }


def parse_tshark_csv(text: str) -> list[dict]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for record in reader:
        if not record:
            continue
        rows.append({key: (value or "").strip() for key, value in record.items() if key})
    return rows


def export_tshark_fields(pcap: Path, timeout: int = 120) -> list[dict]:
    status = tshark_status()
    if not status["available"]:
        raise TsharkError(status["reason"])
    command = build_tshark_command(pcap, binary=status["path"])
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TsharkError(f"tshark timed out after {timeout}s on {pcap.name}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise TsharkError(detail or f"tshark exited {proc.returncode} on {pcap.name}")
    return parse_tshark_csv(proc.stdout)


def _parse_coap_code(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    names = {"GET": 1, "POST": 2, "PUT": 3, "DELETE": 4}
    upper = text.upper()
    if upper in names:
        return names[upper]
    match = re.match(r"(\d+)\.(\d+)", text)
    if match:
        return int(match.group(1)) * 32 + int(match.group(2))
    return None


def _parse_mqtt_type(value: str) -> int | None:
    text = value.strip().upper()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    for name, number in _MQTT_TYPE_NAMES:
        if text == name or text.startswith(name):
            return number
    return None


def _mqtt_payload_length(value: str) -> int | None:
    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}:)+[0-9A-Fa-f]{2}", text):
        return text.count(":") + 1
    return len(text.encode("utf-8"))


def _port_is(row: dict, key: str, port: int) -> bool:
    return _parse_int(row.get(key)) == port


def measurements_from_tshark_rows(rows: list[dict], scenario: str) -> list[dict]:
    """Pair tshark field rows into per-transaction delays for one scenario."""
    if scenario == "coap":
        return _coap_measurements(rows)
    if scenario == "http":
        return _http_measurements(rows)
    if scenario == "mqtt":
        return _mqtt_measurements(rows)
    if scenario == "coap_http":
        return _combine_measurements(_coap_measurements(rows), _http_measurements(rows), "http")
    if scenario == "coap_mqtt":
        return _combine_measurements(_coap_measurements(rows), _mqtt_measurements(rows), "mqtt")
    raise ParseError(f"Unknown scenario {scenario}")


def _coap_measurements(rows: list[dict]) -> list[dict]:
    requests = []
    responses = []
    for index, row in enumerate(rows):
        code = _parse_coap_code(_cell(row, "coap.code"))
        epoch = _parse_float(row.get("frame.time_epoch"))
        if code is None or epoch is None:
            continue
        item = (index, row, code, epoch)
        if 1 <= code <= 31:
            requests.append(item)
        elif code >= 64:
            responses.append(item)
    used: set[int] = set()
    measurements = []
    for _req_index, request, _code, start in requests:
        token = _cell(request, "coap.token")
        mid = _cell(request, "coap.mid")
        match = _first_unused(
            responses,
            used,
            start,
            lambda row: bool(token) and _cell(row, "coap.token") == token,
        )
        if match is None and mid:
            match = _first_unused(
                responses,
                used,
                start,
                lambda row: _cell(row, "coap.mid") == mid,
            )
        if match is None:
            match = _first_unused(responses, used, start, lambda _row: True)
        measurement = _blank_measurement()
        measurement["request_epoch"] = start
        measurement["kind"] = "coap_rtt"
        if match is None:
            measurement["alignment_note"] = "CoAP request had no response in the capture"
            measurement["latency_ms"] = None
            measurement["kind"] = ""
        else:
            _resp_index, response, _resp_code, end = match
            used.add(_resp_index)
            payload = _parse_int(response.get("data.len"))
            measurement["response_epoch"] = end
            measurement["latency_ms"] = (end - start) * 1000.0
            measurement["coap_latency_ms"] = measurement["latency_ms"]
            measurement["coap_payload_bytes"] = payload
        measurements.append(measurement)
    return measurements


def _first_unused(candidates, used: set[int], start: float, predicate) -> tuple | None:
    pool = []
    for item in candidates:
        index, row, _code, epoch = item
        if index in used or epoch < start or not predicate(row):
            continue
        pool.append(item)
    if not pool:
        return None
    return min(pool, key=lambda item: item[3])


def _http_measurements(rows: list[dict]) -> list[dict]:
    requests = []
    responses = []
    for index, row in enumerate(rows):
        epoch = _parse_float(row.get("frame.time_epoch"))
        if epoch is None:
            continue
        if _cell(row, "http.request.method"):
            requests.append((index, row, epoch))
        elif _cell(row, "http.response.code"):
            responses.append((index, row, epoch))
    used: set[int] = set()
    measurements = []
    for _index, request, start in requests:
        stream = _cell(request, "tcp.stream")
        measurement = _blank_measurement()
        measurement["request_epoch"] = start
        if not stream:
            measurement["alignment_note"] = "HTTP request had no tcp.stream; not paired"
            measurements.append(measurement)
            continue
        match = None
        for index, response, epoch in responses:
            if index in used or epoch < start or _cell(response, "tcp.stream") != stream:
                continue
            if match is None or epoch < match[2]:
                match = (index, response, epoch)
        if match is None:
            measurement["alignment_note"] = f"HTTP request on stream {stream} had no response"
            measurements.append(measurement)
            continue
        used.add(match[0])
        measurement["response_epoch"] = match[2]
        measurement["latency_ms"] = (match[2] - start) * 1000.0
        measurement["http_latency_ms"] = measurement["latency_ms"]
        measurement["http_payload_bytes"] = _parse_int(match[1].get("http.content_length"))
        measurement["kind"] = "http_rtt"
        measurements.append(measurement)
    return measurements


def _mqtt_measurements(rows: list[dict]) -> list[dict]:
    client_publishes = []
    broker_publishes = []
    pubacks = []
    pubcomps = []
    for index, row in enumerate(rows):
        epoch = _parse_float(row.get("frame.time_epoch"))
        msgtype = _parse_mqtt_type(_cell(row, "mqtt.msgtype"))
        if epoch is None or msgtype is None:
            continue
        to_broker = _port_is(row, "tcp.dstport", MQTT_PORT)
        from_broker = _port_is(row, "tcp.srcport", MQTT_PORT)
        item = (index, row, epoch)
        if msgtype == 3 and to_broker:
            client_publishes.append(item)
        elif msgtype == 3 and from_broker:
            broker_publishes.append(item)
        elif msgtype == 4 and from_broker:
            pubacks.append(item)
        elif msgtype == 7 and from_broker:
            pubcomps.append(item)
    used_delivery: set[int] = set()
    used_ack: set[int] = set()
    measurements = []
    for _index, publish, start in client_publishes:
        qos = _parse_int(publish.get("mqtt.qos")) or 0
        msgid = _cell(publish, "mqtt.msgid")
        measurement = _blank_measurement()
        measurement["request_epoch"] = start
        measurement["mqtt_payload_bytes"] = _mqtt_payload_length(_cell(publish, "mqtt.msg"))
        delivery = _mqtt_match(broker_publishes, used_delivery, start, msgid if qos else "", require_id=qos > 0)
        if delivery is None and qos == 0:
            delivery = _mqtt_match(broker_publishes, used_delivery, start, "", require_id=False)
        handshake_pool = pubacks if qos == 1 else pubcomps if qos == 2 else []
        handshake = None
        if handshake_pool:
            handshake = _mqtt_match(handshake_pool, used_ack, start, msgid, require_id=True)
        if delivery is not None:
            used_delivery.add(delivery[0])
            measurement["response_epoch"] = delivery[2]
            measurement["mqtt_delivery_latency_ms"] = (delivery[2] - start) * 1000.0
            measurement["latency_ms"] = measurement["mqtt_delivery_latency_ms"]
            measurement["kind"] = "mqtt_delivery"
        else:
            measurement["alignment_note"] = "No broker PUBLISH to the subscriber was paired"
        if handshake is not None:
            used_ack.add(handshake[0])
            measurement["mqtt_handshake_latency_ms"] = (handshake[2] - start) * 1000.0
        measurements.append(measurement)
    return measurements


def _mqtt_match(pool, used: set[int], start: float, msgid: str, require_id: bool) -> tuple | None:
    best = None
    for index, row, epoch in pool:
        if index in used or epoch < start:
            continue
        if require_id and (not msgid or _cell(row, "mqtt.msgid") != msgid):
            continue
        if best is None or epoch < best[2]:
            best = (index, row, epoch)
    return best


def _combine_measurements(coap_rows: list[dict], hop_rows: list[dict], hop: str) -> list[dict]:
    combined = []
    count = max(len(coap_rows), len(hop_rows))
    for index in range(count):
        coap = coap_rows[index] if index < len(coap_rows) else None
        other = hop_rows[index] if index < len(hop_rows) else None
        record = _blank_measurement()
        if coap:
            record["coap_latency_ms"] = coap.get("coap_latency_ms")
            record["coap_payload_bytes"] = coap.get("coap_payload_bytes")
        if other and hop == "http":
            record["http_latency_ms"] = other.get("http_latency_ms")
            record["http_payload_bytes"] = other.get("http_payload_bytes")
        if other and hop == "mqtt":
            record["mqtt_delivery_latency_ms"] = other.get("mqtt_delivery_latency_ms")
            record["mqtt_handshake_latency_ms"] = other.get("mqtt_handshake_latency_ms")
            record["mqtt_payload_bytes"] = other.get("mqtt_payload_bytes")
        start = coap.get("request_epoch") if coap else None
        end = other.get("response_epoch") if other else None
        if start is not None and end is not None:
            record["request_epoch"] = start
            record["response_epoch"] = end
            record["latency_ms"] = (end - start) * 1000.0
            record["kind"] = "e2e"
        else:
            notes = []
            if coap is None:
                notes.append("missing CoAP exchange")
            if other is None:
                notes.append("missing HTTP exchange" if hop == "http" else "missing MQTT exchange")
            elif end is None:
                notes.append("delivery timestamp missing; handshake is stored separately and is not used as end-to-end delay")
            record["alignment_note"] = "; ".join(notes)
        combined.append(record)
    return combined


def align_series(
    script_rows: list[dict],
    tshark_rows: list[dict],
    meta: dict,
    *,
    run_id: str,
    example_data: bool,
    source_csv: str,
    capture_file: str,
    reported: dict | None = None,
) -> list[dict]:
    """Zip script transactions with capture exchanges in order. Do not invent rows."""
    reported = reported or {}
    count = max(len(script_rows), len(tshark_rows))
    note = ""
    if script_rows and tshark_rows and len(script_rows) != len(tshark_rows):
        note = (
            f"Aligned by order: script rows={len(script_rows)}, "
            f"tshark rows={len(tshark_rows)}"
        )
    aligned = []
    for index in range(count):
        script = script_rows[index] if index < len(script_rows) else {}
        tshark = tshark_rows[index] if index < len(tshark_rows) else {}
        alignment = note
        extra = tshark.get("alignment_note") or ""
        if extra:
            alignment = f"{alignment}; {extra}".strip("; ")
        row = {column: None for column in TRANSACTION_COLUMNS}
        row.update(
            {
                "run_id": run_id,
                "example_data": bool(example_data),
                "environment": meta["environment"],
                "scenario": meta["scenario"],
                "protocol": meta["protocol"],
                "coap_type": meta.get("coap_type") or "",
                "mqtt_qos": meta.get("mqtt_qos"),
                "packet_loss_pct": meta["packet_loss_pct"],
                "transaction": script.get("transaction", index + 1),
                "script_timestamp": script.get("script_timestamp") or "",
                "script_latency_ms": script.get("script_latency_ms"),
                "script_coap_latency_ms": script.get("script_coap_latency_ms"),
                "script_http_latency_ms": script.get("script_http_latency_ms"),
                "script_mqtt_latency_ms": script.get("script_mqtt_latency_ms"),
                "script_total_latency_ms": script.get("script_total_latency_ms"),
                "script_reported_average_ms": reported.get("headline"),
                "script_reported_coap_average_ms": reported.get("coap"),
                "script_reported_http_average_ms": reported.get("http"),
                "script_reported_mqtt_average_ms": reported.get("mqtt"),
                "tshark_index": index + 1 if tshark else None,
                "tshark_request_epoch": tshark.get("request_epoch"),
                "tshark_response_epoch": tshark.get("response_epoch"),
                "tshark_latency_ms": tshark.get("latency_ms"),
                "tshark_latency_kind": tshark.get("kind") or "",
                "tshark_coap_latency_ms": tshark.get("coap_latency_ms"),
                "tshark_http_latency_ms": tshark.get("http_latency_ms"),
                "tshark_mqtt_delivery_latency_ms": tshark.get("mqtt_delivery_latency_ms"),
                "tshark_mqtt_handshake_latency_ms": tshark.get("mqtt_handshake_latency_ms"),
                "coap_payload_bytes": tshark.get("coap_payload_bytes"),
                "http_payload_bytes": tshark.get("http_payload_bytes"),
                "mqtt_payload_bytes": tshark.get("mqtt_payload_bytes"),
                "mqtt_payload_bytes_configured": configured_mqtt_payload(meta["scenario"]),
                "capture_file": capture_file,
                "source_csv": source_csv,
                "alignment_note": alignment,
            }
        )
        aligned.append(row)
    return aligned


def _series_key(meta: dict) -> tuple:
    return (
        meta["environment"],
        meta["scenario"],
        meta.get("coap_type") or "",
        meta.get("mqtt_qos"),
        meta["packet_loss_pct"],
    )


def discover_inputs(source: Path) -> dict:
    csv_files = []
    captures = []
    for env in ("env1", "env2"):
        latency_dir = source / env / "latencies"
        capture_dir = source / env / "captures"
        if latency_dir.is_dir():
            csv_files.extend(sorted(latency_dir.glob("*.csv")))
        if capture_dir.is_dir():
            captures.extend(sorted(capture_dir.glob("*.pcap")))
            captures.extend(sorted(capture_dir.glob("*.pcapng")))
    return {"csv": csv_files, "pcap": captures}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _link_or_copy(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dest)
        return "copy"


def _fingerprint(source: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(f"schema={SCHEMA_VERSION}\n".encode())
    for path in sorted(files, key=lambda item: _relative(item, source)):
        digest.update(_relative(path, source).encode())
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _git_metadata(repo: Path) -> dict:
    def run(*args: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    commit = run("rev-parse", "HEAD")
    dirty = run("status", "--porcelain")
    return {
        "commit": commit,
        "commit_short": commit[:12] if commit else None,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
    }


def _host_metadata() -> dict:
    uname = platform.uname()
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "system": uname.system,
        "release": uname.release,
        "machine": uname.machine,
    }


def _new_run_id(store: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = stamp
    suffix = 2
    while (store / candidate).exists():
        candidate = f"{stamp}-{suffix}"
        suffix += 1
    return candidate


def iter_run_metadata(store: Path):
    if not store.is_dir():
        return
    for path in sorted(store.glob("*/metadata.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


def _write_index(store: Path) -> None:
    briefs = []
    latest = None
    for _path, meta in iter_run_metadata(store):
        git = meta.get("git") or {}
        briefs.append(
            {
                "run_id": meta.get("run_id"),
                "created_at_utc": meta.get("created_at_utc"),
                "example_data": meta.get("example_data"),
                "source_mode": meta.get("source_mode"),
                "source_dir": meta.get("source_dir"),
                "fingerprint": meta.get("fingerprint"),
                "git_commit": git.get("commit_short"),
            }
        )
        latest = meta.get("run_id")
    text = "".join(json.dumps(item) + "\n" for item in briefs)
    (store / "index.jsonl").write_text(text, encoding="utf-8")
    if latest:
        (store / "latest.json").write_text(json.dumps({"run_id": latest}, indent=2) + "\n", encoding="utf-8")


def _read_script_summaries(source: Path) -> dict:
    summary_dir = source / "summary"
    if not summary_dir.is_dir():
        return {}
    stored = {}
    for path in sorted(summary_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".txt"}:
            continue
        if path.stat().st_size > 200_000:
            stored[path.name] = {"skipped": "file larger than 200000 bytes"}
            continue
        stored[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return stored


def _example_marker(source: Path) -> dict | None:
    marker = source / "EXAMPLE_DATA.json"
    if not marker.is_file():
        return None
    return json.loads(marker.read_text(encoding="utf-8"))


def _json_safe(value):
    if value is None:
        return None
    try:
        missing = pd.isna(value)
    except TypeError:
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def _table_payload(frame: pd.DataFrame, question: str, note: str) -> dict:
    rows = []
    for record in frame.to_dict(orient="records"):
        rows.append({key: _json_safe(value) for key, value in record.items()})
    return {
        "question": question,
        "note": note,
        "columns": list(frame.columns),
        "rows": rows,
    }


def normalize_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return empty_transactions()
    work = frame.copy()
    if "example_data" in work.columns:
        work["example_data"] = work["example_data"].map(as_bool)
    if "coap_type" in work.columns:
        work["coap_type"] = work["coap_type"].fillna("").astype(str).replace({"nan": ""})
    for column in ("packet_loss_pct", "transaction", "mqtt_qos", "tshark_index"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").astype("Int64")
    for column in TRANSACTION_COLUMNS:
        if column not in work.columns:
            work[column] = pd.NA
    return work[list(TRANSACTION_COLUMNS)]


def empty_transactions() -> pd.DataFrame:
    return pd.DataFrame(columns=list(TRANSACTION_COLUMNS))


def empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=list(SUMMARY_COLUMNS))


def _stat_block(series: pd.Series, prefix: str) -> dict:
    present = pd.to_numeric(series, errors="coerce").dropna()
    block = {
        f"n_{prefix}": int(present.shape[0]),
        f"mean_{prefix}_ms": present.mean() if not present.empty else None,
        f"median_{prefix}_ms": present.median() if not present.empty else None,
        f"min_{prefix}_ms": present.min() if not present.empty else None,
        f"max_{prefix}_ms": present.max() if not present.empty else None,
        f"stdev_{prefix}_ms": present.std(ddof=1) if present.shape[0] > 1 else None,
    }
    return block


def _mean_or_none(series: pd.Series):
    present = pd.to_numeric(series, errors="coerce").dropna()
    if present.empty:
        return None
    return float(present.mean())


def _median_or_none(series: pd.Series):
    present = pd.to_numeric(series, errors="coerce").dropna()
    if present.empty:
        return None
    return float(present.median())


def _first_present(series: pd.Series):
    present = series.dropna()
    if present.empty:
        return None
    value = present.iloc[0]
    if isinstance(value, str) and value == "":
        rest = present[present != ""]
        if rest.empty:
            return ""
        return rest.iloc[0]
    return value


def summarize_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    """Roll transaction rows up to one row per condition. Means ignore nulls."""
    work = normalize_transactions(frame)
    if work.empty:
        return empty_summary()
    work = work.dropna(subset=["packet_loss_pct", "run_id", "scenario"])
    if work.empty:
        return empty_summary()
    group_columns = [
        "run_id",
        "example_data",
        "environment",
        "scenario",
        "protocol",
        "coap_type",
        "mqtt_qos",
        "packet_loss_pct",
    ]
    rows = []
    for key, group in work.groupby(group_columns, dropna=False, sort=False):
        record = dict(zip(group_columns, key if isinstance(key, tuple) else (key,)))
        record.update(_stat_block(group["script_latency_ms"], "script"))
        record.update(_stat_block(group["tshark_latency_ms"], "tshark"))
        record["mean_script_coap_ms"] = _mean_or_none(group["script_coap_latency_ms"])
        record["mean_script_http_ms"] = _mean_or_none(group["script_http_latency_ms"])
        record["mean_script_mqtt_ms"] = _mean_or_none(group["script_mqtt_latency_ms"])
        record["mean_tshark_coap_ms"] = _mean_or_none(group["tshark_coap_latency_ms"])
        record["mean_tshark_http_ms"] = _mean_or_none(group["tshark_http_latency_ms"])
        record["mean_tshark_mqtt_delivery_ms"] = _mean_or_none(group["tshark_mqtt_delivery_latency_ms"])
        record["mean_tshark_mqtt_handshake_ms"] = _mean_or_none(group["tshark_mqtt_handshake_latency_ms"])
        record["script_reported_average_ms"] = _json_safe(_first_present(group["script_reported_average_ms"]))
        record["coap_payload_bytes_measured"] = _median_or_none(group["coap_payload_bytes"])
        record["http_payload_bytes_measured"] = _median_or_none(group["http_payload_bytes"])
        record["mqtt_payload_bytes_measured"] = _median_or_none(group["mqtt_payload_bytes"])
        configured = _first_present(group["mqtt_payload_bytes_configured"])
        record["mqtt_payload_bytes_configured"] = _json_safe(configured)
        record["capture_file"] = _first_present(group["capture_file"].replace("", pd.NA)) or ""
        record["source_csv"] = _first_present(group["source_csv"].replace("", pd.NA)) or ""
        record["example_data"] = as_bool(record["example_data"])
        if pd.isna(record["mqtt_qos"]):
            record["mqtt_qos"] = None
        else:
            record["mqtt_qos"] = int(record["mqtt_qos"])
        record["packet_loss_pct"] = int(record["packet_loss_pct"])
        rows.append(record)
    summary = pd.DataFrame(rows)
    for column in SUMMARY_COLUMNS:
        if column not in summary.columns:
            summary[column] = pd.NA
    summary = summary[list(SUMMARY_COLUMNS)]
    summary["_qos_sort"] = pd.to_numeric(summary["mqtt_qos"], errors="coerce").fillna(-1)
    summary = summary.sort_values(
        ["run_id", "environment", "scenario", "coap_type", "_qos_sort", "packet_loss_pct"],
        kind="mergesort",
    ).drop(columns="_qos_sort")
    return summary.reset_index(drop=True)


def _runs_for(summary: pd.DataFrame, environment: str | None = None) -> list[str]:
    if summary.empty:
        return []
    work = summary
    if environment is not None:
        work = summary[summary["environment"] == environment]
    return list(dict.fromkeys(work["run_id"].tolist()))


def _subset(
    summary: pd.DataFrame,
    run_id: str,
    *,
    environment: str,
    scenario: str,
    loss: int,
    coap_type: str | None = None,
    mqtt_qos: int | None = None,
    qos_required: bool = False,
) -> pd.Series | None:
    work = summary[
        (summary["run_id"] == run_id)
        & (summary["environment"] == environment)
        & (summary["scenario"] == scenario)
        & (pd.to_numeric(summary["packet_loss_pct"], errors="coerce") == loss)
    ]
    if coap_type is not None:
        work = work[work["coap_type"].fillna("").astype(str) == coap_type]
    qos = pd.to_numeric(work["mqtt_qos"], errors="coerce")
    if mqtt_qos is None and qos_required:
        work = work[qos.isna()]
    elif mqtt_qos is not None:
        work = work[qos == mqtt_qos]
    if work.empty:
        return None
    return work.iloc[0]


def _value(row: pd.Series | None, column: str):
    if row is None or column not in row.index:
        return None
    return _json_safe(row[column])


def _timing_pair(timing: str) -> tuple[str, str]:
    if timing == "script":
        return "mean_script_ms", "n_script"
    if timing == "tshark":
        return "mean_tshark_ms", "n_tshark"
    raise ValueError("timing must be 'script' or 'tshark'")


def _component_column(timing: str, leg: str) -> str:
    if timing == "script":
        return {
            "coap": "mean_script_coap_ms",
            "http": "mean_script_http_ms",
            "mqtt": "mean_script_mqtt_ms",
        }[leg]
    return {
        "coap": "mean_tshark_coap_ms",
        "http": "mean_tshark_http_ms",
        "mqtt": "mean_tshark_mqtt_delivery_ms",
    }[leg]


NOTE_ENV1_Q1 = (
    "Device-to-application delay from environment-1 test.sh: a confirmable CoAP GET "
    "of /time, then an HTTP GET of /time. The headline is that end-to-end mean at "
    "0% packet loss. HTTP-only at 0% is the application protocol's own request/response. "
    "The tshark table uses packet timestamps. The script table uses the client clock "
    "logged around the two commands. CoAP and HTTP payload sizes are measured only "
    "when a capture exposes them; the script does not set those body sizes."
)
NOTE_ENV1_Q2 = (
    "Packet loss versus latency for the CoAP-only trials (not the combined CoAP+HTTP "
    "trial). Confirmable is coap-client without -N. Non-confirmable is coap-client -N. "
    "Missing cells are absent data, not zero latency."
)
NOTE_ENV2_Q1 = (
    "Device-to-application delay from environment-2 test.sh: confirmable CoAP GET, "
    "then an MQTT publish at the given QoS. The headline rows are 0% packet loss. "
    "tshark end-to-end timing ends when the broker forwards the PUBLISH to the "
    "subscriber. The script clock is the sum of the CoAP client command and "
    "mosquitto_pub. The combined publish payload configured by test.sh is the "
    "9-byte string 'timestamp'."
)
NOTE_ENV2_Q2 = (
    "Packet loss versus latency for confirmable CoAP (CoAP-only trial) and MQTT "
    "QoS 0, 1, and 2 (MQTT-only trials). QoS 0/1/2 are at most once, at least once, "
    "and exactly once. MQTT tshark latency is subscriber delivery, not the PUBACK "
    "handshake. The MQTT-only publish configured by test.sh is `date +%Y-%m-%d` (10 bytes)."
)
NOTE_ENV2_Q4 = (
    "Same configured access-side loss. CoAP-based MQTT is the environment 2 combined "
    "trial (confirmable CoAP then MQTT). HTTP is the environment 1 HTTP-only trial. "
    "CoAP+HTTP end-to-end is included as the environment 1 combined path. "
    "Each table uses one timing source so script clocks are not mixed with packet timestamps."
)


def env1_q1_delay(summary: pd.DataFrame, timing: str = "script") -> pd.DataFrame:
    mean_col, n_col = _timing_pair(timing)
    series_spec = (
        ("CoAP confirmable + HTTP (end-to-end)", "coap_http", "confirmable", None, "coap", "http"),
        ("HTTP", "http", "", None, None, None),
        ("CoAP confirmable", "coap", "confirmable", None, None, None),
        ("CoAP non-confirmable", "coap", "non-confirmable", None, None, None),
    )
    rows = []
    for run_id in _runs_for(summary, "env1"):
        example = as_bool(summary.loc[summary["run_id"] == run_id, "example_data"].iloc[0])
        for loss in LOSS_RATES:
            for label, scenario, coap_type, qos, coap_leg, app_leg in series_spec:
                match = _subset(
                    summary,
                    run_id,
                    environment="env1",
                    scenario=scenario,
                    loss=loss,
                    coap_type=coap_type,
                    mqtt_qos=qos,
                    qos_required=True,
                )
                role = ""
                if loss == 0 and label.startswith("CoAP confirmable + HTTP"):
                    role = "device_to_application"
                elif loss == 0 and label == "HTTP":
                    role = "application_protocol"
                rows.append(
                    {
                        "run_id": run_id,
                        "example_data": example,
                        "packet_loss_pct": loss,
                        "series": label,
                        "role": role,
                        "mean_latency_ms": _value(match, mean_col),
                        "n": _value(match, n_col),
                        "coap_leg_mean_ms": _value(match, _component_column(timing, coap_leg)) if coap_leg else None,
                        "application_leg_mean_ms": _value(match, _component_column(timing, app_leg)) if app_leg else None,
                        "payload_bytes_measured": _payload_measured(match),
                        "mqtt_payload_bytes_configured": _value(match, "mqtt_payload_bytes_configured"),
                        "timing_source": timing,
                    }
                )
    columns = [
        "run_id",
        "example_data",
        "packet_loss_pct",
        "series",
        "role",
        "mean_latency_ms",
        "n",
        "coap_leg_mean_ms",
        "application_leg_mean_ms",
        "payload_bytes_measured",
        "mqtt_payload_bytes_configured",
        "timing_source",
    ]
    return pd.DataFrame(rows, columns=columns)


def env1_q2_loss_table(summary: pd.DataFrame, timing: str = "script") -> pd.DataFrame:
    mean_col, n_col = _timing_pair(timing)
    rows = []
    for run_id in _runs_for(summary, "env1"):
        example = as_bool(summary.loc[summary["run_id"] == run_id, "example_data"].iloc[0])
        for loss in LOSS_RATES:
            confirmable = _subset(
                summary,
                run_id,
                environment="env1",
                scenario="coap",
                loss=loss,
                coap_type="confirmable",
                qos_required=True,
            )
            nonconfirmable = _subset(
                summary,
                run_id,
                environment="env1",
                scenario="coap",
                loss=loss,
                coap_type="non-confirmable",
                qos_required=True,
            )
            rows.append(
                {
                    "run_id": run_id,
                    "example_data": example,
                    "packet_loss_pct": loss,
                    "coap_confirmable_mean_ms": _value(confirmable, mean_col),
                    "coap_nonconfirmable_mean_ms": _value(nonconfirmable, mean_col),
                    "n_coap_confirmable": _value(confirmable, n_col),
                    "n_coap_nonconfirmable": _value(nonconfirmable, n_col),
                    "coap_confirmable_payload_bytes_measured": _value(confirmable, "coap_payload_bytes_measured"),
                    "coap_nonconfirmable_payload_bytes_measured": _value(
                        nonconfirmable, "coap_payload_bytes_measured"
                    ),
                    "timing_source": timing,
                }
            )
    columns = [
        "run_id",
        "example_data",
        "packet_loss_pct",
        "coap_confirmable_mean_ms",
        "coap_nonconfirmable_mean_ms",
        "n_coap_confirmable",
        "n_coap_nonconfirmable",
        "coap_confirmable_payload_bytes_measured",
        "coap_nonconfirmable_payload_bytes_measured",
        "timing_source",
    ]
    return pd.DataFrame(rows, columns=columns)


def env2_q1_delay(summary: pd.DataFrame, timing: str = "script") -> pd.DataFrame:
    mean_col, n_col = _timing_pair(timing)
    rows = []
    for run_id in _runs_for(summary, "env2"):
        example = as_bool(summary.loc[summary["run_id"] == run_id, "example_data"].iloc[0])
        for qos in (0, 1, 2):
            for loss in LOSS_RATES:
                match = _subset(
                    summary,
                    run_id,
                    environment="env2",
                    scenario="coap_mqtt",
                    loss=loss,
                    coap_type="confirmable",
                    mqtt_qos=qos,
                )
                rows.append(
                    {
                        "run_id": run_id,
                        "example_data": example,
                        "mqtt_qos": qos,
                        "mqtt_qos_name": {0: "at most once", 1: "at least once", 2: "exactly once"}[qos],
                        "packet_loss_pct": loss,
                        "role": "device_to_application" if loss == 0 else "",
                        "e2e_mean_ms": _value(match, mean_col),
                        "coap_leg_mean_ms": _value(match, _component_column(timing, "coap")),
                        "mqtt_leg_mean_ms": _value(match, _component_column(timing, "mqtt")),
                        "n": _value(match, n_col),
                        "coap_payload_bytes_measured": _value(match, "coap_payload_bytes_measured"),
                        "mqtt_payload_bytes_measured": _value(match, "mqtt_payload_bytes_measured"),
                        "mqtt_payload_bytes_configured": _value(match, "mqtt_payload_bytes_configured"),
                        "timing_source": timing,
                    }
                )
    columns = [
        "run_id",
        "example_data",
        "mqtt_qos",
        "mqtt_qos_name",
        "packet_loss_pct",
        "role",
        "e2e_mean_ms",
        "coap_leg_mean_ms",
        "mqtt_leg_mean_ms",
        "n",
        "coap_payload_bytes_measured",
        "mqtt_payload_bytes_measured",
        "mqtt_payload_bytes_configured",
        "timing_source",
    ]
    return pd.DataFrame(rows, columns=columns)


def env2_q2_loss_table(summary: pd.DataFrame, timing: str = "script") -> pd.DataFrame:
    mean_col, n_col = _timing_pair(timing)
    rows = []
    for run_id in _runs_for(summary, "env2"):
        example = as_bool(summary.loc[summary["run_id"] == run_id, "example_data"].iloc[0])
        for loss in LOSS_RATES:
            confirmable = _subset(
                summary,
                run_id,
                environment="env2",
                scenario="coap",
                loss=loss,
                coap_type="confirmable",
                qos_required=True,
            )
            mqtt = {
                qos: _subset(
                    summary,
                    run_id,
                    environment="env2",
                    scenario="mqtt",
                    loss=loss,
                    coap_type="",
                    mqtt_qos=qos,
                )
                for qos in (0, 1, 2)
            }
            rows.append(
                {
                    "run_id": run_id,
                    "example_data": example,
                    "packet_loss_pct": loss,
                    "coap_confirmable_mean_ms": _value(confirmable, mean_col),
                    "mqtt_qos0_mean_ms": _value(mqtt[0], mean_col),
                    "mqtt_qos1_mean_ms": _value(mqtt[1], mean_col),
                    "mqtt_qos2_mean_ms": _value(mqtt[2], mean_col),
                    "n_coap_confirmable": _value(confirmable, n_col),
                    "n_mqtt_qos0": _value(mqtt[0], n_col),
                    "n_mqtt_qos1": _value(mqtt[1], n_col),
                    "n_mqtt_qos2": _value(mqtt[2], n_col),
                    "coap_payload_bytes_measured": _value(confirmable, "coap_payload_bytes_measured"),
                    "mqtt_qos0_payload_bytes_measured": _value(mqtt[0], "mqtt_payload_bytes_measured"),
                    "mqtt_qos1_payload_bytes_measured": _value(mqtt[1], "mqtt_payload_bytes_measured"),
                    "mqtt_qos2_payload_bytes_measured": _value(mqtt[2], "mqtt_payload_bytes_measured"),
                    "mqtt_payload_bytes_configured": _value(mqtt[0], "mqtt_payload_bytes_configured"),
                    "timing_source": timing,
                }
            )
    columns = [
        "run_id",
        "example_data",
        "packet_loss_pct",
        "coap_confirmable_mean_ms",
        "mqtt_qos0_mean_ms",
        "mqtt_qos1_mean_ms",
        "mqtt_qos2_mean_ms",
        "n_coap_confirmable",
        "n_mqtt_qos0",
        "n_mqtt_qos1",
        "n_mqtt_qos2",
        "coap_payload_bytes_measured",
        "mqtt_qos0_payload_bytes_measured",
        "mqtt_qos1_payload_bytes_measured",
        "mqtt_qos2_payload_bytes_measured",
        "mqtt_payload_bytes_configured",
        "timing_source",
    ]
    return pd.DataFrame(rows, columns=columns)


def env2_q4_mqtt_vs_http(summary: pd.DataFrame, timing: str = "script") -> pd.DataFrame:
    mean_col, n_col = _timing_pair(timing)
    run_ids = list(dict.fromkeys(_runs_for(summary)))
    rows = []
    for run_id in run_ids:
        has_http = run_id in _runs_for(summary, "env1")
        has_mqtt = run_id in _runs_for(summary, "env2")
        if not has_http and not has_mqtt:
            continue
        example_values = summary.loc[summary["run_id"] == run_id, "example_data"]
        example = as_bool(example_values.iloc[0]) if not example_values.empty else False
        for loss in LOSS_RATES:
            http = _subset(
                summary,
                run_id,
                environment="env1",
                scenario="http",
                loss=loss,
                coap_type="",
                qos_required=True,
            )
            coap_http = _subset(
                summary,
                run_id,
                environment="env1",
                scenario="coap_http",
                loss=loss,
                coap_type="confirmable",
                qos_required=True,
            )
            e2e = {
                qos: _subset(
                    summary,
                    run_id,
                    environment="env2",
                    scenario="coap_mqtt",
                    loss=loss,
                    coap_type="confirmable",
                    mqtt_qos=qos,
                )
                for qos in (0, 1, 2)
            }
            rows.append(
                {
                    "run_id": run_id,
                    "example_data": example,
                    "packet_loss_pct": loss,
                    "http_mean_ms": _value(http, mean_col),
                    "coap_http_e2e_mean_ms": _value(coap_http, mean_col),
                    "coap_mqtt_qos0_e2e_mean_ms": _value(e2e[0], mean_col),
                    "coap_mqtt_qos1_e2e_mean_ms": _value(e2e[1], mean_col),
                    "coap_mqtt_qos2_e2e_mean_ms": _value(e2e[2], mean_col),
                    "n_http": _value(http, n_col),
                    "n_coap_http": _value(coap_http, n_col),
                    "n_coap_mqtt_qos0": _value(e2e[0], n_col),
                    "n_coap_mqtt_qos1": _value(e2e[1], n_col),
                    "n_coap_mqtt_qos2": _value(e2e[2], n_col),
                    "timing_source": timing,
                }
            )
    columns = [
        "run_id",
        "example_data",
        "packet_loss_pct",
        "http_mean_ms",
        "coap_http_e2e_mean_ms",
        "coap_mqtt_qos0_e2e_mean_ms",
        "coap_mqtt_qos1_e2e_mean_ms",
        "coap_mqtt_qos2_e2e_mean_ms",
        "n_http",
        "n_coap_http",
        "n_coap_mqtt_qos0",
        "n_coap_mqtt_qos1",
        "n_coap_mqtt_qos2",
        "timing_source",
    ]
    return pd.DataFrame(rows, columns=columns)


def _payload_measured(row: pd.Series | None):
    if row is None:
        return None
    for column in (
        "coap_payload_bytes_measured",
        "http_payload_bytes_measured",
        "mqtt_payload_bytes_measured",
    ):
        value = _value(row, column)
        if value is not None:
            return value
    return None


def build_lab_tables(summary: pd.DataFrame) -> dict:
    builders = (
        ("env1_q1_delay", env1_q1_delay, Q_ENV1_1, NOTE_ENV1_Q1),
        ("env1_q2_loss", env1_q2_loss_table, Q_ENV1_2, NOTE_ENV1_Q2),
        ("env2_q1_delay", env2_q1_delay, Q_ENV2_1, NOTE_ENV2_Q1),
        ("env2_q2_loss", env2_q2_loss_table, Q_ENV2_2, NOTE_ENV2_Q2),
        ("env2_q4_coap_mqtt_vs_http", env2_q4_mqtt_vs_http, Q_ENV2_4, NOTE_ENV2_Q4),
    )
    tables = {}
    for name, builder, question, note in builders:
        for timing in ("script", "tshark"):
            tables[f"{name}_{timing}"] = _table_payload(builder(summary, timing), question, note)
    return tables


def headline_sentence(table: pd.DataFrame, environment: str) -> str:
    """One or two plain sentences for the lab's averaged-delay question."""
    if table is None or table.empty or "role" not in table.columns:
        return f"{environment}: no rows for this timing source."
    chosen = table[table["role"].fillna("").astype(str) != ""]
    if chosen.empty:
        return f"{environment}: no 0% loss headline row for this timing source."
    lines = []
    for _, row in chosen.iterrows():
        lines.append(_format_headline_row(row, environment))
    return "\n".join(lines)


def _format_headline_row(row: pd.Series, environment: str) -> str:
    prefix = "EXAMPLE DATA (not a measurement). " if as_bool(row.get("example_data")) else ""
    timing = row.get("timing_source")
    timing_name = "Wireshark timestamps via tshark" if timing == "tshark" else "the test.sh client clock"
    mean_column = "e2e_mean_ms" if "e2e_mean_ms" in row.index else "mean_latency_ms"
    mean = row.get(mean_column)
    label = row["series"] if "series" in row.index else f"MQTT QoS {row.get('mqtt_qos')} ({row.get('mqtt_qos_name')})"
    if mean is None or (isinstance(mean, float) and math.isnan(mean)):
        return (
            f"{prefix}{environment} {label} at 0% packet loss: "
            f"not available from {timing_name}."
        )
    n_value = row.get("n")
    try:
        n_int = int(n_value) if n_value is not None and not (isinstance(n_value, float) and math.isnan(n_value)) else None
    except (TypeError, ValueError):
        n_int = None
    if n_int is None:
        count = "transaction count unknown"
    elif n_int != LAB_TRANSACTION_COUNT:
        count = f"n={n_int}; the lab asks for {LAB_TRANSACTION_COUNT}"
    else:
        count = f"n={n_int}"
    payload = _headline_payload(row)
    role = row.get("role")
    role_text = {
        "device_to_application": "device-to-application",
        "application_protocol": "HTTP request/response at the application",
    }.get(role, "result")
    return (
        f"{prefix}{environment} {role_text}, {label}, 0% packet loss: "
        f"mean {float(mean):.3f} ms ({count}). Timing source: {timing_name}.{payload}"
    )


def _headline_payload(row: pd.Series) -> str:
    measured = row.get("payload_bytes_measured")
    if measured is None or (isinstance(measured, float) and math.isnan(measured)):
        measured = row.get("mqtt_payload_bytes_measured")
    if measured is None or (isinstance(measured, float) and math.isnan(measured)):
        measured = row.get("coap_payload_bytes_measured")
    configured = row.get("mqtt_payload_bytes_configured")
    if measured is not None and not (isinstance(measured, float) and math.isnan(measured)):
        return f" Measured application payload median {float(measured):.0f} bytes."
    if configured is not None and not (isinstance(configured, float) and math.isnan(configured)):
        return (
            f" MQTT payload configured by test.sh is {int(configured)} bytes "
            "(not measured from a capture)."
        )
    return " Payload size was not measured, and this series does not have a payload fixed by test.sh."


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, na_rep="")


def _captures_readme(run_dir: Path, capture_count: int) -> None:
    capture_dir = run_dir / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    if capture_count:
        body = (
            "# Packet captures\n\n"
            "These `.pcapng` files are the raw tshark captures for this run.\n"
            "Open them in Wireshark to paste traces into the TELE 6510 report.\n"
            "They are gitignored (`*.pcapng`). Paths are listed in `../metadata.json` under `captures`.\n"
        )
    else:
        body = (
            "# Packet captures\n\n"
            "This run has no `.pcapng` files.\n"
            "Live tests and a `lab_results` tree that includes `env*/captures/` will store them here.\n"
            "Open those files in Wireshark for the lab's trace screenshots. They are gitignored.\n"
        )
    (capture_dir / "README.md").write_text(body, encoding="utf-8")


def _find_reusable(store: Path, fingerprint: str) -> dict | None:
    for _path, meta in iter_run_metadata(store):
        if meta.get("fingerprint") == fingerprint and meta.get("schema_version") == SCHEMA_VERSION:
            return meta
    return None


def ingest(
    source: Path,
    store: Path | None = None,
    *,
    force: bool = False,
    notes: str = "",
    source_mode: str = "ingest",
    live_info: dict | None = None,
    extra_warnings: list[str] | None = None,
) -> dict:
    """Parse a results tree, link its captures, and write one timestamped run."""
    source = Path(source).resolve()
    store = Path(store) if store else default_store()
    store.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        raise IngestError(f"Source does not exist: {source}")
    found = discover_inputs(source)
    if not found["csv"] and not found["pcap"]:
        raise IngestError(
            f"No latency CSVs or pcap/pcapng captures under {source}. "
            "Run environment-*/test.sh or comprehensive-test/lab_test.sh first, "
            "or pass the notebooks/sample_lab_results example (it is synthetic)."
        )
    fingerprint = _fingerprint(source, found["csv"] + found["pcap"])
    warnings = list(extra_warnings or [])
    if not force:
        existing = _find_reusable(store, fingerprint)
        if existing:
            reused_warnings = list(extra_warnings or [])
            if existing.get("example_data"):
                reused_warnings.append(
                    "EXAMPLE DATA: these CSVs are synthetic and are not lab measurements. "
                    "Do not use them in the TELE 6510 report."
                )
            reused_warnings.append(
                f"Reused {existing['run_id']} because the source files are unchanged. "
                "Set FORCE = True to store another copy."
            )
            return {
                "run_id": existing["run_id"],
                "run_dir": str(store / existing["run_id"]),
                "reused": True,
                "example_data": bool(existing.get("example_data")),
                "warnings": reused_warnings,
                "metadata": existing,
            }

    example_doc = _example_marker(source)
    example_data = example_doc is not None
    if example_data:
        warnings.append(
            "EXAMPLE DATA: these CSVs are synthetic and are not lab measurements. "
            "Do not use them in the TELE 6510 report."
        )
    tshark = tshark_status()
    script_by_key: dict[tuple, dict] = {}
    for path in found["csv"]:
        meta_name = parse_result_name(path.name)
        if meta_name is None:
            warnings.append(f"Skipping unrecognized latency file {path.name}")
            continue
        try:
            parsed = parse_script_csv(path)
        except ParseError as exc:
            warnings.append(f"Could not parse {path.name}: {exc}")
            continue
        if parsed["skipped"]:
            warnings.append(f"{path.name}: skipped {parsed['skipped']} malformed data rows")
        script_by_key[_series_key(parsed["meta"])] = parsed

    run_id = _new_run_id(store)
    run_dir = store / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    captures_meta = []
    tshark_by_key: dict[tuple, dict] = {}
    if not found["pcap"]:
        warnings.append(
            "No pcapng captures in this source. Wireshark-timestamp columns are empty. "
            "Script-clock columns are filled when latency CSVs exist."
        )
    elif not tshark["available"]:
        warnings.append(tshark["reason"])
    for path in found["pcap"]:
        name_meta = parse_result_name(path.name)
        if name_meta is None:
            warnings.append(f"Skipping unrecognized capture {path.name}")
            continue
        try:
            environment = environment_from_path(path)
        except ParseError as exc:
            warnings.append(str(exc))
            continue
        meta = dict(name_meta)
        meta["environment"] = environment
        stored_as = Path("captures") / environment / path.name
        method = _link_or_copy(path, run_dir / stored_as)
        record = {
            "environment": environment,
            "scenario": meta["scenario"],
            "protocol": meta["protocol"],
            "coap_type": meta["coap_type"],
            "mqtt_qos": meta["mqtt_qos"],
            "packet_loss_pct": meta["packet_loss_pct"],
            "stored_as": stored_as.as_posix(),
            "original_path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "link_method": method,
            "wireshark": "Open this pcapng in Wireshark for the lab trace screenshots.",
            "tshark_parsed": False,
            "tshark_error": "",
            "tshark_transactions": 0,
        }
        if not tshark["available"]:
            record["tshark_error"] = tshark["reason"]
        else:
            try:
                field_rows = export_tshark_fields(path)
                measurements = measurements_from_tshark_rows(field_rows, meta["scenario"])
                tshark_by_key[_series_key(meta)] = {"meta": meta, "rows": measurements}
                record["tshark_parsed"] = True
                record["tshark_transactions"] = sum(1 for item in measurements if item.get("latency_ms") is not None)
                if record["tshark_transactions"] == 0:
                    record["tshark_error"] = "tshark ran but no request/response pairs were found"
            except TsharkError as exc:
                record["tshark_error"] = str(exc)
                warnings.append(f"{path.name}: {exc}")
        captures_meta.append(record)

    if found["pcap"] and tshark["available"] and not any(item["tshark_parsed"] for item in captures_meta):
        warnings.append("Captures were stored, but tshark did not produce timings. See metadata captures[].tshark_error.")

    keys = list(dict.fromkeys([*script_by_key.keys(), *tshark_by_key.keys()]))
    transactions: list[dict] = []
    for key in keys:
        script = script_by_key.get(key)
        captured = tshark_by_key.get(key)
        meta = (script or captured)["meta"]
        reported = script["reported"] if script else {}
        capture_file = ""
        for item in captures_meta:
            if (
                item["environment"] == meta["environment"]
                and item["scenario"] == meta["scenario"]
                and (item.get("coap_type") or "") == (meta.get("coap_type") or "")
                and item.get("mqtt_qos") == meta.get("mqtt_qos")
                and item["packet_loss_pct"] == meta["packet_loss_pct"]
            ):
                capture_file = item["stored_as"]
                break
        transactions.extend(
            align_series(
                script["rows"] if script else [],
                captured["rows"] if captured else [],
                meta,
                run_id=run_id,
                example_data=example_data,
                source_csv=_relative(script["source"], source) if script else "",
                capture_file=capture_file,
                reported=reported,
            )
        )
    frame = pd.DataFrame(transactions) if transactions else empty_transactions()
    frame = normalize_transactions(frame)
    summary = summarize_transactions(frame)
    if not example_data and not summary.empty:
        for _, series in summary.iterrows():
            for label, count in (("script", series["n_script"]), ("tshark", series["n_tshark"])):
                if count and int(count) != LAB_TRANSACTION_COUNT:
                    warnings.append(
                        f"{series['environment']} {series['scenario']} "
                        f"{series['coap_type']} qos={series['mqtt_qos']} "
                        f"loss={series['packet_loss_pct']}% has {label} n={int(count)}, "
                        f"not {LAB_TRANSACTION_COUNT}."
                    )
            if series["n_script"] and series["n_tshark"] and int(series["n_script"]) != int(series["n_tshark"]):
                warnings.append(
                    f"{series['environment']} {series['scenario']} loss={series['packet_loss_pct']}%: "
                    f"script n={int(series['n_script'])} and tshark n={int(series['n_tshark'])} differ; "
                    "rows were aligned by order and not forced to match."
                )

    negative = pd.to_numeric(frame.get("script_latency_ms"), errors="coerce")
    if negative is not None and (negative < 0).any():
        warnings.append("Some script latencies are negative. The clock around the client command went backwards.")

    tables = build_lab_tables(summary)
    _write_frame(frame, run_dir / "transactions.csv")
    _write_frame(summary, run_dir / "summary.csv")
    (run_dir / "lab_tables.json").write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
    _captures_readme(run_dir, len(captures_meta))
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": created,
        "example_data": example_data,
        "example_marker": example_doc,
        "source_mode": source_mode,
        "source_dir": str(source),
        "fingerprint": fingerprint,
        "notes": notes,
        "git": _git_metadata(repo_root()),
        "host": _host_metadata(),
        "parameters": {
            "script_defaults": SCRIPT_DEFAULTS,
            "procedure": TEST_PROCEDURE,
            "timing": TIMING_DEFINITIONS,
            "observed_packet_loss_pct": sorted(
                {int(value) for value in summary["packet_loss_pct"].dropna().tolist()}
            )
            if not summary.empty
            else [],
        },
        "tools_at_ingest": {
            "tshark": tshark,
        },
        "tshark": {
            **tshark,
            "field_command": tshark_command_template(),
            "fields": list(TSHARK_FIELDS),
        },
        "captures": captures_meta,
        "script_summaries": _read_script_summaries(source),
        "live": live_info,
        "warnings": warnings,
        "files": {
            "transactions": "transactions.csv",
            "summary": "summary.csv",
            "lab_tables": "lab_tables.json",
            "captures_dir": "captures",
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    _write_index(store)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "reused": False,
        "example_data": example_data,
        "warnings": warnings,
        "metadata": metadata,
    }


def run_environment_script(repo: Path, environment: str, timeout: float | None) -> dict:
    """Run one existing ``test.sh`` from its own directory, as the README does."""
    relative = ENV_SCRIPTS[environment]
    script = repo / relative
    if not script.is_file():
        return {
            "script": relative,
            "cwd": str(script.parent),
            "returncode": 127,
            "stdout_tail": "",
            "stderr_tail": f"missing {script}",
        }
    try:
        proc = subprocess.run(
            ["bash", script.name],
            cwd=script.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "script": relative,
            "cwd": str(script.parent),
            "returncode": 124,
            "stdout_tail": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": f"timed out after {timeout}s",
        }
    return {
        "script": relative,
        "cwd": str(script.parent),
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-8000:],
        "stderr_tail": (proc.stderr or "")[-8000:],
    }


def collect(
    mode: str = "ingest",
    source: Path | None = None,
    store: Path | None = None,
    *,
    force: bool = False,
    environments: tuple[str, ...] = ("env1", "env2"),
    live_timeout_s: float | None = None,
    notes: str = "",
) -> dict:
    """Ingest existing results, or run ``test.sh`` when the machine can.

    Live mode needs the CoAP/MQTT/HTTP tools, tshark, and passwordless sudo for
    ``tc netem``. If those are missing it does not start the scripts; it ingests
    ``lab_results`` when that tree has files, otherwise the labeled example fixture.
    """
    root = repo_root()
    store = Path(store) if store else default_store()
    store.mkdir(parents=True, exist_ok=True)
    mode_name = mode.lower().strip()
    if mode_name not in {"ingest", "live"}:
        raise ValueError("mode must be 'ingest' or 'live'")
    warnings: list[str] = []
    live_info = None
    chosen = source
    used_mode = mode_name
    if mode_name == "live":
        status = check_tools()
        requested = [item for item in environments if item in ENV_SCRIPTS]
        runnable = [item for item in requested if item in status["live_ready_environments"]]
        if not runnable:
            warnings.append(
                "Live tests were not started. "
                + " ".join(status["live_blockers"])
                + " Falling back to ingest."
            )
            used_mode = "ingest"
        else:
            skipped = [item for item in requested if item not in runnable]
            if skipped:
                warnings.append(
                    "Skipped live environments with missing tools: " + ", ".join(skipped) + "."
                )
            logs = {}
            for environment in runnable:
                logs[environment] = run_environment_script(root, environment, live_timeout_s)
                code = logs[environment]["returncode"]
                if code != 0:
                    warnings.append(f"{environment} test.sh exited {code}. Partial CSVs and captures are still ingested.")
            live_info = {"tools": status, "scripts": logs}
            chosen = root / "lab_results"
            used_mode = "live"
    if chosen is None:
        chosen = default_source(root)
        if chosen.name == "sample_lab_results":
            warnings.append(
                "No lab_results latency CSVs or captures were found. "
                "Using notebooks/sample_lab_results. That tree is example data, not a measurement."
            )
    return ingest(
        chosen,
        store,
        force=force,
        notes=notes,
        source_mode=used_mode,
        live_info=live_info,
        extra_warnings=warnings,
    )


def load_transactions(store: Path, run_id: str | None = None) -> pd.DataFrame:
    store = Path(store)
    if run_id:
        paths = [store / run_id / "transactions.csv"]
    else:
        paths = sorted(store.glob("*/transactions.csv"))
    frames = []
    for path in paths:
        if path.is_file() and path.stat().st_size:
            frames.append(pd.read_csv(path))
    if not frames:
        return empty_transactions()
    return normalize_transactions(pd.concat(frames, ignore_index=True))


def load_metadata(store: Path, run_id: str | None = None) -> dict:
    store = Path(store)
    if run_id is None:
        latest = store / "latest.json"
        if latest.is_file():
            run_id = json.loads(latest.read_text(encoding="utf-8"))["run_id"]
        else:
            found = list(store.glob("*/metadata.json"))
            if not found:
                raise FileNotFoundError(f"No runs in {store}")
            run_id = max(found, key=lambda path: path.stat().st_mtime).parent.name
    path = store / run_id / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(store: Path) -> pd.DataFrame:
    rows = []
    for _path, meta in iter_run_metadata(Path(store)):
        git = meta.get("git") or {}
        host = meta.get("host") or {}
        tshark = meta.get("tshark") or {}
        rows.append(
            {
                "run_id": meta.get("run_id"),
                "created_at_utc": meta.get("created_at_utc"),
                "example_data": meta.get("example_data"),
                "source_mode": meta.get("source_mode"),
                "source_dir": meta.get("source_dir"),
                "git_commit": git.get("commit_short"),
                "git_branch": git.get("branch"),
                "hostname": host.get("hostname"),
                "tshark_available": tshark.get("available"),
                "capture_count": len(meta.get("captures") or []),
            }
        )
    return pd.DataFrame(rows)


def tshark_text_preview(pcap: Path, limit: int = 25) -> str:
    """Short text listing of a capture. The lab screenshots still come from Wireshark."""
    status = tshark_status()
    if not status["available"]:
        return status["reason"]
    command = [
        status["path"],
        "-r",
        str(pcap),
        "-n",
        "-c",
        str(limit),
        "-d",
        f"udp.port=={COAP_PORT},coap",
        "-d",
        f"tcp.port=={HTTP_PORT},http",
        "-d",
        f"tcp.port=={MQTT_PORT},mqtt",
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        return f"tshark timed out reading {pcap}"
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or f"tshark exited {proc.returncode}").strip()
    return proc.stdout.strip() or "(tshark printed no packets)"


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect TELE 6510 protocol results into notebooks/run-store")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Show which lab tools and tshark are available")
    ingest_parser = sub.add_parser("ingest", help="Ingest lab_results or another results tree")
    ingest_parser.add_argument("--source", type=Path, default=None)
    ingest_parser.add_argument("--store", type=Path, default=None)
    ingest_parser.add_argument("--force", action="store_true")
    live_parser = sub.add_parser("live", help="Run environment test.sh when tools exist, then ingest")
    live_parser.add_argument("--store", type=Path, default=None)
    live_parser.add_argument("--force", action="store_true")
    sub.add_parser("write-example", help="Rewrite notebooks/sample_lab_results (synthetic)")
    args = parser.parse_args(argv)
    if args.command == "check":
        _print_json(check_tools())
        return 0
    if args.command == "write-example":
        from example_fixture import write_example_fixture

        destination = repo_root() / "notebooks" / "sample_lab_results"
        write_example_fixture(destination)
        print(destination)
        return 0
    if args.command == "ingest":
        result = collect(mode="ingest", source=args.source, store=args.store, force=args.force)
    else:
        result = collect(mode="live", store=args.store, force=args.force)
    _print_json(
        {
            "run_id": result["run_id"],
            "run_dir": result["run_dir"],
            "reused": result["reused"],
            "example_data": result["example_data"],
            "warnings": result["warnings"],
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
