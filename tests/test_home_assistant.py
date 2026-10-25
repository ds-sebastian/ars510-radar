"""Home Assistant bridge: signal decode, car state, discovery / state publishing, the MQTT client and autostart."""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "home_assistant"))

from ars510_ha import bridge
from ars510_ha.car import CarState
from ars510_ha.entities import ENTITIES, state_payload
from ars510_ha.mqtt import MqttClient, connect_packet, publish_packet
from ars510_ha.signals import S, Signal, extract


def frame(**bytes_at: int) -> bytes:
    data = bytearray(8)
    for k, v in bytes_at.items():
        data[int(k[1:])] = v
    return bytes(data)


def awake(car: CarState, t0: float, t1: float, *extra: tuple[int, bytes]) -> None:
    """Car-bus traffic at 20 Hz from t0 to t1 plus the given (address, payload) frames."""
    for i in range(int((t1 - t0) * 20) + 1):
        t = t0 + i / 20
        car.feed(t, 0, 0xB4, bytes.fromhex("0000000000271000"))
        for addr, data in extra:
            car.feed(t, 0, addr, data)


def test_extract_big_and_little_endian():
    assert extract(bytes.fromhex("0000000000271000"), S["speed_kph"]) == pytest.approx(100.0)
    assert extract(frame(b4=0x28, b5=0xF6), S["lead_rel_speed_kph"]) == -10
    little = Signal("X", 0, 21, 3, big_endian=False)  # LIGHT_STALK HEADLIGHT_MODE layout
    assert extract(frame(b2=0b1110_0000), little) == 7
    assert extract(bytes(2), S["odometer"]) is None  # too short


def test_body_frames():
    car = CarState()
    car.feed(0, 0, 0x620, frame(b5=0x20, b7=0x40))  # DOOR_OPEN_FL (45), SEATBELT_DRIVER_UNLATCHED (62)
    car.feed(0, 0, 0x127, frame(b5=0x30))           # GEAR_PACKET_HYBRID 3 = D
    car.feed(0, 0, 0x611, bytes.fromhex("0000000400002710"))  # ODOMETER 10000 (bytes 4-7), UNITS 2 = miles (bits 26-25)
    car.feed(0, 0, 0x638, frame(b2=0x10))           # LOCK_STATUS 1 = unlocked
    v = car.values(0)
    assert v["door_fl"] and not v["door_fr"] and v["seatbelt_driver_unlatched"]
    assert v["gear"] == "D" and v["unlocked"]
    assert v["odometer_km"] == pytest.approx(16093.44)


def test_radar_frames_from_docs_13():
    car = CarState()
    awake(car, 0, 3, (0x411, bytes.fromhex("0020000000008000")), (0x344, bytes.fromhex("0000010000000050")),
          (0x365, frame(b4=0xFC)))
    v = car.values(3)
    assert v["pcs_state"] == "on" and v["pcs_sensitivity"] == "mid" and not v["radar_blocked"]
    assert v["pcs_braking_available"] is True and v["lead_distance_m"] is None
    assert car.pop_events() == []
    car.feed(3.05, 0, 0x411, bytes.fromhex("1020000300008000"))  # PCS alarm on the dash: FCW (U3)
    car.feed(3.05, 0, 0x344, bytes.fromhex("0000030000000052"))  # PCSALM
    car.feed(3.05, 0, 0x283, bytes.fromhex("000000001000 9C".replace(" ", "")))  # STATE 4: not emergency braking
    car.feed(3.05, 0, 0x365, frame(b4=40, b5=0xF6))
    assert car.pop_events() == ["forward_collision_warning", "pcs_alarm"]
    v = car.values(3.05)
    assert v["lead_distance_m"] == 40 and v["lead_rel_speed_kph"] == -10
    car.feed(3.1, 0, 0x283, bytes.fromhex("000000000C0000"))  # STATE 3
    assert car.pop_events() == ["emergency_braking"]


def test_presence_needs_an_awake_bus():
    car = CarState()
    assert car.values(0)["pcs_braking_available"] is None
    awake(car, 0, 1, (0x344, bytes(8)))
    assert car.values(1)["pcs_braking_available"] is None  # first seconds awake: not yet known
    awake(car, 1, 3, (0x344, bytes(8)))
    assert car.values(3)["pcs_braking_available"] is True
    awake(car, 3, 6)  # radar disabled over UDS: the car bus runs, 0x344 stops
    assert car.values(6)["pcs_braking_available"] is False
    assert car.values(30)["pcs_braking_available"] is None  # car off


def test_stale_pcs_hud_reads_unknown():
    car = CarState()
    awake(car, 0, 3, (0x411, bytes.fromhex("0020000000008000")))
    awake(car, 3, 8)
    assert car.values(8)["pcs_state"] is None


def test_every_value_has_an_entity():
    car = CarState()
    for (bus, addr) in {(s.bus, s.addr) for s in S.values()}:
        car.feed(0, bus, addr, bytes(8))
    assert set(car.values(0)) <= set(ENTITIES)
    assert set(bridge.device_values({}, True)) <= set(ENTITIES)


def test_publisher_discovers_once_and_throttles():
    sent = []
    pub = bridge.Publisher(lambda t, p, r: sent.append((t, p, r)), "car", "Car")
    pub.on_connect()
    assert [t for t, _, _ in sent] == ["ars510_ha/car/status", "homeassistant/binary_sensor/car/online/config",
                                       "homeassistant/event/car/safety_event/config"]
    sent.clear()
    pub.update({"speed_kph": 50.0, "lead_distance_m": None}, [], 0)
    assert [t for t, _, _ in sent] == ["homeassistant/sensor/car/speed_kph/config", "ars510_ha/car/speed_kph"]
    config = json.loads(sent[0][1])
    assert config["unique_id"] == "car_speed_kph" and config["device_class"] == "speed"
    sent.clear()
    pub.update({"speed_kph": 51.0}, [], 1)       # within speed's 5 s interval
    pub.update({"speed_kph": 51.0, "door_fl": True}, ["pcs_alarm"], 6)
    assert [(t, p) for t, p, _ in sent if not t.startswith("homeassistant/")] == [
        ("ars510_ha/car/speed_kph", "51"), ("ars510_ha/car/door_fl", "ON"),
        ("ars510_ha/car/safety_event", '{"event_type": "pcs_alarm"}')]
    sent.clear()
    pub.on_connect()                             # a reconnect republishes discovery, then every state
    pub.update({}, [], 7)
    assert ("ars510_ha/car/speed_kph", "51", True) in sent and ("ars510_ha/car/door_fl", "ON", True) in sent


def test_state_payloads():
    assert state_payload("door_fl", False) == "OFF"
    assert state_payload("lead_distance_m", None) == "None"
    assert state_payload("battery_voltage", 12.40) == "12.4"
    assert json.loads(state_payload("location", {"latitude": 1.5})) == {"latitude": 1.5}


def test_mqtt_packets():
    assert publish_packet("a/b", "ON", retain=True) == b"\x31\x07\x00\x03a/bON"
    p = connect_packet("id", 60, "u", "pw", will=("s", "offline", True))
    assert p[0] == 0x10 and p[2:10] == b"\x00\x04MQTT\x04\xe6" and p[10:12] == b"\x00\x3c"
    long = publish_packet("t", "x" * 200)
    assert long[1:3] == bytes([0x80 | (203 % 128), 203 // 128])


def test_mqtt_client_against_a_fake_broker():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = []

    def broker():
        conn, _ = server.accept()
        conn.recv(1024)
        conn.sendall(b"\x20\x02\x00\x00")
        while chunk := conn.recv(1024):
            received.append(chunk)
        conn.close()

    thread = threading.Thread(target=broker, daemon=True)
    thread.start()
    client = MqttClient("127.0.0.1", server.getsockname()[1], will=("s", "offline", True))
    client.connect()
    client.publish("ars510_ha/car/door_fl", "ON", retain=True)
    client.loop()
    client.disconnect()
    thread.join(5)
    server.close()
    assert b"".join(received) == publish_packet("ars510_ha/car/door_fl", "ON", True) + b"\xe0\x00"


def test_autostart_is_idempotent_and_removable(tmp_path):
    continue_sh = tmp_path / "continue.sh"
    original = "#!/usr/bin/bash\n\ncd /data/openpilot\nexec ./launch_openpilot.sh\n"
    continue_sh.write_text(original)
    start = Path("/data/ars510-radar/home_assistant/start.sh")
    bridge.install_autostart(continue_sh, start)
    bridge.install_autostart(continue_sh, start)
    text = continue_sh.read_text()
    assert text.count(bridge.AUTOSTART_BEGIN) == 1
    assert text.index(f"{start} &") < text.index("exec ./launch_openpilot.sh")
    assert bridge.remove_autostart_text(text) == original


def test_replay_of_a_bundled_sample(capsys):
    assert bridge.main(["--config", "", "--replay", str(REPO / "data/sample/highway_following_30s.csv.gz"),
                        "--dry-run"]) == 0
    out = capsys.readouterr()
    assert "ars510_ha/rav4/speed_kph (retained): 1" in out.out
    assert "bus 0 0x0B4 SPEED" in out.err


def test_readme_lists_every_entity():
    readme = (REPO / "home_assistant/README.md").read_text()
    assert [key for key in ENTITIES if f"`{key}`" not in readme] == []
