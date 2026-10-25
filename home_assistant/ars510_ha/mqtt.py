"""A publish-only MQTT 3.1.1 client on the standard library (openpilot's Python has no MQTT package).

QoS 0, retained messages, a last-will message for availability, keepalive pings and optional TLS. Nothing is
subscribed: the broker's retained discovery and state messages cover a Home Assistant restart.
"""
from __future__ import annotations

import socket
import ssl
import struct
import time


class MqttError(OSError):
    pass


def _str(s: str | bytes) -> bytes:
    b = s.encode() if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def _packet(header: int, body: bytes) -> bytes:
    n, out = len(body), bytearray([header])
    while True:  # remaining length, 7 bits per byte
        n, digit = divmod(n, 128)
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out) + body


def connect_packet(client_id: str, keepalive: int, username: str | None = None, password: str | None = None,
                   will: tuple[str, str, bool] | None = None) -> bytes:
    flags, payload = 0x02, _str(client_id)  # clean session
    if will:
        topic, message, retain = will
        flags |= 0x04 | (0x20 if retain else 0)
        payload += _str(topic) + _str(message)
    if username is not None:
        flags |= 0x80
        payload += _str(username)
        if password is not None:
            flags |= 0x40
            payload += _str(password)
    return _packet(0x10, _str("MQTT") + bytes([4, flags]) + struct.pack("!H", keepalive) + payload)


def publish_packet(topic: str, payload: str | bytes, retain: bool = False) -> bytes:
    body = payload.encode() if isinstance(payload, str) else payload
    return _packet(0x30 | (0x01 if retain else 0), _str(topic) + body)


class MqttClient:
    def __init__(self, host: str, port: int = 1883, client_id: str = "ars510_ha", username: str | None = None,
                 password: str | None = None, tls: bool = False, keepalive: int = 60,
                 will: tuple[str, str, bool] | None = None, timeout: float = 5.0) -> None:
        self.host, self.port, self.client_id = host, port, client_id
        self.username, self.password, self.tls = username, password, tls
        self.keepalive, self.will, self.timeout = keepalive, will, timeout
        self.sock: socket.socket | None = None
        self._last_send = 0.0

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            if self.tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            sock.sendall(connect_packet(self.client_id, self.keepalive, self.username, self.password, self.will))
            ack = b""
            while len(ack) < 4:
                chunk = sock.recv(4 - len(ack))
                if not chunk:
                    raise MqttError("connection closed before CONNACK")
                ack += chunk
            if ack[0] != 0x20 or ack[3] != 0:
                raise MqttError(f"broker refused the connection (CONNACK return code {ack[3]})")
            sock.setblocking(False)
        except BaseException:
            sock.close()
            raise
        self.sock, self._last_send = sock, time.monotonic()

    def _send(self, data: bytes) -> None:
        if self.sock is None:
            raise MqttError("not connected")
        try:
            self.sock.settimeout(self.timeout)
            self.sock.sendall(data)
            self.sock.setblocking(False)
        except OSError:
            self.close()
            raise
        self._last_send = time.monotonic()

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self._send(publish_packet(topic, payload, retain))

    def loop(self) -> None:
        """Keepalive ping and drain of what the broker sends (PINGRESP); notices a closed connection."""
        if self.sock is None:
            return
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    self.close()
                    return
        except (BlockingIOError, ssl.SSLWantReadError):
            pass
        except OSError:
            self.close()
            return
        if time.monotonic() - self._last_send > self.keepalive / 2:
            self._send(b"\xc0\x00")  # PINGREQ

    def disconnect(self) -> None:
        if self.sock is not None:
            try:
                self._send(b"\xe0\x00")
            except OSError:
                pass
            self.close()

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None
