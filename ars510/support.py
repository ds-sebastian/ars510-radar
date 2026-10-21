"""Support messages: the radar's ACC target (0x235 / 0x237 / 0x239 / 0x23B), the cycle header (0x190), the
selected-target summaries (0x191-0x194), the single-object stream (0x680), and car-bus target 0x366; docs/05 and 13.

0x192 / 0x194 (4 bytes, ~radar cycle) each carry the position of one target of the radar's internal tracker in the
object list's encoding: word 0 distance (code - 160) / 16 m, word 1 lateral (code - 2048) * LATERAL_M_PER_CODE m, left
positive. The whole-frame sentinel is 00 FF 00 FF. Use a parsed position together with the ACC target's availability
and association (docs/05).
"""
from __future__ import annotations

from dataclasses import dataclass

from .objects import LATERAL_M_PER_CODE

A192_SENTINEL = bytes.fromhex("00FF00FF")
A192_ALL_ONES = bytes.fromhex("FFFFFFFF")  # one-cycle glitch inside a live track (7 of ~760 k summary frames, two cars); caught by the top-bits check
# Summary distance: (code - 160) / 16 m. The same numbers as the object list's LONG_DIST, but established independently:
# the zero is pinned by the ACC target (summary code = 160 + floor(0.4 x ACC distance code), and the ACC distance has no
# offset), while the object list's zero comes from vision. Kept separate on purpose, so a future object-list correction
# does not move the summaries.
SUMMARY_RANGE_ZERO_CODE = 160
SUMMARY_RANGE_M_PER_CODE = 1 / 16
A680_IDLE = bytes.fromhex("000008008000800A")


@dataclass(frozen=True)
class Target192:
    range_code13: int
    field1_code13: int

    @property
    def d_rel(self) -> float:
        """Distance in m: (code - 160) / 16, the object list's encoding (see SUMMARY_RANGE_ZERO_CODE)."""
        return (self.range_code13 - SUMMARY_RANGE_ZERO_CODE) * SUMMARY_RANGE_M_PER_CODE

    @property
    def y_rel(self) -> float:
        """Lateral position in m, left positive: (code - 2048) * 0.015, the object list's encoding."""
        return (self.field1_code13 - 2048) * LATERAL_M_PER_CODE


def parse_0x192(data: bytes) -> Target192 | None:
    """Raw 13-bit summary words; Target192.d_rel / .y_rel give metres in the object list's encoding."""
    if len(data) < 4 or bytes(data[:4]) == A192_SENTINEL or (data[0] | data[2]) & 0xE0:  # the top 3 bits of each word are 0 unless corrupt
        return None
    return Target192(int.from_bytes(data[0:2], "big") & 0x1FFF,
                     int.from_bytes(data[2:4], "big") & 0x1FFF)


A191_SENTINEL = bytes.fromhex("FEFEFEFCFCFFFEFF")


class RadarFaultFlag:
    """0x196 byte 1 bit 0: the radar's own fault flag (docs/05).

    Set on every cycle while the radar declares itself blocked (car-bus 0x411 dust / 0x48 state; the object list keeps
    running), after some object-list outages, and on one cycle at power-up. MIN_CYCLES consecutive set cycles make it
    active, which skips the power-up frame; the first clear cycle clears it."""

    MIN_CYCLES = 2

    def __init__(self) -> None:
        self.run = 0

    def update(self, data: bytes) -> None:
        if len(data) >= 2:
            self.run = self.run + 1 if data[1] & 1 else 0

    @property
    def active(self) -> bool:
        return self.run >= self.MIN_CYCLES


def pcs_alarm(data: bytes) -> bool:
    """0x100 byte 0 bit 1: the radar's PCS alarm (FCW stage), set from the same CAN frame as the car-bus alarm in 8 alarms
    and never otherwise (docs/15). The first frame after power-up is FF FF, which is not an alarm."""
    return len(data) > 0 and data[0] != 0xFF and bool(data[0] & 0x02)


@dataclass(frozen=True)
class CycleHeader:
    active_summaries: int  # 0-2: how many of the 0x191/0x192 and 0x193/0x194 pairs carry a target (0x191 fills first)
    timestamp_us: int      # radar cycle clock, microseconds (32 bits)
    counter: int           # mod-16 counter, +3 per cycle


def parse_0x190(data: bytes) -> CycleHeader | None:
    """0x190 (7 bytes, once per radar cycle): summary count, microsecond timestamp, cycle counter (docs/05).

    Byte 0 = count << 2 | 2; the count equals the number of populated 0x191 / 0x193 frames in every logged cycle after start-up
    (681,864 of 681,879; the rest are startup frames).
    Returns None for a short frame or the all-ones start-up frame."""
    if len(data) < 7 or data[0] == 0xFF:
        return None
    return CycleHeader(data[0] >> 2, int.from_bytes(data[2:6], "big"), data[6] >> 4)


@dataclass(frozen=True)
class Target191:
    score: int       # 91-100 while a target is present
    age: int         # radar cycles, saturates at 126
    track_code: int  # pair-local target code 0-63
    width_m: float   # class template: 1.8 car, 2.2 truck
    height_m: float  # class template: 1.5 car, 2.3 truck
    length_m: float  # class template: 4.5 car, 12.0 truck
    quality: int     # counter that grows with age and saturates at 30


def parse_0x191(data: bytes) -> Target191 | None:
    """0x191 / 0x193 (8 bytes): companion of the 0x192 / 0x194 target summary, or None for the sentinel (docs/05).

    The three size fields are a class template in 0.1 m (18:15:45 for cars, 22:23:120 for trucks on 99.97 % of
    active frames, 607,999 of 608,186), the same class the ACC target reports on 0x239 when it is this target."""
    if len(data) != 8 or bytes(data) == A191_SENTINEL or data[0] >> 1 == 127:
        return None
    return Target191(data[0] >> 1, data[1] >> 1, data[3] >> 2, (data[4] >> 2) * 0.1, (data[6] >> 1) * 0.1, data[7] * 0.1,
                     data[5] >> 3)


@dataclass(frozen=True)
class Object680:
    selector: int        # byte 0: 0 / 1 mostly stationary objects, 3 mostly same-direction vehicles
    d_rel: float         # m, longitudinal distance, 1/32 m per code
    y_rel: float         # m, left positive, 0.015 m per code (the object list's lateral unit); 11 bits, so +-15.36 m: an object farther
                         # to the side most likely wraps to the opposite side, so |y| above about 13 m is ambiguous
    v_ground: float      # m/s over ground, nominal 0.15 m/s per code (0 for a stationary object)
    flags: int           # motion flags: bit 0 stationary, bit 1 oncoming, bit 3 seen moving; bits 2, 4, 5 raw
    lat_speed_code: int  # centred lateral speed over ground, about 0.13-0.18 m/s per code (0 on stationary objects)

    @property
    def stationary(self) -> bool:
        """Flag bit 0: set on 99.2 % of objects slower than 0.5 m/s over ground and on 0.7 % of moving ones."""
        return bool(self.flags & 0x01)

    @property
    def oncoming(self) -> bool:
        """Flag bit 1: set on 98.5 % of objects faster than 3 m/s toward ego and on 0.7 % of the others."""
        return bool(self.flags & 0x02)

    @property
    def seen_moving(self) -> bool:
        """Flag bit 3: a vehicle that moves or has moved (86 % of moving objects; with bit 0 a stopped vehicle)."""
        return bool(self.flags & 0x08)


def parse_0x680(data: bytes) -> Object680 | None:
    """0x680 (8 bytes, 2 Hz): one object from the radar's function-level tracker, or None when idle (docs/05).

    Mostly a stationary roadside object, which the 0x80 object list mostly drops while driving; sometimes a vehicle.
    Distance scale is fixed by stationary objects closing at ego speed; the speed unit agrees with the ACC target
    (0.09 m/s median absolute difference on shared targets). An analysis helper; the driving interface reads 0x235 / 0x237."""
    if len(data) != 8:
        return None
    rng, lat = _be_field(data, 43, 13), _be_field(data, 32, 11)
    if rng <= 1 and lat == 0:
        return None
    return Object680(data[0], rng / 32, (lat - 2048 if lat >= 1024 else lat) * LATERAL_M_PER_CODE,
                     (_be_field(data, 22, 10) - 512) * 0.15, _be_field(data, 16, 6), _be_field(data, 8, 8) - 128)


def _be_field(data: bytes, start: int, length: int) -> int:
    """Bit field of an 8-byte frame read as one big-endian integer (bit 0 = LSB of the last byte)."""
    return (int.from_bytes(bytes(data[:8]).ljust(8, b"\x00"), "big") >> start) & ((1 << length) - 1)


def parse_acc_target_vrel(data: bytes) -> float | None:
    """0x235: closing speed of the radar's ACC target, m/s (negative = closing).

    Bits 29..39, offset 1024, 0.125 m/s per code. The unit is fixed by stopped lead vehicles (true closing speed =
    ego speed) and by the slope of the target's own range code: speed / range rate = 0.99 on 1,862 windows (docs/05).
    """
    if len(data) < 8:
        return None
    return (_be_field(data, 29, 11) - 1024) * 0.125


def parse_acc_target_arel(data: bytes) -> float | None:
    """0x235 byte 2: relative acceleration of the radar's ACC target, m/s^2 (positive = opening).

    (byte 2 - 100) * 0.125; the idle payload's 0x64 decodes to 0. The unit follows from the frame's own closing
    speed: over 2 s windows the speed code changes by 1.00 times the integral of this code (0.997 on 222,050 windows,
    1.002 on other drives), so one code is one speed code (0.125 m/s) per second. Meaningful only while the target
    is active (docs/05).
    """
    if len(data) < 8:
        return None
    return (data[2] - 100) * 0.125


def parse_acc_target_position(data: bytes) -> tuple[float, float] | None:
    """0x237: (distance m, lateral m left positive) of the radar's ACC target, as the track association uses them.

    Distance: bits 39..51 (13 bits), code * 0.025 m (parse_acc_target_range_code returns the raw code).
    Lateral: bits 27..38 (12 bits), (code - 2000) * 0.01 m; one object-list lateral code is 1.5 of these codes (1.499-1.502).
    """
    if len(data) < 8:
        return None
    return _be_field(data, 39, 13) * 0.025, (_be_field(data, 27, 12) - 2000) * 0.01


def parse_acc_target_range_code(data: bytes) -> int | None:
    """0x237 BE39|13 distance code of the radar's ACC target: distance = 0.025 m x code, zero offset.

    Against the 0x680 object range the fit is 0.02500 m per code, +0.01 m, 0.02 m median residual (docs/05). Read it
    after checking target availability (0x235 state 5); `parse_acc_target` returns the full target.
    """
    if len(data) < 8:
        return None
    return _be_field(data, 39, 13)


@dataclass(frozen=True)
class AccTarget:
    target_id: int        # 0x235 bits 0-5 (6 bits; 32-63 on a C-HR radar): constant while the radar follows one target
    d_rel: float          # m, 0.025 m per code
    y_rel: float          # m, left positive, 12-bit (code - 2000) * 0.01
    v_rel: float          # m/s, negative = closing
    a_rel: float          # m/s^2, positive = opening
    v_lat: float          # m/s, left positive, about 0.0125 m/s per code
    a_lat: float          # m/s^2, relative lateral acceleration, (code - 100) * 0.125: mostly minus ego's own
    in_path: bool         # in-path confirmed (93.6 % of target frames)
    in_path_level: int    # 5 confirmed, then 4, 3, 2 as the target moves off the path
    tracker_codes: tuple[int, int]  # two raw tracker bytes that rise while the target accelerates or brakes


def parse_acc_target(data235: bytes, data237: bytes) -> AccTarget | None:
    """Every field of the radar's ACC target from one 0x235 / 0x237 pair, or None while the target is idle (docs/05).

    Field boundaries come from the carry structure of 2 M frames; while the target is idle every numeric field sits at its zero
    code. The driving interface keeps using the single-field helpers below."""
    if len(data235) != 8 or len(data237) != 8 or data235[1] & 0x0F != 5 or not _be_field(data237, 10, 1):
        return None
    d_rel, y_rel = parse_acc_target_position(data237)
    return AccTarget(target_id=_be_field(data235, 0, 6), d_rel=d_rel, y_rel=y_rel, v_rel=parse_acc_target_vrel(data235),
                     a_rel=parse_acc_target_arel(data235), v_lat=(_be_field(data235, 8, 11) - 1024) * 0.0125,
                     a_lat=(_be_field(data235, 19, 8) - 100) * 0.125, in_path=bool(_be_field(data237, 8, 1)),
                     in_path_level=_be_field(data237, 4, 3), tracker_codes=(_be_field(data237, 19, 8), _be_field(data237, 11, 8)))


@dataclass(frozen=True)
class AccTargetInfo:
    target_class: int     # 1 car, 2 truck (the 0x191 template class); 0, 4, 5, 6 other; 7 idle
    present: bool
    in_object_list: bool  # the target also has an object in the 0x80 list
    timestamp_us: int     # radar cycle clock of this target update, same clock as 0x190


def parse_0x239(data: bytes) -> AccTargetInfo | None:
    """0x239 (8 bytes, 50 Hz): class, object-list flag and cycle timestamp of the radar's ACC target (docs/05).

    The timestamp is 32 bits starting 3 bits into byte 3 and equals the 0x190 timestamp of the cycle the 0x235 / 0x237
    content belongs to. Returns None for a short frame or the all-ones start-up frame."""
    if len(data) != 8 or data[1] & 0x0F == 0x0F:
        return None
    return AccTargetInfo(data[1] & 0x0F, bool(data[3] & 0x08), bool(data[3] & 0x80), _be_field(data, 3, 32))


# ---------------------------------------------------------------- 0x235 / 0x237 / 0x239: check byte
# Byte 0 is a CRC-8 with polynomial 0x1D (MSB first, as in 0x23B) over the frame's signals serialized as zero-padded 8 /
# 16 / 32-bit integers, not over the raw bytes (docs/05). Being linear, it is stored as one column per payload bit
# (byte 1 bit 7 first ... byte 7 bit 0) plus a constant; bits that never varied on their own carry their CRC column from the
# serialized layout. LAT_SPEED (0x235) and LAT_DIST (0x237) are one bit wider inside
# the radar: when that bit is set the CAN field wraps and the check byte differs by the bit's CRC term (WRAP).
ACC_CHECK_235 = (0xDF, 0x9C, (
    0x68, 0x34, 0x1A, 0x0D, 0x18, 0xDC, 0xAF, 0xD9,
    0x6C, 0xE4, 0x3C, 0x1E, 0x0F, 0x89, 0xCA, 0x65,
    0x61, 0xBE, 0x5F, 0xA1, 0xDE, 0x6F, 0xB9, 0xD2,
    0x69, 0xBA, 0x5D, 0x8C, 0x46, 0x23, 0x9F, 0xC1,
    0xEE, 0x77, 0xB5, 0xD4, 0x6A, 0x4E, 0x27, 0x9D,
    0xC0, 0x60, 0x30, 0x18, 0x0C, 0x06, 0x03, 0x8F,
    0xCF, 0xE9, 0x75, 0xB4, 0x5A, 0x2D, 0x98, 0x4C))
ACC_CHECK_237 = (0xFE, 0x14, (
    0x0F, 0x89, 0xCA, 0x65, 0x99, 0xC2, 0x61, 0xBE,
    0x5F, 0xA1, 0xDE, 0x6F, 0xB9, 0xD2, 0x69, 0xBA,
    0x5D, 0x0A, 0x05, 0x8C, 0x46, 0x23, 0x9F, 0xC1,
    0xEE, 0x77, 0xB5, 0xD4, 0x6A, 0x35, 0x94, 0x4A,
    0x25, 0x9C, 0x4E, 0x27, 0x9D, 0xC0, 0x60, 0x30,
    0x18, 0x0C, 0x06, 0x03, 0x8F, 0x27, 0x2C, 0x2E,
    0xEF, 0xEF, 0x98, 0x98, 0x77, 0x1D, 0x3A, 0x74))
ACC_CHECK_239 = (0x02, None, (
    0xA3, 0xDF, 0xE1, 0xFE, 0x92, 0xD3, 0xE7, 0xFD,
    0x38, 0xB9, 0x65, 0x5C, 0x6A, 0xD4, 0xB5, 0x77,
    0xB9, 0xB9, 0xEE, 0xC1, 0x9F, 0x35, 0x94, 0x4A,
    0x25, 0x9C, 0x4E, 0x27, 0x9D, 0xC0, 0x60, 0x30,
    0x18, 0x0C, 0x06, 0x03, 0x8F, 0xC9, 0xEA, 0x75,
    0xB4, 0x5A, 0x2D, 0x98, 0x4C, 0x26, 0x13, 0x87,
    0xCD, 0xE8, 0x74, 0x3A, 0x1D, 0x23, 0x46, 0x8C))
ACC_CHECK = {0x235: ACC_CHECK_235, 0x237: ACC_CHECK_237, 0x239: ACC_CHECK_239}


def acc_check(address: int, data: bytes) -> str | None:
    """Check byte of an ACC target frame (0x235 / 0x237 / 0x239): "ok", "wrapped" (valid, and LAT_SPEED / LAT_DIST
    wrapped: add 2048 / 4096 codes), "bad", or None for another address or length. 0 failures on 2.9 M frames of two cars."""
    if address not in ACC_CHECK or len(data) != 8:
        return None
    const, wrap, cols = ACC_CHECK[address]
    r, bits = const ^ data[0], int.from_bytes(data[1:], "big")
    for i, col in enumerate(cols):
        if bits >> (55 - i) & 1:
            r ^= col
    return "ok" if r == 0 else "wrapped" if r == wrap else "bad"


# ---------------------------------------------------------------- 0x23B: target width, counter, CRC-8
A23B_CRC_XOROUT = 0x59


def crc8_0x1d_bits(bits) -> int:
    """CRC-8, polynomial 0x1D (x^8+x^4+x^3+x^2+1), MSB first, init 0, direct bit order in and out, over an iterable of bits."""
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
    """0x23B (3 bytes, 50 Hz), in frame order as received: (ACC target width in cm, rolling counter 0-15, check byte valid).

    Byte 0 = CRC-8, byte 1 = counter << 4 | width high nibble, byte 2 = width low byte. The width is 0 exactly while
    the target is idle, 140-220 for the car class (median 171) and 200-280 for the truck class (docs/05). The startup
    frame 00 0f ff is the one frame with a mismatching check byte; every other frame carries a valid one."""
    if len(data) != 3:
        return None
    return (data[1] & 0x0F) << 8 | data[2], data[1] >> 4, crc_0x23b(data[2], data[1]) == data[0]


@dataclass(frozen=True)
class Target366:
    """Car-bus target report: matches ACC in some regimes and also reports other states (docs/13)."""
    speed_code: int
    distance_code: int
    header_raw: int
    tail_raw: int
    lateral_code: int = 15  # signed five bits at MSB-first 40|5; 15 is the no-target value

    @property
    def y_rel(self) -> float | None:
        """Lateral offset in metres, left positive, -0.34 m per code; None for 15 (idle) and -16 (invalid, mostly beyond +-5 m)."""
        return None if self.lateral_code in (15, -16) else -0.34 * self.lateral_code

    @property
    def v_rel(self) -> float | None:
        """Relative speed: the 9 bits are signed (codes from 256 are code - 512), 0.5 km/h per code, zero 155 (docs/13)."""
        return ((self.speed_code - 512 if self.speed_code >= 256 else self.speed_code) - 155) * 5 / 36

    @property
    def d_rel(self) -> float:
        """Approximate range in metres at the fitted 0.8 m per code (fit 0.79, docs/13)."""
        return self.distance_code * .8

    @property
    def target_id(self) -> int:
        """Byte 4 bits 7-3: the ACC target's TARGET_ID (equal on 98 % of reports; the rest are publication timing)."""
        return self.tail_raw >> 19 & 31

    @property
    def pcs_alarm(self) -> bool:
        """Byte 1 bit 2: set only during the radar's PCS alarm (one recorded event, docs/15)."""
        return bool(self.header_raw & 0x0004)


def parse_0x366(data: bytes) -> Target366 | None:
    """Decode a seven-byte car-bus report, or None for the 7FFF idle word.

    0x366 arrives about 90 ms after 0x365. It agrees with the ACC target in matched mature-target comparisons and
    also reports while the ACC target is idle (docs/13). An analysis helper; the profiles read the ACC target frames.
    """
    if len(data) != 7 or data[2:4] == b"\x7f\xff":
        return None
    lateral = data[5] >> 3
    return Target366(data[2] * 2 + (data[3] >> 7), data[3] & 127,
                     int.from_bytes(data[:2], "big"), int.from_bytes(data[4:], "big"), lateral - 32 if lateral >= 16 else lateral)
