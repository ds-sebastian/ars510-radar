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
