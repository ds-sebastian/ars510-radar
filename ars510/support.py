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
A680_IDLE = bytes.fromhex("000008008000800A")


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


@dataclass(frozen=True)
class Object680:
    selector: int        # byte 0: 0 / 1 mostly stationary objects, 3 mostly same-direction vehicles
    d_rel: float         # m, longitudinal distance, 1/32 m per code
    y_rel: float         # m, left positive, 1/64 m per code
    v_ground: float      # m/s over ground, nominal 0.15 m/s per code (0 for a stationary object)
    flags: int           # 6-bit raw flags (8 on vehicles, 1 / 9 / 49 on stationary objects)
    lat_speed_code: int  # centred raw code that follows the lateral-position slope


def parse_0x680(data: bytes) -> Object680 | None:
    """0x680 (8 bytes, 2 Hz): one object from the radar's function-level tracker, or None when idle (docs/05).

    Mostly a stationary roadside object, which the 0x80 object list does not carry while driving; sometimes a vehicle.
    Distance scale is fixed by stationary objects closing at ego speed; the speed unit agrees with the ACC target
    (0.2 m/s median absolute difference on shared targets). The driving interface does not use this helper."""
    if len(data) != 8:
        return None
    rng, lat = _be_field(data, 43, 13), _be_field(data, 32, 11)
    if rng <= 1 and lat == 0:
        return None
    return Object680(data[0], rng / 32, (lat - 2048 if lat >= 1024 else lat) / 64, (_be_field(data, 22, 10) - 512) * 0.15,
                     _be_field(data, 16, 6), _be_field(data, 8, 8) - 128)


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


# ---------------------------------------------------------------- 0x23B: slow value, counter, CRC-8
A23B_CRC_XOROUT = 0x59


def crc8_0x1d_bits(bits) -> int:
    """CRC-8, polynomial 0x1D (x^8+x^4+x^3+x^2+1), MSB first, init 0, no reflection, over an iterable of bits."""
    crc = 0
    for bit in bits:
        crc = ((crc << 1) & 0xFF) ^ ((((crc >> 7) & 1) ^ bit) * 0x1D)
    return crc


def crc_0x23b(value: int, counter_and_low: int) -> int:
    """Check byte of 0x23B: CRC-8/0x1D over [counter 4 bits][0000][low nibble of byte 1][value byte 2 8 bits], xor 0x59."""
    bits = [(counter_and_low >> (7 - i)) & 1 for i in range(4)] + [0] * 4 + [(counter_and_low >> (3 - i)) & 1 for i in range(4)] \
        + [(value >> (7 - i)) & 1 for i in range(8)]
    return crc8_0x1d_bits(bits) ^ A23B_CRC_XOROUT


def parse_0x23b(data: bytes) -> tuple[int, int, bool] | None:
    """0x23B (3 bytes, 50 Hz), in frame order as received: (slow 8-bit value, rolling counter 0-15, check byte valid).

    Byte 0 = CRC-8, byte 1 = counter << 4 | low nibble (0 except 1 / 15 on 74 of 2 M frames), byte 2 = slow value (about
    171 +- 6 when nonzero, unreferenced; docs/05). The startup frame 00 0f ff fails the check; every other frame passes."""
    if len(data) != 3:
        return None
    return data[2], data[1] >> 4, crc_0x23b(data[2], data[1]) == data[0]
