"""The CAN signals the Home Assistant bridge reads, with DBC-style bit extraction.

Car signals are copied from opendbc's Toyota DBCs (generator/toyota/_toyota_2017.dbc, toyota_nodsu_pt.dbc,
_community.dbc): start bit, length, byte order, sign, scale and offset exactly as there. The radar's car-bus
messages (0x283, 0x344, 0x365, 0x411) follow the same DBCs, read with what docs/13 established on this radar.
`status` is "●" when openpilot itself reads the message on the RAV4 TSS2 2023 or docs/13 decodes it on this car,
"◐" when opendbc defines it but nothing in this repo has seen it on this car's bus yet.
"""
from __future__ import annotations

from dataclasses import dataclass

CAR_BUS = 0
RADAR_BUS = 1


@dataclass(frozen=True)
class Signal:
    message: str
    addr: int
    start: int          # DBC start bit: the MSB for big-endian (@0), the LSB for little-endian (@1)
    length: int
    big_endian: bool = True
    signed: bool = False
    scale: float = 1.0
    offset: float = 0.0
    bus: int = CAR_BUS
    status: str = "●"


def extract(data: bytes, sig: Signal) -> float | None:
    """The signal's physical value from one frame, or None when the frame is too short."""
    nbits = len(data) * 8
    if sig.big_endian:
        msb = (sig.start // 8) * 8 + (7 - sig.start % 8)  # bit index counted from the first payload bit, MSB-first
        if msb + sig.length > nbits:
            return None
        raw = (int.from_bytes(data, "big") >> (nbits - msb - sig.length)) & ((1 << sig.length) - 1)
    else:
        if sig.start + sig.length > nbits:
            return None
        raw = (int.from_bytes(data, "little") >> sig.start) & ((1 << sig.length) - 1)
    if sig.signed and raw >> (sig.length - 1):
        raw -= 1 << sig.length
    return raw if sig.scale == 1 and sig.offset == 0 else raw * sig.scale + sig.offset


def _sigs(message: str, addr: int, status: str = "●", **fields: tuple) -> dict[str, Signal]:
    out = {}
    for name, spec in fields.items():
        start, length, *rest = spec
        kw = rest[0] if rest else {}
        out[name] = Signal(message, addr, start, length, status=status, **kw)
    return out


S = {
    # body (opendbc carstate reads BODY_CONTROL_STATE, BLINKERS_STATE, LIGHT_STALK, PCM_CRUISE*, GEAR_PACKET*, ESP_CONTROL)
    **_sigs("BODY_CONTROL_STATE", 0x620, door_fl=(45, 1), door_fr=(44, 1), door_rl=(42, 1), door_rr=(43, 1),
            seatbelt_driver_unlatched=(62, 1), parking_brake=(60, 1)),
    **_sigs("UI_SETTING", 0x611, "◐", odometer=(39, 32), odometer_units=(26, 2)),
    **_sigs("DOOR_LOCKS", 0x638, "◐", lock_status=(20, 1)),
    **_sigs("GEAR_PACKET", 0x3BC, gear=(13, 6)),
    **_sigs("GEAR_PACKET_HYBRID", 0x127, gear_hybrid=(47, 4)),
    **_sigs("SPEED", 0xB4, speed_kph=(47, 16, {"scale": 0.01})),
    **_sigs("BLINKERS_STATE", 0x614, turn_signals=(29, 2)),
    **_sigs("BLINKERS_STATE", 0x614, "◐", hazard_light=(27, 1)),
    **_sigs("LIGHT_STALK", 0x622, auto_high_beam=(37, 1)),
    **_sigs("LIGHT_STALK", 0x622, "◐", low_beam=(29, 1), high_beam=(30, 1)),
    **_sigs("PCM_CRUISE", 0x1D2, cruise_active=(5, 1)),
    **_sigs("PCM_CRUISE_2", 0x1D3, cruise_main_on=(15, 1), cruise_set_speed_kph=(23, 8)),
    **_sigs("ESP_CONTROL", 0x3B7, brake_hold_active=(36, 1)),
    **_sigs("BSM", 0x3F6, "◐", bsm_l_adjacent=(0, 1), bsm_l_approaching=(8, 1), bsm_r_adjacent=(1, 1),
            bsm_r_approaching=(10, 1)),
    **_sigs("ENGINE_RPM", 0x1C4, "◐", engine_rpm=(7, 16, {"signed": True, "scale": 0.78125}), engine_running=(27, 1)),
    # the radar's car-bus messages (docs/13)
    **_sigs("DSU_CRUISE", 0x365, lead_distance_m=(39, 8), lead_rel_speed_kph=(47, 8, {"signed": True})),
    **_sigs("PRE_COLLISION_2", 0x344, pcs_alarm=(17, 1)),
    **_sigs("PRE_COLLISION", 0x283, "◐", aeb_state=(36, 3)),
    **_sigs("PCS_HUD", 0x411, pcs_indicator=(7, 2), fcw=(4, 1), pcs_sensitivity=(55, 8)),
    **_sigs("PCS_HUD", 0x411, "◐", radar_blocked=(41, 1), radar_temperature=(42, 1), radar_beam_adjust=(53, 3)),
}

# Messages read only for their presence: the radar's PCS / AEB request (0x344), a radar CAN filter's heartbeat (SDSU,
# 0x2FF) and the radar's object list on the radar bus (0x80).
PRESENCE = {
    "pcs_braking_available": (CAR_BUS, 0x344),  # the radar's PCS / AEB request reaches the car: AEB in place (docs/13, 15)
    "radar_filter": (CAR_BUS, 0x2FF),
    "radar_object_list": (RADAR_BUS, 0x80),
}

BY_FRAME: dict[tuple[int, int], list[tuple[str, Signal]]] = {}
for _name, _sig in S.items():
    BY_FRAME.setdefault((_sig.bus, _sig.addr), []).append((_name, _sig))
WANTED = set(BY_FRAME) | set(PRESENCE.values())
