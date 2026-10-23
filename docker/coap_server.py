#!/usr/bin/env python3
"""CoAP edge server for the container lab.

GET of any URI (the lab uses ``/time``) returns exactly ``0123456789``.
A confirmable request gets a piggybacked ACK: type 2, code 2.05, the same
message id and token. A non-confirmable request gets a non-confirmable 2.05
with a new message id and the same token, so a capture can still pair it.
"""

from __future__ import annotations

import socket
import sys
import threading

PAYLOAD = b"0123456789"
CODE_GET = 1
CODE_CONTENT = (2 << 5) | 5  # 2.05
# Content-Format text/plain; charset=utf-8 is option 12, value 0.
CONTENT_FORMAT = b"\xc1\x00"


def response_for(data: bytes, mid_counter: list[int]) -> bytes | None:
    """Return one CoAP response datagram, or None when ``data`` is not a GET."""
    if len(data) < 4:
        return None
    first = data[0]
    version = first >> 6
    msg_type = (first >> 4) & 0x3
    token_len = first & 0x0F
    if version != 1 or token_len > 8 or len(data) < 4 + token_len:
        return None
    code = data[1]
    if code != CODE_GET:
        return None
    mid = int.from_bytes(data[2:4], "big")
    token = data[4 : 4 + token_len]
    if msg_type == 0:  # CON -> piggybacked ACK
        resp_type = 2
        resp_mid = mid
    elif msg_type == 1:  # NON -> NON 2.05
        resp_type = 1
        mid_counter[0] = (mid_counter[0] + 1) & 0xFFFF
        if mid_counter[0] == 0:
            mid_counter[0] = 1
        resp_mid = mid_counter[0]
    else:
        return None
    header = bytes([(1 << 6) | (resp_type << 4) | token_len, CODE_CONTENT])
    return header + resp_mid.to_bytes(2, "big") + token + CONTENT_FORMAT + b"\xff" + PAYLOAD


def serve_socket(sock: socket.socket, ready: threading.Event | None = None) -> None:
    counter = [1]
    if ready is not None:
        ready.set()
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except OSError:
            return
        reply = response_for(data, counter)
        if reply is not None:
            sock.sendto(reply, addr)


def serve(host: str = "0.0.0.0", port: int = 5683) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    serve_socket(sock)


if __name__ == "__main__":
    bind_host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    bind_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5683
    serve(bind_host, bind_port)
