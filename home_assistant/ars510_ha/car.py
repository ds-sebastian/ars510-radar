"""Car state for Home Assistant from raw CAN frames: the latest value of each signal, message presence, and
safety events (FCW, PCS alarm, emergency braking) on their rising edge.

Values come out ready to publish: bool, int, float, str, or None for "unknown".
"""
from __future__ import annotations

from .signals import BY_FRAME, CAR_BUS, PRESENCE, WANTED, extract

KPH_PER_MPH = 1.609344
PRESENCE_TIMEOUT_S = 2.0  # the slowest message read for presence, 0x2FF / 0x344 / 0x80, runs at 20 Hz or faster
STALE_S = 3.0             # radar values (0x365 at 5 Hz, 0x411 at 1 Hz) count as unknown once the radar stops sending them

GEAR = {0: "D", 1: "S", 8: "N", 16: "R", 32: "P"}           # GEAR_PACKET (opendbc VAL_ 956 GEAR)
GEAR_HYBRID = {0: "P", 1: "R", 2: "N", 3: "D", 4: "B"}      # GEAR_PACKET_HYBRID (VAL_ 295 GEAR)
TURN_SIGNALS = {1: "left", 2: "right", 3: "off"}            # VAL_ 1556 TURN_SIGNALS
PCS_INDICATOR = {0: "on", 1: "off", 2: "faulted"}           # VAL_ 1041 PCS_INDICATOR; 1 also for ~3 s after a cold start (docs/13)
PCS_SENSITIVITY = {0: "off", 64: "high", 128: "mid", 192: "low"}
LEAD_IDLE_M = 0xFC                                          # 0x365 byte 4 with no ACC target (docs/13)

EVENTS = {  # event type: (signal, value that starts it)
    "forward_collision_warning": ("fcw", 1),
    "pcs_alarm": ("pcs_alarm", 1),
    "emergency_braking": ("aeb_state", 3),   # 0x283 STATE 3 (opendbc VAL_ 643 "emergency_braking")
}


class CarState:
    def __init__(self) -> None:
        self.raw: dict[str, float] = {}
        self.last_seen: dict[tuple[int, int], float] = {}
        self.frame_counts: dict[tuple[int, int], int] = {}
        self.events: list[str] = []
        self.awake_since: dict[int, float] = {}

    def feed(self, t: float, bus: int, addr: int, data: bytes) -> None:
        key = (bus, addr)
        if t - self.last_seen.get((bus, None), -1e9) > PRESENCE_TIMEOUT_S:
            self.awake_since[bus] = t
        self.last_seen[bus, None] = t  # any frame on this bus
        if key not in WANTED:
            return
        self.last_seen[key] = t
        self.frame_counts[key] = self.frame_counts.get(key, 0) + 1
        for name, sig in BY_FRAME.get(key, ()):
            value = extract(data, sig)
            if value is None:
                continue
            for event, (event_sig, start) in EVENTS.items():
                if event_sig == name and value == start and self.raw.get(name) != start:
                    self.events.append(event)
            self.raw[name] = value

    def pop_events(self) -> list[str]:
        out, self.events = self.events, []
        return out

    def _present(self, t: float, key: tuple[int, int], timeout: float = PRESENCE_TIMEOUT_S) -> bool | None:
        """True / False while the car bus is awake; None (unknown) while it sleeps and for its first seconds awake."""
        if (t - self.last_seen.get((CAR_BUS, None), -1e9) > PRESENCE_TIMEOUT_S
                or t - self.awake_since.get(CAR_BUS, t) < timeout):
            return None
        return t - self.last_seen.get(key, -1e9) <= timeout

    def values(self, t: float) -> dict[str, object]:
        r = self.raw
        v: dict[str, object] = {}

        def flag(name: str, src: str | None = None) -> None:
            if (src or name) in r:
                v[name] = bool(r[src or name])

        for door in ("fl", "fr", "rl", "rr"):
            flag(f"door_{door}")
        flag("seatbelt_driver_unlatched")
        flag("parking_brake")
        if "lock_status" in r:
            v["unlocked"] = r["lock_status"] == 1  # VAL_ 1592 LOCK_STATUS 0 "locked" 1 "unlocked"
        if "odometer" in r and r.get("odometer_units") in (1, 2):
            v["odometer_km"] = r["odometer"] * (KPH_PER_MPH if r["odometer_units"] == 2 else 1)
        if "gear_hybrid" in r:
            v["gear"] = GEAR_HYBRID.get(r["gear_hybrid"])
        elif "gear" in r:
            v["gear"] = GEAR.get(r["gear"])
        if "speed_kph" in r:
            v["speed_kph"] = round(r["speed_kph"], 1)
        if "turn_signals" in r:
            v["turn_signal"] = TURN_SIGNALS.get(r["turn_signals"])
        for name in ("hazard_light", "low_beam", "high_beam", "auto_high_beam", "cruise_active", "cruise_main_on",
                     "brake_hold_active", "engine_running"):
            flag(name)
        if "cruise_set_speed_kph" in r:
            v["cruise_set_speed_kph"] = r["cruise_set_speed_kph"] if r.get("cruise_main_on") else None
        for side in ("l", "r"):
            if f"bsm_{side}_adjacent" in r:
                v[f"blind_spot_{side}"] = bool(r[f"bsm_{side}_adjacent"] or r[f"bsm_{side}_approaching"])
        if "engine_rpm" in r:
            v["engine_rpm"] = round(r["engine_rpm"])

        # the radar (docs/13); with openpilot's radar disable (alpha long) the radar's car-bus messages stop
        if "lead_distance_m" in r:
            has_lead = r["lead_distance_m"] != LEAD_IDLE_M and self._present(t, (CAR_BUS, 0x365), STALE_S) is not False
            v["lead_distance_m"] = r["lead_distance_m"] if has_lead else None
            v["lead_rel_speed_kph"] = r["lead_rel_speed_kph"] if has_lead else None
        if "pcs_indicator" in r and self._present(t, (CAR_BUS, 0x411), STALE_S) is False:
            v.update(pcs_state=None, pcs_sensitivity=None, radar_blocked=None, radar_temperature=None, radar_beam_adjust=None)
        elif "pcs_indicator" in r:
            v["pcs_state"] = PCS_INDICATOR.get(r["pcs_indicator"])
            v["pcs_sensitivity"] = PCS_SENSITIVITY.get(r["pcs_sensitivity"])
            flag("radar_blocked")
            flag("radar_temperature")
            v["radar_beam_adjust"] = r["radar_beam_adjust"] != 0
        for name, key in PRESENCE.items():
            v[name] = self._present(t, key)
        return v
