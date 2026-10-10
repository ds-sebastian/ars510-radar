"""Toyota / Continental ARS510 front radar: CAN decode for openpilot experiments.

Status: transport, geometry, track IDs and the ACC target are decoded; the default `fused`
profile filters the object list's far-range speed excursions. Field confidence: README.md and docs/03.
"""
from .constants import ID80_ADDR, ID85_ADDR, RADAR_BUS, TOYOTA_SPEED_ADDR
from .interface import (
    COLORED_CONFIG,
    FUSED_CONFIG,
    BASE_CONFIG,
    ALL_TRACKS_CONFIG,
    Ars510NativeRadarInterface,
    NativeInterfaceConfig,
    parse_toyota_speed_mps,
)
from .objects import NativeObject, decode_native_slot
from .record import id80_crc_ok, occupied_slots
from .transport import Id80RecordAssembler, Id85RecordAssembler

__all__ = [
    "ID80_ADDR", "ID85_ADDR", "RADAR_BUS", "TOYOTA_SPEED_ADDR",
    "COLORED_CONFIG", "FUSED_CONFIG", "BASE_CONFIG", "ALL_TRACKS_CONFIG", "Ars510NativeRadarInterface", "NativeInterfaceConfig",
    "parse_toyota_speed_mps", "NativeObject", "decode_native_slot", "id80_crc_ok", "occupied_slots",
    "Id80RecordAssembler", "Id85RecordAssembler",
]
