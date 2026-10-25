"""Home Assistant entities and their MQTT discovery payloads (https://www.home-assistant.io/integrations/mqtt/).

Data entities carry no availability topic, so Home Assistant keeps their last retained value while the car is
parked and the comma device is off; the "Comma device" connectivity sensor shows whether the values are live.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    component: str           # binary_sensor, sensor, event, device_tracker
    name: str
    config: dict = field(default_factory=dict)
    min_interval_s: float = 0.0  # at most one state per interval for values that change while driving
    diagnostic: bool = False


def _bin(name, device_class=None, icon=None, **kw):
    config = {k: v for k, v in (("device_class", device_class), ("icon", icon)) if v}
    return Entity("binary_sensor", name, config, **kw)


def _num(name, unit, device_class=None, precision=None, state_class="measurement", icon=None, **kw):
    config = {"unit_of_measurement": unit, "state_class": state_class}
    config.update({k: v for k, v in (("device_class", device_class), ("suggested_display_precision", precision),
                                     ("icon", icon)) if v is not None})
    return Entity("sensor", name, config, **kw)


def _enum(name, options, icon=None, **kw):
    config = {"device_class": "enum", "options": options}
    if icon:
        config["icon"] = icon
    return Entity("sensor", name, config, **kw)


ENTITIES: dict[str, Entity] = {
    # body
    "door_fl": _bin("Front left door", "door"),
    "door_fr": _bin("Front right door", "door"),
    "door_rl": _bin("Rear left door", "door"),
    "door_rr": _bin("Rear right door", "door"),
    "unlocked": _bin("Door lock", "lock"),  # on = unlocked, as Home Assistant's lock device class expects
    "seatbelt_driver_unlatched": _bin("Driver seatbelt unlatched", icon="mdi:seatbelt"),
    "parking_brake": _bin("Parking brake", icon="mdi:car-brake-parking"),
    "hazard_light": _bin("Hazard lights", icon="mdi:hazard-lights"),
    "low_beam": _bin("Low beams", "light", "mdi:car-light-dimmed"),
    "high_beam": _bin("High beams", "light", "mdi:car-light-high"),
    "auto_high_beam": _bin("Automatic high beams", icon="mdi:car-light-high", diagnostic=True),
    "turn_signal": _enum("Turn signal", ["off", "left", "right"], "mdi:arrow-left-right"),
    "gear": _enum("Gear", ["P", "R", "N", "D", "B", "S"], "mdi:car-shift-pattern"),
    "speed_kph": _num("Speed", "km/h", "speed", 0, min_interval_s=5),
    "odometer_km": _num("Odometer", "km", "distance", 0, "total_increasing", min_interval_s=60),
    "engine_running": _bin("Engine running", "running", "mdi:engine"),
    "engine_rpm": _num("Engine speed", "rpm", None, 0, icon="mdi:engine", min_interval_s=5),
    "brake_hold_active": _bin("Brake hold", icon="mdi:car-brake-hold"),
    "cruise_main_on": _bin("Cruise control", icon="mdi:speedometer"),
    "cruise_active": _bin("Cruise engaged", "running", "mdi:speedometer"),
    "cruise_set_speed_kph": _num("Cruise set speed", "km/h", "speed", 0),
    "blind_spot_l": _bin("Blind spot left", "occupancy", "mdi:car-side"),
    "blind_spot_r": _bin("Blind spot right", "occupancy", "mdi:car-side"),
    # radar (docs/13, docs/15)
    "lead_distance_m": _num("Lead distance", "m", "distance", 0, min_interval_s=2),
    "lead_rel_speed_kph": _num("Lead relative speed", "km/h", "speed", 0, min_interval_s=2),
    "pcs_state": _enum("Pre-collision system", ["on", "off", "faulted"], "mdi:car-brake-alert"),
    "pcs_sensitivity": _enum("Pre-collision sensitivity", ["off", "high", "mid", "low"], "mdi:car-brake-alert",
                             diagnostic=True),
    "pcs_braking_available": _bin("Pre-collision braking", icon="mdi:car-brake-alert"),
    "radar_blocked": _bin("Radar blocked", "problem", "mdi:radar"),
    "radar_temperature": _bin("Radar temperature alert", "problem", "mdi:radar", diagnostic=True),
    "radar_beam_adjust": _bin("Radar beam alignment alert", "problem", "mdi:radar", diagnostic=True),
    "radar_filter": _bin("Radar CAN filter", "connectivity", diagnostic=True),
    "radar_object_list": _bin("Radar object list", "connectivity", diagnostic=True),
    "safety_event": Entity("event", "Safety event", {"event_types": ["forward_collision_warning", "pcs_alarm",
                                                                    "emergency_braking"], "icon": "mdi:car-emergency"}),
    # openpilot and the comma device
    "ignition": _bin("Ignition", "power", "mdi:key"),
    "engaged": _bin("openpilot engaged", "running", "mdi:steering"),
    "battery_voltage": _num("12 V battery", "V", "voltage", 2, min_interval_s=30),
    "device_temp": _num("Comma device temperature", "°C", "temperature", 0, min_interval_s=60, diagnostic=True),
    "free_space": _num("Comma device free space", "%", None, 0, icon="mdi:harddisk", min_interval_s=300, diagnostic=True),
    "location": Entity("device_tracker", "Location", {"source_type": "gps"}, min_interval_s=10),
    "online": _bin("Comma device", "connectivity", diagnostic=True),
}


def discovery(key: str, node_id: str, base_topic: str, device: dict) -> tuple[str, dict]:
    """(config topic suffix, config payload) for one entity."""
    ent = ENTITIES[key]
    payload = {"name": ent.name, "unique_id": f"{node_id}_{key}", "device": device, **ent.config}
    if ent.diagnostic:
        payload["entity_category"] = "diagnostic"
    if ent.component == "device_tracker":
        payload["json_attributes_topic"] = f"{base_topic}/{key}"
    elif key == "online":
        payload.update(state_topic=f"{base_topic}/status", payload_on="online", payload_off="offline")
    else:
        payload["state_topic"] = f"{base_topic}/{key}"
    return f"{ent.component}/{node_id}/{key}/config", payload


def state_payload(key: str, value: object) -> str:
    if ENTITIES[key].component in ("device_tracker", "event"):
        return json.dumps(value)
    if value is None:
        return "None"  # Home Assistant's MQTT sensors read "None" as unknown
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)
