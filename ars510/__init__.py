"""Toyota / Continental ARS510 front radar: CAN decode for openpilot experiments.

Status: native geometry and slot lifecycle have supporting evidence; exact vRel
and state semantics remain unresolved. Not validated for active control.
See README.md.
"""
from .constants import ID80_ADDR, ID85_ADDR, RADAR_BUS, TOYOTA_SPEED_ADDR
from .interface import (
    OPENPILOT_CONFIG,
    RAW_CONFIG,
    STEADY_CONFIG,
    Ars510NativeRadarInterface,
    NativeInterfaceConfig,
    parse_toyota_speed_mps,
)
from .objects import NativeObject, decode_native_slot
from .record import id80_crc_ok, occupied_slots
from .transport import Id80RecordAssembler, Id85RecordAssembler

__all__ = [
    "ID80_ADDR", "ID85_ADDR", "RADAR_BUS", "TOYOTA_SPEED_ADDR",
    "OPENPILOT_CONFIG", "RAW_CONFIG", "STEADY_CONFIG", "Ars510NativeRadarInterface", "NativeInterfaceConfig",
    "parse_toyota_speed_mps", "NativeObject", "decode_native_slot", "id80_crc_ok", "occupied_slots",
    "Id80RecordAssembler", "Id85RecordAssembler",
]
