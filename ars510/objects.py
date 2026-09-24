"""Native decode of one 36-byte 0x80 object slot.

Each slot is read as ONE little-endian bit field: bit 0 is the LSB of slot byte 0, bit 8 the LSB of byte 1,
and so on. `start|length` below uses that numbering (it is also DBC `@1+` Intel numbering on the slot bytes).

Field boundaries come from carry chains between consecutive cycles of the same slot (a higher bit almost
never flips unless the bit below it flips). Scales and zero points come from vehicle physics (wheel speed,
standstill, stationary objects) and were then checked against model-free camera geometry on held-out drives.
See docs/02_object_record_0x80.md for the evidence and its limits.

Output convention matches openpilot's RadarPoint: dRel forward (m), yRel LEFT positive (m).
"""
from __future__ import annotations

from dataclasses import dataclass

SLOT_BYTES = 36


@dataclass(frozen=True)
class NativeField:
    name: str
    bit_start: int
    bit_len: int
    zero_code: float
    scale: float
    unit: str
    status: str  # how well the field is established; see docs


# Longitudinal distance, forward. 12-bit unsigned, 1/16 m, zero code 160 (= -10.000 m exactly).
LONG_DIST = NativeField("long_dist", 32, 12, 160.0, 1.0 / 16.0, "m", "validated")
# Lateral distance, LEFT positive. 12-bit offset binary around 2048, 1/64 m (scale bounded to about +/-10%).
LAT_DIST = NativeField("lat_dist_left", 44, 12, 2048.0, 1.0 / 64.0, "m", "validated_sign_scale_pm10pct")
# Longitudinal velocity OVER GROUND (not relative). 10-bit, 0.15 m/s per code, zero 510.5.
# vRel = this - ego speed.
LONG_VEL_GROUND = NativeField("long_vel_over_ground", 64, 10, 510.5, 0.15, "m/s", "validated_with_caveats")
# Lateral velocity over ground, left positive (sign confirmed). Scale NOT pinned: radar-only estimates (own lateral
# position change in straight driving) range 0.097-0.147 m/s per code across data sets, and the pre-registered test
# was unverified (docs/14). 0.15 is kept as a placeholder; openpilot does not use this field (yvRel stays NaN).
LAT_VEL = NativeField("lat_vel_over_ground", 74, 10, 510.5, 0.15, "m/s", "scale_not_pinned")
# Acceleration-like, zero code 511 at standstill; follows the velocity change with a ~0.5 s lag. Radar-only scale about
# 0.04 m/s^2 per code on most data, but drive-dependent (0.03-0.11), so it stays in centred codes (docs/14).
ACCEL_LIKE = NativeField("accel_like_84", 84, 10, 511.0, 1.0, "code", "unnamed")
# Track age in radar cycles (~60 ms): 1 at birth, saturates at 126, 0 = slot being retired.
AGE = NativeField("age_cycles", 24, 7, 0.0, 1.0, "cycles", "structure")
# Movement state (passed a pre-registered test on unseen data, docs/14): 0 = moving away / same direction,
# 2 = moving toward (oncoming), 1 and 3 = not clearly moving (the difference between 1 and 3 is unresolved).
MOVE_STATE = NativeField("move_state", 109, 2, 0.0, 1.0, "enum", "tested_semantics")
# Oncoming flag (passed a pre-registered test): 1 = oncoming now or earlier in the track's life (it persists after
# an oncoming object slows or stops).
ONCOMING_FLAG = NativeField("oncoming_flag", 14, 1, 0.0, 1.0, "flag", "tested_semantics")

# Candidate velocity-uncertainty code (unnamed; behaves like an rms field). Among settled tracks it is higher when the
# native velocity disagrees with the camera's by > 2 m/s, also within 5 m range bands at fixed age (stratified AUC
# about 0.62 on drives A-C). Unit and meaning are unpinned: use it only as a relative confidence signal (docs/14).
VEL_UNC_240 = NativeField("vel_uncertainty_candidate", 240, 7, 0.0, 1.0, "code", "candidate")

MOVE_STATE_NAMES = {0: "moving_away", 1: "not_clearly_moving", 2: "moving_toward", 3: "not_clearly_moving_3"}

AGE_SATURATION = 126
# |lateral code - 2048| >= this is a sentinel, not a position.
LAT_INVALID_ABS_CODE = 2000

NAMED_FIELDS = (AGE, LONG_DIST, LAT_DIST, LONG_VEL_GROUND, LAT_VEL, ACCEL_LIKE, MOVE_STATE, ONCOMING_FLAG, VEL_UNC_240)


def slot_bits(slot: bytes, start: int, length: int) -> int:
    return (int.from_bytes(slot, "little") >> start) & ((1 << length) - 1)


def field_code(slot: bytes, field: NativeField) -> int:
    return slot_bits(slot, field.bit_start, field.bit_len)


def field_value(slot: bytes, field: NativeField) -> float:
    return (field_code(slot, field) - field.zero_code) * field.scale


def encode_slot(**codes: int) -> bytes:
    """Build a synthetic slot from raw codes, e.g. encode_slot(long_dist=640, age=40). Unset bits are 0."""
    by_name = {f.name: f for f in NAMED_FIELDS}
    value = 0
    for name, code in codes.items():
        f = by_name[name]
        value |= (int(code) & ((1 << f.bit_len) - 1)) << f.bit_start
    return value.to_bytes(SLOT_BYTES, "little")


@dataclass(frozen=True)
class NativeObject:
    slot: int
    age: int
    d_rel: float  # m, forward of the radar
    y_rel: float  # m, left positive
    v_long_ground: float  # m/s over ground (NOT relative)
    v_lat_ground: float  # m/s, provisional
    accel_like_code: int  # centred code, unscaled
    move_state: int  # 0 moving away, 2 moving toward, 1/3 not clearly moving (MOVE_STATE_NAMES)
    oncoming_flag: bool  # oncoming now or earlier in the track's life
    vel_unc_code: int  # candidate velocity-uncertainty code (240|7), relative confidence only
    geometry_valid: bool  # age >= 1 (age 0 carries the previous occupant's stale geometry)
    lateral_valid: bool  # lateral code is not the sentinel


def decode_native_slot(slot_index: int, slot: bytes) -> NativeObject:
    if len(slot) != SLOT_BYTES:
        raise ValueError(f"0x80 slot must be {SLOT_BYTES} bytes, got {len(slot)}")
    age = field_code(slot, AGE)
    lat_code = field_code(slot, LAT_DIST) - LAT_DIST.zero_code
    return NativeObject(
        slot=int(slot_index),
        age=int(age),
        d_rel=field_value(slot, LONG_DIST),
        y_rel=lat_code * LAT_DIST.scale,
        v_long_ground=field_value(slot, LONG_VEL_GROUND),
        v_lat_ground=field_value(slot, LAT_VEL),
        accel_like_code=int(field_code(slot, ACCEL_LIKE) - ACCEL_LIKE.zero_code),
        move_state=int(field_code(slot, MOVE_STATE)),
        oncoming_flag=bool(field_code(slot, ONCOMING_FLAG)),
        vel_unc_code=int(field_code(slot, VEL_UNC_240)),
        geometry_valid=age >= 1,
        lateral_valid=abs(lat_code) < LAT_INVALID_ABS_CODE,
    )


def relative_velocity(obj: NativeObject, v_ego: float) -> float:
    return obj.v_long_ground - float(v_ego)
