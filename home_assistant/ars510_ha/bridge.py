"""Bridge from openpilot's CAN and device messages to Home Assistant over MQTT discovery (home_assistant/README.md).

On the comma device it reads cereal's `can`, `pandaStates`, `deviceState`, `selfdriveState` / `controlsState` and
GPS services; `--replay` feeds a CAN CSV (data/sample format) or an openpilot rlog / qlog through the same code,
and `--dry-run` prints the MQTT messages instead of sending them.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .car import CarState
from .entities import ENTITIES, discovery, state_payload
from .mqtt import MqttClient
from .signals import BY_FRAME, PRESENCE

PUBLISH_PERIOD_S = 0.5
AUTOSTART_BEGIN = "# >>> ars510 home assistant bridge >>>"
AUTOSTART_END = "# <<< ars510 home assistant bridge <<<"
DEFAULTS = {"host": None, "port": 1883, "username": None, "password": None, "tls": False, "node_id": "rav4",
            "name": "RAV4", "discovery_prefix": "homeassistant", "location": True}

Send = Callable[[str, str, bool], None]


class Publisher:
    """Publishes discovery once per entity (when it first has a value) and states when they change."""

    def __init__(self, send: Send, node_id: str, name: str, prefix: str = "homeassistant") -> None:
        self.send, self.node_id, self.prefix = send, node_id, prefix
        self.base = f"ars510_ha/{node_id}"
        self.status_topic = f"{self.base}/status"
        self.device = {"identifiers": [f"ars510_ha_{node_id}"], "name": name, "manufacturer": "Toyota",
                       "model": "RAV4 TSS2 (ARS510 radar)"}
        self.discovered: set[str] = set()
        self.current: dict[str, object] = {}
        self.published: dict[str, object] = {}
        self.published_t: dict[str, float] = {}

    def _discover(self, key: str) -> None:
        topic, payload = discovery(key, self.node_id, self.base, self.device)
        self.send(f"{self.prefix}/{topic}", json.dumps(payload), True)
        self.discovered.add(key)

    def on_connect(self) -> None:
        """After every (re)connect: availability, every discovery config sent so far, and every current state."""
        self.send(self.status_topic, "online", True)
        for key in sorted(self.discovered | {"online", "safety_event"}):
            self._discover(key)
        self.published.clear()
        self.published_t.clear()

    def update(self, values: dict[str, object], events: Iterable[str], now: float) -> None:
        self.current.update(values)
        for key, value in self.current.items():
            ent = ENTITIES.get(key)
            if ent is None or (value is None and key not in self.discovered):
                continue
            if key in self.published and self.published[key] == value:
                continue
            if key in self.published and now - self.published_t.get(key, -1e9) < ent.min_interval_s:
                continue
            if key not in self.discovered:
                self._discover(key)
            self.send(f"{self.base}/{key}", state_payload(key, value), True)
            self.published[key], self.published_t[key] = value, now
        for event in events:
            self.send(f"{self.base}/safety_event", state_payload("safety_event", {"event_type": event}), False)


class Link:
    """Keeps the MQTT connection up, with backoff; a publisher's send that fails waits for the next connect."""

    def __init__(self, client: MqttClient, log: Callable[[str], None] = print) -> None:
        self.client, self.log = client, log
        self.publisher: Publisher | None = None
        self.retry_at, self.backoff = 0.0, 2.0

    def send(self, topic: str, payload: str, retain: bool) -> None:
        if self.client.connected:
            try:
                self.client.publish(topic, payload, retain)
            except OSError as e:
                self.log(f"mqtt: publish failed ({e}), reconnecting")

    def tick(self, now: float) -> None:
        if self.client.connected:
            self.client.loop()
            return
        if now < self.retry_at:
            return
        try:
            self.client.connect()
        except OSError as e:
            self.log(f"mqtt: cannot reach {self.client.host}:{self.client.port} ({e}); retry in {self.backoff:.0f} s")
            self.retry_at, self.backoff = now + self.backoff, min(self.backoff * 2, 60.0)
            return
        self.log(f"mqtt: connected to {self.client.host}:{self.client.port}")
        self.backoff = 2.0
        if self.publisher is not None:
            self.publisher.on_connect()


def device_values(msgs: dict[str, object], location: bool) -> dict[str, object]:
    """Values from the latest cereal messages by service name (a SubMaster or the last messages of a log)."""
    v: dict[str, object] = {}
    panda = msgs.get("pandaStates")
    if panda is not None and len(panda):
        v["battery_voltage"] = round(panda[0].voltage / 1000, 2)
        v["ignition"] = bool(panda[0].ignitionLine or panda[0].ignitionCan)
    dev = msgs.get("deviceState")
    if dev is not None:
        v["device_temp"] = round(dev.maxTempC)
        v["free_space"] = round(dev.freeSpacePercent)
    for service in ("selfdriveState", "controlsState"):
        if msgs.get(service) is not None:
            v["engaged"] = bool(msgs[service].enabled)
            break
    if location:
        for service in ("gpsLocationExternal", "gpsLocation"):
            gps = msgs.get(service)
            if gps is not None and (getattr(gps, "hasFix", False) or gps.flags % 2):
                v["location"] = {"latitude": round(gps.latitude, 6), "longitude": round(gps.longitude, 6),
                                 "gps_accuracy": round(gps.horizontalAccuracy, 1), "altitude": round(gps.altitude),
                                 "speed": round(gps.speed * 3.6), "course": round(gps.bearingDeg)}
                break
    return v


def run_device(publisher: Publisher, link: Link, location: bool) -> None:
    from cereal import messaging
    from cereal.services import SERVICE_LIST

    wanted = ["pandaStates", "deviceState", "selfdriveState", "controlsState", "gpsLocationExternal", "gpsLocation"]
    services = [s for s in wanted if s in SERVICE_LIST]
    if "selfdriveState" in services:
        services.remove("controlsState")  # openpilot moved `enabled` to selfdriveState; older forks only have controlsState
    sm = messaging.SubMaster(services)
    can = messaging.sub_sock("can")
    car = CarState()
    next_publish = 0.0
    while True:
        sm.update(100)
        now = time.monotonic()
        for msg in messaging.drain_sock(can):
            for c in msg.can:
                if c.src < 128:  # 128+ are the panda's echoes of what openpilot sends
                    car.feed(now, c.src, c.address, c.dat)
        link.tick(now)
        if now >= next_publish:
            msgs = {s: sm[s] for s in services if sm.recv_frame[s] > 0}
            publisher.update({**car.values(now), **device_values(msgs, location)}, car.pop_events(), now)
            next_publish = now + PUBLISH_PERIOD_S


def read_log(path: Path) -> Iterable[tuple[float, str, object]]:
    """(t, kind, payload) from a CAN CSV (t_s, bus, address, data_hex) or an openpilot log via its LogReader."""
    if path.name.endswith((".csv", ".csv.gz")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt") as f:
            for row in csv.DictReader(f):
                yield float(row["t_s"]), "can", (int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"]))
        return
    from openpilot.tools.lib.logreader import LogReader
    t0 = None
    for msg in LogReader(str(path)):
        t0 = msg.logMonoTime if t0 is None else t0
        t, which = (msg.logMonoTime - t0) * 1e-9, msg.which()
        if which == "can":
            for c in msg.can:
                yield t, "can", (c.src, c.address, bytes(c.dat))
        else:
            yield t, which, getattr(msg, which)


def run_replay(path: Path, publisher: Publisher, location: bool) -> CarState:
    car, msgs, next_publish, t = CarState(), {}, 0.0, 0.0
    for t, kind, payload in read_log(path):
        if kind == "can":
            bus, addr, data = payload
            if bus < 128:
                car.feed(t, bus, addr, data)
        else:
            msgs[kind] = payload
        if t >= next_publish:
            publisher.update({**car.values(t), **device_values(msgs, location)}, car.pop_events(), t)
            next_publish = t + PUBLISH_PERIOD_S
    publisher.update({**car.values(t), **device_values(msgs, location)}, car.pop_events(), t + 3600)
    return car


def coverage(car: CarState) -> list[str]:
    """Which of the bridge's messages the log carried: the check for the ◐ rows on your own car."""
    names = {key: sigs[0][1].message for key, sigs in BY_FRAME.items()}
    for name, key in PRESENCE.items():
        names.setdefault(key, name)
    return [f"  bus {bus} 0x{addr:03X} {names[bus, addr]:<28} {car.frame_counts.get((bus, addr), 0):>8} frames"
            for bus, addr in sorted(names)]


def install_autostart(continue_sh: Path, start_sh: Path) -> str:
    """Adds one marked line to /data/continue.sh (AGNOS's boot script, outside the openpilot checkout, so fork
    updates keep it) that starts the bridge in the background before openpilot."""
    text = continue_sh.read_text()
    text = remove_autostart_text(text)
    block = f"{AUTOSTART_BEGIN}\n{start_sh} &\n{AUTOSTART_END}\n"
    lines = text.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.lstrip().startswith("exec ")), len(lines))
    continue_sh.write_text("".join(lines[:at]) + block + "".join(lines[at:]))
    return f"autostart added to {continue_sh}"


def remove_autostart_text(text: str) -> str:
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == AUTOSTART_BEGIN:
            skip = True
        elif line.strip() == AUTOSTART_END:
            skip = False
        elif not skip:
            out.append(line)
    return "".join(out)


def load_config(args: argparse.Namespace) -> dict:
    cfg = dict(DEFAULTS)
    if args.config and Path(args.config).exists():
        cfg.update(json.loads(Path(args.config).read_text()))
    for key in DEFAULTS:
        value = getattr(args, key, None)
        if value is not None:
            cfg[key] = value
    return cfg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="/data/ars510_ha.json", help="JSON file with the keys below (default %(default)s)")
    p.add_argument("--host", help="MQTT broker, e.g. homeassistant.local")
    p.add_argument("--port", type=int)
    p.add_argument("--username")
    p.add_argument("--password")
    p.add_argument("--tls", action="store_true", default=None)
    p.add_argument("--node-id", dest="node_id", help="MQTT node id and unique-id prefix (default rav4)")
    p.add_argument("--name", help="device name in Home Assistant (default RAV4)")
    p.add_argument("--discovery-prefix", dest="discovery_prefix")
    p.add_argument("--no-location", dest="location", action="store_false", default=None, help="do not publish GPS")
    p.add_argument("--replay", type=Path, help="feed a CAN CSV or an openpilot rlog / qlog instead of the live device")
    p.add_argument("--dry-run", action="store_true", help="print the MQTT messages instead of sending them")
    p.add_argument("--install-autostart", nargs="?", const="/data/continue.sh", metavar="CONTINUE_SH")
    p.add_argument("--remove-autostart", nargs="?", const="/data/continue.sh", metavar="CONTINUE_SH")
    args = p.parse_args(argv)

    if args.install_autostart or args.remove_autostart:
        start_sh = Path(__file__).resolve().parents[1] / "start.sh"
        if args.install_autostart:
            print(install_autostart(Path(args.install_autostart), start_sh))
        else:
            path = Path(args.remove_autostart)
            path.write_text(remove_autostart_text(path.read_text()))
            print(f"autostart removed from {path}")
        return 0

    cfg = load_config(args)
    if args.dry_run:
        def send(topic: str, payload: str, retain: bool) -> None:
            print(f"{topic}{' (retained)' if retain else ''}: {payload}")
        publisher = Publisher(send, cfg["node_id"], cfg["name"], cfg["discovery_prefix"])
        publisher.on_connect()
        link = None
    else:
        if not cfg["host"]:
            p.error(f"no MQTT broker: set \"host\" in {args.config} or pass --host")
        base = f"ars510_ha/{cfg['node_id']}"
        client = MqttClient(cfg["host"], cfg["port"], f"ars510_ha_{cfg['node_id']}", cfg["username"], cfg["password"],
                            cfg["tls"], will=(f"{base}/status", "offline", True))
        link = Link(client)
        publisher = Publisher(link.send, cfg["node_id"], cfg["name"], cfg["discovery_prefix"])
        link.publisher = publisher

    if args.replay:
        if link is not None:  # a replay to a real broker: connect once, then stream the log
            link.tick(time.monotonic())
            if not link.client.connected:
                return 1
        car = run_replay(args.replay, publisher, cfg["location"])
        print("messages in the log:", file=sys.stderr)
        print("\n".join(coverage(car)), file=sys.stderr)
        if link is not None:
            link.send(publisher.status_topic, "offline", True)
            link.client.disconnect()
        return 0
    if link is None:
        p.error("--dry-run needs --replay (the live bridge sends to a broker)")
    run_device(publisher, link, cfg["location"])
    return 0
