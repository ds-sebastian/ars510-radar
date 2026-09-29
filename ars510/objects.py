"""Native decode of one 36-byte 0x80 object slot.

Each slot is read as ONE little-endian bit field: bit 0 is the LSB of slot byte 0, bit 8 the LSB of byte 1,
and so on. `start|length` below uses that numbering (it is also DBC `@1+` Intel numbering on the slot bytes).

Field boundaries come from carry chains between consecutive cycles of the same slot (a higher bit almost
never flips unless the bit below it flips). Scales and zero points come from vehicle physics (wheel speed,
standstill, stationary objects) and were then checked against model-free camera geometry on held-out drives.
docs/03_slot_fields.md describes every field; docs/06_accuracy.md the measured accuracy.

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
# Lateral velocity over ground, left positive. With the rotating-frame correction (vy = dy/dt + yaw_rate * x) it fits
# 0.142-0.145 m/s per code; 0.15 is used here (docs/03). openpilot does not use it (yvRel stays NaN).
LAT_VEL = NativeField("lat_vel_over_ground", 74, 10, 510.5, 0.15, "m/s", "scale_not_pinned")
# Longitudinal acceleration over ground, filtered: zero code 511, about 0.04 m/s^2 per code, follows the velocity by
# 0.5-1 s. Kept in centred codes (docs/03).
ACCEL_LIKE = NativeField("accel_like_84", 84, 10, 511.0, 1.0, "code", "unnamed")
# Track age in radar cycles (~60 ms): 1 at birth, saturates at 126, 0 = slot being retired.
AGE = NativeField("age_cycles", 24, 7, 0.0, 1.0, "cycles", "structure")
# Motion code 109|3: 0 moving forward, 1 slow or standing, 2 oncoming, 3 moving right, 4 moving left, 5 initializing,
# 7 stopped after moving (docs/03). move_state is the historical two-bit view, kept for compatibility.
MOVE_STATE = NativeField("move_state", 109, 2, 0.0, 1.0, "enum", "legacy_coarse_view")
MOVEMENT_CODE = NativeField("movement_code", 109, 3, 0.0, 1.0, "code", "structure_provisional_semantics")
# Startup code 8|5: min(30, floor(31 * (2/3)**max(age - 4, 0))) while the motion code is 5 (initializing).
# Bit 13 is a separate raw flag (docs/03).
RAW8_LOW5 = NativeField("raw8_low5", 8, 5, 0.0, 1.0, "code", "structure_semantics_unresolved")
RAW13_BIT = NativeField("raw13_bit", 13, 1, 0.0, 1.0, "bit", "structure_semantics_unresolved")
# Lane state 128|3: 3 ego lane, 2 right lane, 4 left lane; 1 / 5 / 7 = no lane weights (docs/03).
RAW_WEIGHT_STATE128 = NativeField("raw_weight_state128", 128, 3, 0.0, 1.0, "code", "structure_provisional_semantics")
# Lane weights in 1/15 steps: 148|4 right lane, 152|4 left lane, 156|4 ego lane; nonzero triplets sum to 15 or 16
# (docs/03). Raw wire values are kept as they are.
RAW_WEIGHT_148 = NativeField("raw_weight148", 148, 4, 0.0, 1.0, "code", "structure_semantics_unresolved")
RAW_WEIGHT_152 = NativeField("raw_weight152", 152, 4, 0.0, 1.0, "code", "structure_semantics_unresolved")
RAW_WEIGHT_156 = NativeField("raw_weight156", 156, 4, 0.0, 1.0, "code", "structure_semantics_unresolved")
# Oncoming flag (passed a pre-registered test): 1 = oncoming now or earlier in the track's life (it persists after
# an oncoming object slows or stops).
ONCOMING_FLAG = NativeField("oncoming_flag", 14, 1, 0.0, 1.0, "flag", "tested_semantics")

# Velocity standard deviation (sigma vx) candidate: grows with range and during velocity excursions, higher when the
# velocity disagrees with the camera by > 2 m/s. Relative confidence; unit not pinned (docs/03).
VEL_UNC_240 = NativeField("vel_uncertainty_candidate", 240, 7, 0.0, 1.0, "code", "candidate")

# Historical labels only; full code 3 is rightward-like while full code 7 is stopped-like.
MOVE_STATE_NAMES = {0: "moving_away", 1: "not_clearly_moving", 2: "moving_toward", 3: "not_clearly_moving_3"}

AGE_SATURATION = 126
# |lateral code - 2048| >= this is a sentinel, not a position.
LAT_INVALID_ABS_CODE = 2000

NAMED_FIELDS = (AGE, LONG_DIST, LAT_DIST, LONG_VEL_GROUND, LAT_VEL, ACCEL_LIKE, MOVE_STATE, MOVEMENT_CODE, RAW8_LOW5, RAW13_BIT, ONCOMING_FLAG, VEL_UNC_240, RAW_WEIGHT_STATE128, RAW_WEIGHT_148, RAW_WEIGHT_152, RAW_WEIGHT_156)


def slot_bits(slot: bytes, start: int, length: int) -> int:
    return (int.from_bytes(slot, "little") >> start) & ((1 << length) - 1)


def field_code(slot: bytes, field: NativeField) -> int:
    return slot_bits(slot, field.bit_start, field.bit_len)


def field_value(slot: bytes, field: NativeField) -> float:
    return (field_code(slot, field) - field.zero_code) * field.scale


def encode_slot(**codes: int) -> bytes:
    """Build a synthetic slot from raw codes, e.g. encode_slot(long_dist=640, age=40). Unset bits are 0."""
    if "move_state" in codes and "movement_code" in codes:
        if (int(codes["move_state"]) & 3) != (int(codes["movement_code"]) & 3):
            raise ValueError("move_state must equal the low two bits of movement_code")
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
    move_state: int  # legacy low two bits; see movement_code for distinct full states
    oncoming_flag: bool  # oncoming now or earlier in the track's life
    vel_unc_code: int  # candidate velocity-uncertainty code (240|7), relative confidence only
    geometry_valid: bool  # age >= 1 (age 0 carries the previous occupant's stale geometry)
    lateral_valid: bool  # lateral code is not the sentinel
    movement_code: int | None = None  # full 109|3; None for legacy manually constructed objects
    raw8_low5: int | None = None  # startup decay code; mature semantics unknown
    raw13_bit: int | None = None  # separately changing raw bit; meaning unknown
    raw_weights148: tuple[int, int, int] | None = None  # 148/152/156|4; outcomes and units unknown
    raw_weight_state128: int | None = None  # 128|3; availability/category association, not validity
    vel_code: int = -1  # raw 64|10 code; 1023 is a saturated (invalid) reading


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
        movement_code=int(field_code(slot, MOVEMENT_CODE)),
        raw8_low5=int(field_code(slot, RAW8_LOW5)),
        raw13_bit=int(field_code(slot, RAW13_BIT)),
        raw_weights148=tuple(field_code(slot, f) for f in (RAW_WEIGHT_148, RAW_WEIGHT_152, RAW_WEIGHT_156)),
        raw_weight_state128=int(field_code(slot, RAW_WEIGHT_STATE128)),
        oncoming_flag=bool(field_code(slot, ONCOMING_FLAG)),
        vel_unc_code=int(field_code(slot, VEL_UNC_240)),
        geometry_valid=age >= 1,
        lateral_valid=abs(lat_code) < LAT_INVALID_ABS_CODE,
        vel_code=int(field_code(slot, LONG_VEL_GROUND)),
    )


def relative_velocity(obj: NativeObject, v_ego: float) -> float:
    return obj.v_long_ground - float(v_ego)
