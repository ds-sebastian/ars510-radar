"""Support messages: the OEM ACC target witness (0x235 / 0x237) and the selected-target summaries (docs/05).

0x192 / 0x194 (4 bytes, ~radar cycle) each carry two raw 13-bit summaries.
Word 0 is range-like; physical scale and origin require independent calibration.
Preserve all of word 1, including bit 12, before physical interpretation.
The whole-frame sentinel is 00 FF 00 FF. Parsing a non-sentinel does not certify
target availability or association. The driving interface does not use this helper.
"""
from __future__ import annotations

from dataclasses import dataclass

A192_SENTINEL = bytes.fromhex("00FF00FF")


@dataclass(frozen=True)
class Target192:
    range_code13: int
    field1_code13: int


def parse_0x192(data: bytes) -> Target192 | None:
    """Decode raw summary words without assuming metric units or lane categories."""
    if len(data) < 4 or bytes(data[:4]) == A192_SENTINEL:
        return None
    return Target192(int.from_bytes(data[0:2], "big") & 0x1FFF,
                     int.from_bytes(data[2:4], "big") & 0x1FFF)


def _be_field(data: bytes, start: int, length: int) -> int:
    """Bit field of an 8-byte frame read as one big-endian integer (bit 0 = LSB of the last byte)."""
    return (int.from_bytes(bytes(data[:8]).ljust(8, b"\x00"), "big") >> start) & ((1 << length) - 1)


def parse_acc_target_vrel(data: bytes) -> float | None:
    """0x235: nominal closing speed of the OEM ACC target witness, m/s (negative = closing).

    Bits 29..39, offset 1024, nominal 0.1 m/s per code; physical units are not independently calibrated.
    On 20 routes the median difference against the vision-matched lead is 0.00 m/s under this convention.
    When native vRel and this value differ by > 3 m/s, vision agrees with this value in 86-90% of cases (docs/05).
    """
    if len(data) < 8:
        return None
    return (_be_field(data, 29, 11) - 1024) * 0.1


def parse_acc_target_arel(data: bytes) -> float | None:
    """0x235 byte 2: nominal relative acceleration of the OEM ACC target witness, m/s^2 (positive = opening).

    (byte 2 - 100) * 0.1; the idle payload's 0x64 decodes to 0. Binned against the derivative of the 0x235 closing
    speed it gives identical curves on discovery, confirmation and fresh drives, lagging that derivative by
    0.1-0.2 s. The approximate scale (0.1-0.14 m/s^2 per code) is conditional on the assumed velocity scale,
    not an independent physical calibration. Meaningful only while the target is active (docs/05).
    """
    if len(data) < 8:
        return None
    return (data[2] - 100) * 0.1


def parse_acc_target_position(data: bytes) -> tuple[float, float] | None:
    """0x237: nominal (coarse distance m, lateral m left positive) of the OEM ACC target witness.

    Lateral: bits 28..38, 1/60 m per code, offset -16.70 m (Pearson 0.97 against the matched lead). Distance is
    coarse: bits 47..51 at about 5.26 m per code, +9.6 m (about +-5 m). These empirical conversions are
    reference-dependent, not independently calibrated physical units or origins.
    """
    if len(data) < 8:
        return None
    return _be_field(data, 47, 5) * 5.26 + 9.6, _be_field(data, 28, 11) * 0.01667 - 16.70


def parse_acc_target_range_code(data: bytes) -> int | None:
    """0x237 BE39|13 raw distance code, without an assumed absolute origin.

    Nominal changes of about 0.02 m/code agree with integrated OEM 0x235 vRel
    assuming 0.1 m/s per velocity code on continuous-target windows. Jointly
    rescaling both preserves this closure; it does not calibrate physical units.
    Do not reuse the coarse decoder's +9.6 m offset. Callers must
    establish target availability and continuity before interpreting changes.
    The default radar interface does not consume this diagnostic field.
    """
    if len(data) < 8:
        return None
    return _be_field(data, 39, 13)
