#!/usr/bin/env python3
"""Unit test for the edge CoAP server. Does not need Docker."""

from __future__ import annotations

import importlib.util
import socket
import threading
import unittest
from pathlib import Path

_PATH = Path(__file__).with_name("coap_server.py")
_SPEC = importlib.util.spec_from_file_location("coap_server", _PATH)
assert _SPEC and _SPEC.loader
coap_server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(coap_server)


class CoapServerTest(unittest.TestCase):
    def test_confirmable_is_piggybacked_ack_with_ten_byte_body(self) -> None:
        request = bytes([0x41, 0x01, 0x00, 0x07, 0xAB, 0xB4]) + b"time"
        reply = coap_server.response_for(request, [1])
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply[0] >> 6, 1)
        self.assertEqual((reply[0] >> 4) & 0x3, 2)
        self.assertEqual(reply[0] & 0x0F, 1)
        self.assertEqual(reply[1], 69)
        self.assertEqual(reply[2:4], b"\x00\x07")
        self.assertEqual(reply[4:5], b"\xab")
        self.assertTrue(reply.endswith(b"\xff0123456789"))
        self.assertEqual(len(reply[reply.rfind(b"\xff") + 1 :]), 10)

    def test_non_confirmable_keeps_token_and_uses_a_new_mid(self) -> None:
        request = bytes([0x51, 0x01, 0x00, 0x09, 0xCD])
        counter = [4]
        reply = coap_server.response_for(request, counter)
        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual((reply[0] >> 4) & 0x3, 1)
        self.assertNotEqual(reply[2:4], b"\x00\x09")
        self.assertEqual(reply[4:5], b"\xcd")
        self.assertEqual(reply[-10:], b"0123456789")
        self.assertEqual(counter[0], 5)

    def test_non_get_is_ignored(self) -> None:
        self.assertIsNone(coap_server.response_for(bytes([0x40, 0x02, 0x00, 0x01]), [1]))
        self.assertIsNone(coap_server.response_for(bytes([0x40, 0x00, 0x00, 0x01]), [1]))
        self.assertIsNone(coap_server.response_for(b"\x40\x01", [1]))

    def test_udp_round_trip(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        ready = threading.Event()
        thread = threading.Thread(target=coap_server.serve_socket, args=(sock, ready), daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2))
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2)
        client.sendto(bytes([0x40, 0x01, 0x12, 0x34]), ("127.0.0.1", port))
        data, _addr = client.recvfrom(256)
        self.assertEqual(data[1], 69)
        self.assertEqual(data[2:4], b"\x12\x34")
        self.assertEqual((data[0] >> 4) & 0x3, 2)
        self.assertTrue(data.endswith(b"0123456789"))
        client.close()
        sock.close()


if __name__ == "__main__":
    unittest.main()
