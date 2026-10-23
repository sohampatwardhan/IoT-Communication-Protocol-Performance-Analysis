"""Tests for parsing test.sh CSVs, tshark field rows, and the lab tables."""

from __future__ import annotations

import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import iot_results as iot
from example_fixture import write_example_fixture


def _field(**kwargs) -> dict:
    base = {name: "" for name in iot.TSHARK_FIELDS}
    base.update({key: "" if value is None else str(value) for key, value in kwargs.items()})
    return base


class ScriptCsvTests(unittest.TestCase):
    def test_simple_csv_ignores_shifted_average_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env1" / "latencies" / "coap_confirmable_0pct.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "Transaction,Timestamp,Latency_ms",
                        "1,2026-01-15-12:00:01,10",
                        "2,2026-01-15-12:00:02,30",
                        "Average,999",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            parsed = iot.parse_script_csv(path)
            self.assertEqual([row["script_latency_ms"] for row in parsed["rows"]], [10.0, 30.0])
            self.assertEqual(parsed["reported"]["headline"], 999.0)
            self.assertEqual(parsed["meta"]["environment"], "env1")
            self.assertEqual(parsed["meta"]["coap_type"], "confirmable")
            self.assertEqual(parsed["meta"]["packet_loss_pct"], 0)

    def test_combined_average_footer_is_not_shifted_into_the_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env1" / "latencies" / "coap_confirmable_http_5pct.csv"
            path.parent.mkdir(parents=True)
            path.write_text(
                "\n".join(
                    [
                        "Transaction,Timestamp,CoAP_Latency_ms,HTTP_Latency_ms,Total_Latency_ms",
                        "1,2026-01-15-12:00:01,5,7,12",
                        "Average,1,2,3",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            parsed = iot.parse_script_csv(path)
            self.assertEqual(parsed["rows"][0]["script_latency_ms"], 12.0)
            self.assertEqual(parsed["rows"][0]["script_coap_latency_ms"], 5.0)
            self.assertEqual(parsed["rows"][0]["script_http_latency_ms"], 7.0)
            self.assertEqual(parsed["reported"]["coap"], 1.0)
            self.assertEqual(parsed["reported"]["http"], 2.0)
            self.assertEqual(parsed["reported"]["headline"], 3.0)

    def test_filename_patterns_cover_script_outputs(self):
        names = {
            "coap_confirmable_0pct.csv": ("coap", "confirmable", None, 0),
            "coap_non-confirmable_10pct.csv": ("coap", "non-confirmable", None, 10),
            "http_3pct.csv": ("http", "", None, 3),
            "coap_confirmable_http_5pct.csv": ("coap_http", "confirmable", None, 5),
            "mqtt_qos0_0pct.csv": ("mqtt", "", 0, 0),
            "mqtt_qos2_10pct.csv": ("mqtt", "", 2, 10),
            "coap_confirmable_mqtt_qos1_3pct.csv": ("coap_mqtt", "confirmable", 1, 3),
            "coap_confirmable_0pct.pcapng": ("coap", "confirmable", None, 0),
            "http_standard_5pct.pcapng": ("http", "", None, 5),
            "coap_http_non-confirmable_10pct.pcapng": ("coap_http", "non-confirmable", None, 10),
            "mqtt_qos1_3pct.pcapng": ("mqtt", "", 1, 3),
            "coap_mqtt_confirmable_qos2_0pct.pcapng": ("coap_mqtt", "confirmable", 2, 0),
        }
        for name, expected in names.items():
            meta = iot.parse_result_name(name)
            self.assertIsNotNone(meta, name)
            self.assertEqual(
                (meta["scenario"], meta["coap_type"], meta["mqtt_qos"], meta["packet_loss_pct"]),
                expected,
                name,
            )


class TsharkTests(unittest.TestCase):
    def test_command_uses_field_export(self):
        command = iot.build_tshark_command(Path("capture.pcapng"), binary="tshark")
        text = " ".join(command)
        self.assertIn("-T fields", text)
        self.assertIn("-E separator=,", text)
        self.assertIn("-e frame.time_epoch", text)
        self.assertIn("-e coap.mid", text)
        self.assertIn("-e coap.type", text)
        self.assertIn("-e mqtt.msgtype", text)
        self.assertIn("-e http.request.method", text)
        self.assertIn("-d udp.port==5683,coap", text)
        self.assertIn("-d tcp.port==8080,http", text)
        self.assertIn("-d tcp.port==1883,mqtt", text)
        self.assertEqual(command[command.index("-r") + 1], "capture.pcapng")

    def test_coap_pairs_by_token_not_arrival_order(self):
        rows = [
            _field(**{"frame.time_epoch": "10.000", "coap.type": "0", "coap.code": "1", "coap.mid": "1", "coap.token": "aa"}),
            _field(**{"frame.time_epoch": "11.000", "coap.type": "0", "coap.code": "1", "coap.mid": "2", "coap.token": "bb"}),
            _field(**{"frame.time_epoch": "11.500", "coap.type": "2", "coap.code": "69", "coap.mid": "2", "coap.token": "bb", "data.len": "4"}),
            _field(**{"frame.time_epoch": "12.000", "coap.type": "2", "coap.code": "69", "coap.mid": "1", "coap.token": "aa", "data.len": "10"}),
        ]
        measured = iot.measurements_from_tshark_rows(rows, "coap")
        self.assertEqual(len(measured), 2)
        self.assertAlmostEqual(measured[0]["latency_ms"], 2000.0)
        self.assertAlmostEqual(measured[1]["latency_ms"], 500.0)
        self.assertEqual(measured[0]["coap_payload_bytes"], 10)
        self.assertEqual(measured[1]["coap_payload_bytes"], 4)

    def test_http_pairs_on_tcp_stream(self):
        rows = [
            _field(**{"frame.time_epoch": "50", "tcp.stream": "1", "tcp.dstport": "8080", "http.request.method": "GET", "http.request.uri": "/time"}),
            _field(**{"frame.time_epoch": "50.020", "tcp.stream": "1", "tcp.srcport": "8080", "http.response.code": "200", "http.content_length": "10"}),
            _field(**{"frame.time_epoch": "51", "tcp.stream": "2", "tcp.dstport": "8080", "http.request.method": "GET"}),
            _field(**{"frame.time_epoch": "51.005", "tcp.stream": "2", "tcp.srcport": "8080", "http.response.code": "200", "http.content_length": "10"}),
        ]
        measured = iot.measurements_from_tshark_rows(rows, "http")
        self.assertAlmostEqual(measured[0]["latency_ms"], 20.0)
        self.assertAlmostEqual(measured[1]["latency_ms"], 5.0)
        self.assertEqual(measured[0]["http_payload_bytes"], 10)

    def test_mqtt_delivery_is_headline_and_handshake_is_separate(self):
        rows = [
            _field(**{"frame.time_epoch": "200.000", "tcp.dstport": "1883", "tcp.srcport": "40000", "mqtt.msgtype": "3", "mqtt.qos": "1", "mqtt.msgid": "7", "mqtt.topic": "iot/time", "mqtt.msg": "2026-01-15"}),
            _field(**{"frame.time_epoch": "200.003", "tcp.srcport": "1883", "tcp.dstport": "40001", "mqtt.msgtype": "3", "mqtt.qos": "1", "mqtt.msgid": "7", "mqtt.topic": "iot/time", "mqtt.msg": "2026-01-15"}),
            _field(**{"frame.time_epoch": "200.010", "tcp.srcport": "1883", "tcp.dstport": "40000", "mqtt.msgtype": "4", "mqtt.qos": "0", "mqtt.msgid": "7"}),
        ]
        measured = iot.measurements_from_tshark_rows(rows, "mqtt")
        self.assertEqual(len(measured), 1)
        self.assertAlmostEqual(measured[0]["latency_ms"], 3.0)
        self.assertEqual(measured[0]["kind"], "mqtt_delivery")
        self.assertAlmostEqual(measured[0]["mqtt_handshake_latency_ms"], 10.0)
        self.assertEqual(measured[0]["mqtt_payload_bytes"], 10)

    def test_mqtt_qos2_handshake_does_not_replace_missing_delivery(self):
        rows = [
            _field(**{"frame.time_epoch": "300.000", "tcp.dstport": "1883", "tcp.srcport": "40000", "mqtt.msgtype": "3", "mqtt.qos": "2", "mqtt.msgid": "9", "mqtt.msg": "timestamp"}),
            _field(**{"frame.time_epoch": "300.020", "tcp.srcport": "1883", "tcp.dstport": "40000", "mqtt.msgtype": "7", "mqtt.msgid": "9"}),
        ]
        measured = iot.measurements_from_tshark_rows(rows, "mqtt")
        self.assertIsNone(measured[0]["latency_ms"])
        self.assertAlmostEqual(measured[0]["mqtt_handshake_latency_ms"], 20.0)
        self.assertEqual(measured[0]["mqtt_payload_bytes"], 9)

    def test_combined_e2e_uses_coap_start_and_http_end(self):
        rows = [
            _field(**{"frame.time_epoch": "10.000", "coap.type": "0", "coap.code": "1", "coap.mid": "1", "coap.token": "aa"}),
            _field(**{"frame.time_epoch": "10.004", "coap.type": "2", "coap.code": "69", "coap.mid": "1", "coap.token": "aa", "data.len": "8"}),
            _field(**{"frame.time_epoch": "10.010", "tcp.stream": "4", "http.request.method": "GET", "http.request.uri": "/time"}),
            _field(**{"frame.time_epoch": "10.025", "tcp.stream": "4", "http.response.code": "200", "http.content_length": "8"}),
        ]
        measured = iot.measurements_from_tshark_rows(rows, "coap_http")
        self.assertAlmostEqual(measured[0]["latency_ms"], 25.0)
        self.assertAlmostEqual(measured[0]["coap_latency_ms"], 4.0)
        self.assertAlmostEqual(measured[0]["http_latency_ms"], 15.0)
        self.assertEqual(measured[0]["kind"], "e2e")

    def test_align_keeps_unequal_counts(self):
        meta = {
            "environment": "env1",
            "scenario": "coap",
            "protocol": "CoAP",
            "coap_type": "confirmable",
            "mqtt_qos": None,
            "packet_loss_pct": 0,
        }
        rows = iot.align_series(
            [{"transaction": 1, "script_timestamp": "t", "script_latency_ms": 10, "script_coap_latency_ms": 10, "script_http_latency_ms": None, "script_mqtt_latency_ms": None, "script_total_latency_ms": 10}],
            [{"request_epoch": 1.0, "response_epoch": 1.01, "latency_ms": 10.0, "kind": "coap_rtt", "coap_latency_ms": 10.0, "http_latency_ms": None, "mqtt_delivery_latency_ms": None, "mqtt_handshake_latency_ms": None, "coap_payload_bytes": 10, "http_payload_bytes": None, "mqtt_payload_bytes": None, "alignment_note": ""}, {"request_epoch": 2.0, "response_epoch": 2.02, "latency_ms": 20.0, "kind": "coap_rtt", "coap_latency_ms": 20.0, "alignment_note": ""}],
            meta,
            run_id="run",
            example_data=False,
            source_csv="env1/latencies/coap_confirmable_0pct.csv",
            capture_file="captures/env1/coap_confirmable_0pct.pcapng",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["script_latency_ms"], 10)
        self.assertIsNone(rows[1]["script_latency_ms"])
        self.assertIn("script rows=1", rows[0]["alignment_note"])
        self.assertEqual(rows[0]["coap_payload_bytes"], 10)


class LabTableTests(unittest.TestCase):
    def test_missing_loss_is_null_not_zero(self):
        summary = iot.summarize_transactions(
            iot.normalize_transactions(
                __import__("pandas").DataFrame(
                    [
                        {
                            "run_id": "r",
                            "example_data": False,
                            "environment": "env1",
                            "scenario": "coap",
                            "protocol": "CoAP",
                            "coap_type": "confirmable",
                            "mqtt_qos": None,
                            "packet_loss_pct": 0,
                            "transaction": 1,
                            "script_latency_ms": 12,
                            "script_coap_latency_ms": 12,
                        }
                    ]
                )
            )
        )
        table = iot.env1_q2_loss_table(summary, "script")
        self.assertEqual(list(table["packet_loss_pct"]), [0, 3, 5, 10])
        self.assertEqual(table.loc[table["packet_loss_pct"] == 0, "coap_confirmable_mean_ms"].iloc[0], 12)
        self.assertTrue(pd.isna(table.loc[table["packet_loss_pct"] == 10, "coap_confirmable_mean_ms"].iloc[0]))
        self.assertTrue(pd.isna(table.loc[table["packet_loss_pct"] == 0, "coap_nonconfirmable_mean_ms"].iloc[0]))

    def test_example_fixture_builds_lab_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample"
            store = Path(tmp) / "store"
            write_example_fixture(source)
            result = iot.ingest(source, store)
            self.assertTrue(result["example_data"])
            self.assertFalse(result["reused"])
            self.assertTrue(any("EXAMPLE DATA" in warning for warning in result["warnings"]))
            transactions = iot.load_transactions(store, result["run_id"])
            summary = iot.summarize_transactions(transactions)
            self.assertEqual(len(summary), 44)
            self.assertEqual(len(transactions), 44 * 3)
            q2 = iot.env1_q2_loss_table(summary, "script")
            self.assertEqual(len(q2), 4)
            confirmable_0 = q2.loc[q2["packet_loss_pct"] == 0, "coap_confirmable_mean_ms"].iloc[0]
            confirmable_10 = q2.loc[q2["packet_loss_pct"] == 10, "coap_confirmable_mean_ms"].iloc[0]
            nonconfirmable_10 = q2.loc[q2["packet_loss_pct"] == 10, "coap_nonconfirmable_mean_ms"].iloc[0]
            self.assertGreater(confirmable_10, confirmable_0)
            self.assertGreater(confirmable_10, nonconfirmable_10)
            self.assertEqual(int(q2["n_coap_confirmable"].iloc[0]), 3)
            q2_wire = iot.env1_q2_loss_table(summary, "tshark")
            self.assertTrue(q2_wire["coap_confirmable_mean_ms"].isna().all())
            env2 = iot.env2_q2_loss_table(summary, "script")
            qos0 = env2.loc[env2["packet_loss_pct"] == 0, "mqtt_qos0_mean_ms"].iloc[0]
            qos2 = env2.loc[env2["packet_loss_pct"] == 0, "mqtt_qos2_mean_ms"].iloc[0]
            self.assertGreater(qos2, qos0)
            self.assertEqual(int(env2["mqtt_payload_bytes_configured"].iloc[0]), 10)
            q1 = iot.env2_q1_delay(summary, "script")
            configured = q1.loc[q1["packet_loss_pct"] == 0, "mqtt_payload_bytes_configured"].iloc[0]
            self.assertEqual(int(configured), 9)
            compared = iot.env2_q4_mqtt_vs_http(summary, "script")
            self.assertEqual(len(compared), 4)
            self.assertIsNotNone(compared.loc[compared["packet_loss_pct"] == 0, "http_mean_ms"].iloc[0])
            self.assertIsNotNone(compared.loc[compared["packet_loss_pct"] == 0, "coap_mqtt_qos1_e2e_mean_ms"].iloc[0])
            sentence = iot.headline_sentence(iot.env1_q1_delay(summary, "script"), "Environment 1")
            self.assertIn("EXAMPLE DATA", sentence)
            self.assertIn("0% packet loss", sentence)
            metadata = iot.load_metadata(store, result["run_id"])
            self.assertEqual(metadata["captures"], [])
            self.assertIn("frame.time_epoch", metadata["tshark"]["field_command"])
            self.assertIn("coap.mid", metadata["tshark"]["field_command"])
            again = iot.ingest(source, store)
            self.assertTrue(again["reused"])
            self.assertEqual(again["run_id"], result["run_id"])
            forced = iot.ingest(source, store, force=True)
            self.assertFalse(forced["reused"])
            self.assertNotEqual(forced["run_id"], result["run_id"])

    def test_capture_is_linked_even_when_tshark_cannot_parse_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "lab_results"
            capture = source / "env1" / "captures" / "coap_confirmable_0pct.pcapng"
            latency = source / "env1" / "latencies" / "coap_confirmable_0pct.csv"
            capture.parent.mkdir(parents=True)
            latency.parent.mkdir(parents=True)
            capture.write_bytes(b"not a real pcapng")
            latency.write_text(
                "Transaction,Timestamp,Latency_ms\n1,2026-01-15-12:00:01,4\n",
                encoding="utf-8",
            )
            store = Path(tmp) / "store"
            result = iot.ingest(source, store)
            self.assertFalse(result["example_data"])
            meta = iot.load_metadata(store, result["run_id"])
            self.assertEqual(len(meta["captures"]), 1)
            stored = Path(result["run_dir"]) / meta["captures"][0]["stored_as"]
            self.assertTrue(stored.is_file())
            self.assertEqual(stored.read_bytes(), b"not a real pcapng")
            self.assertTrue(meta["captures"][0]["tshark_error"])
            frame = iot.load_transactions(store, result["run_id"])
            self.assertEqual(frame["script_latency_ms"].iloc[0], 4)
            self.assertTrue(iot.pd.isna(frame["tshark_latency_ms"].iloc[0]))

    def test_live_mode_does_not_launch_test_scripts_when_tools_are_missing(self):
        calls = []
        real = subprocess.run

        def wrapped(args, **kwargs):
            calls.append([str(part) for part in args])
            return real(args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample"
            write_example_fixture(source)
            store = Path(tmp) / "store"
            subprocess.run = wrapped
            try:
                # Point the default sample lookup at our fixture by ingesting explicitly
                # only if live falls back. Patch default_source via a missing lab_results
                # inside the real repo: collect() then uses the repo sample or lab_results.
                status = iot.check_tools()
                if status["live_ready_environments"]:
                    self.skipTest("live tools are installed; this test covers the fallback")
                result = iot.collect(mode="live", source=None, store=store)
            finally:
                subprocess.run = real
            launched = [call for call in calls if any(part.endswith("test.sh") for part in call)]
            self.assertEqual(launched, [])
            self.assertTrue(any("not started" in warning.lower() or "Falling back" in warning for warning in result["warnings"]))


def _ip_checksum(header: bytes) -> int:
    total = 0
    for index in range(0, len(header), 2):
        total += int.from_bytes(header[index : index + 2], "big")
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _ethernet_ipv4_udp(payload: bytes, src: str, dst: str, sport: int, dport: int) -> bytes:
    udp_len = 8 + len(payload)
    ip_len = 20 + udp_len
    ip_no_sum = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        ip_len,
        1,
        0,
        64,
        17,
        0,
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        ip_len,
        1,
        0,
        64,
        17,
        _ip_checksum(ip_no_sum),
        socket.inet_aton(src),
        socket.inet_aton(dst),
    )
    udp = struct.pack("!HHHH", sport, dport, udp_len, 0) + payload
    return b"\x02" * 6 + b"\x02" * 6 + b"\x08\x00" + ip + udp


def _write_pcap(path: Path, packets: list[tuple[float, bytes]]) -> None:
    with path.open("wb") as handle:
        handle.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for timestamp, packet in packets:
            seconds = int(timestamp)
            micros = int(round((timestamp - seconds) * 1_000_000))
            handle.write(struct.pack("<IIII", seconds, micros, len(packet), len(packet)))
            handle.write(packet)


class TsharkBinaryTests(unittest.TestCase):
    def test_real_tshark_reads_coap_exchange(self):
        if not shutil.which("tshark"):
            self.skipTest("tshark is not installed")
        # CON GET /time, token 0x61, mid 1. Piggybacked ACK 2.05, 10-byte payload.
        request = bytes.fromhex("4101000161b474696d65")
        response = bytes.fromhex("6145000161ff") + b"0123456789"
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp) / "coap_confirmable_0pct.pcap"
            _write_pcap(
                capture,
                [
                    (1_700_000_000.000, _ethernet_ipv4_udp(request, "127.0.0.1", "127.0.0.1", 40000, 5683)),
                    (1_700_000_000.012, _ethernet_ipv4_udp(response, "127.0.0.1", "127.0.0.1", 5683, 40000)),
                ],
            )
            rows = iot.export_tshark_fields(capture)
            measured = iot.measurements_from_tshark_rows(rows, "coap")
            self.assertEqual(len(measured), 1, rows)
            self.assertAlmostEqual(measured[0]["latency_ms"], 12.0, delta=0.05)
            self.assertEqual(measured[0]["coap_payload_bytes"], 10)
            self.assertEqual(measured[0]["kind"], "coap_rtt")


class ToolReportTests(unittest.TestCase):
    def test_check_tools_shape(self):
        report = iot.check_tools()
        self.assertIn("tshark", report)
        self.assertIn("live_ready_environments", report)
        self.assertIn("tools", report)
        self.assertIn("coap-client", report["tools"])


if __name__ == "__main__":
    unittest.main()
