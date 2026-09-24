"""Support messages that are partly understood. None of them is needed for the object decode.

0x192 (4 bytes, ~radar cycle) is a filtered target summary, most likely the target the radar itself selects
for ACC / pre-collision. It is NOT a better lead measurement: it is heavily smoothed and lags the 0x80 track
by 10-15 m during closings. Sentinel payload 00 FF 00 FF (no target).
  bytes 0-1 : big-endian distance, ~3/64 m per code (scale approximate, 13 bits used)
  byte 2    : lateral bin of that target (7/8 own lane, 6 and 9 adjacent lanes, 10-13 far left, 2-5 oncoming side)
  byte 3    : unknown
0x194 has the same shape (second target?), not characterised.
"""
from __future__ import annotations

from dataclasses import dataclass

A192_SENTINEL = bytes.fromhex("00FF00FF")
A192_DIST_SCALE_M = 3.0 / 64.0  # approximate


@dataclass(frozen=True)
class Target192:
    distance_m: float
    lateral_bin: int
    byte3: int


def parse_0x192(data: bytes) -> Target192 | None:
    if len(data) < 4 or bytes(data[:4]) == A192_SENTINEL:
        return None
    code = int.from_bytes(data[0:2], "big") & 0x1FFF
    return Target192(code * A192_DIST_SCALE_M, data[2], data[3])


def _be_field(data: bytes, start: int, length: int) -> int:
    """Bit field of an 8-byte frame read as one big-endian integer (bit 0 = LSB of the last byte)."""
    return (int.from_bytes(bytes(data[:8]).ljust(8, b"\x00"), "big") >> start) & ((1 << length) - 1)


def parse_acc_target_vrel(data: bytes) -> float | None:
    """0x235: closing speed of the radar's own ACC target, m/s (negative = closing).

    Bits 29..39, offset 1024, 0.1 m/s. Tested against the vision-matched radar lead on 20 routes: unbiased against
    vision (median 0.00 m/s). When native vRel and this value differ by > 3 m/s, vision agrees with this value in
    86-90% of cases (docs/15).
    """
    if len(data) < 8:
        return None
    return (_be_field(data, 29, 11) - 1024) * 0.1


def parse_acc_target_position(data: bytes) -> tuple[float, float] | None:
    """0x237: (coarse distance m, lateral m left positive) of the radar's ACC target.

    Lateral: bits 28..38, 1/60 m per code, offset -16.70 m (Pearson 0.97 against the matched lead). Distance is
    coarse: bits 47..51 at about 5.26 m per code, +9.6 m (about +-5 m).
    """
    if len(data) < 8:
        return None
    return _be_field(data, 47, 5) * 5.26 + 9.6, _be_field(data, 28, 11) * 0.01667 - 16.70


def parse_acc_target_range_code(data: bytes) -> int | None:
    """0x237 BE39|13 raw distance code, without an assumed absolute origin.

    Changes of about 0.02 m/code agree with integrated OEM 0x235 vRel on
    continuous-target windows. This is internal consistency, not independent
    range truth. Do not reuse the coarse decoder's +9.6 m offset. Callers must
    establish target availability and continuity before interpreting changes.
    The default radar interface does not consume this diagnostic field.
    """
    if len(data) < 8:
        return None
    return _be_field(data, 39, 13)
