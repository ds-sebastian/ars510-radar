#!/usr/bin/env python3
"""Make ARS510 objects visible in Cabana: a virtual-bus DBC plus rlogs with the reassembled records appended.

The object list is a 742-byte record segmented over 106 frames on 0x80, so no DBC can decode it from the raw
frames. This tool reassembles each record and appends, on a virtual bus (default 10), one CAN-FD-sized message
per occupied object slot with the slot's own 36 bytes, so the bit positions in the DBC are the real slot bit
positions. The original log is copied unchanged; Cabana sorts events by time.

Virtual bus messages (dbc/ars510_objects_vbus.dbc):
  0x700+slot  ARS510_OBJ_xx          raw slot bytes (36, padded to 48), decoded fields and raw fields
  0x720+slot  ARS510_OBJ_xx_DERIVED  NOT radar bytes: values the interface computes (vRel, trackIds, flags)
  0x740       ARS510_REC_HEADER      0x80 record bytes 0-16
  0x741       ARS510_REC_TRAILER     CRC32 + byte 741
  0x760       ARS510_SHELL85_HDR     0x85 proposed prefix bytes 0-20
  0x761+k     ARS510_SHELL85_CELL_k  ten 12-byte cells
  0x76B       ARS510_SHELL85_CRC     verified CRC32 + two trailer bytes

Usage:
  python tools/build_cabana_route.py --dbc-only                       # regenerate dbc/ars510_objects_vbus.dbc
  python tools/build_cabana_route.py SEG_DIR [SEG_DIR ...] --out OUT  # SEG_DIR holds rlog(.zst|.bz2) (+ cameras)
Then: cabana --data_dir OUT/route "<route name>" --dbc dbc/ars510_objects_vbus.dbc  (see docs/09_tools_and_data.md)

Reading and writing logs needs openpilot's cereal (run from an openpilot venv / PYTHONPATH). --dbc-only does not.
"""
from __future__ import annotations

import argparse
import bz2
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ars510.constants import ID80_IDLE_SLOT, ID80_OBJECT_COUNT, ID80_OBJECT_LEN, ID80_OBJECT_START  # noqa: E402
from ars510.interface import BASE_CONFIG, ALL_TRACKS_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.objects import ACCEL_LIKE, AGE, LAT_DIST, LAT_INVALID_ABS_CODE, LAT_VEL, LONG_DIST, LONG_VEL_GROUND  # noqa: E402
from ars510.record import id80_crc_ok  # noqa: E402
from ars510.shell85 import CELL_COUNT, CELL_LEN, HEADER_LEN, id85_crc_ok  # noqa: E402
from ars510.transport import Id80RecordAssembler, Id85RecordAssembler  # noqa: E402

VBUS = 10
OBJ_BASE, DERIVED_BASE, HEADER_ADDR, TRAILER_ADDR, SHELL_HDR, SHELL_BASE = 0x700, 0x720, 0x740, 0x741, 0x760, 0x761
OBJ_DLC, DERIVED_DLC, HEADER_DLC, TRAILER_DLC, SHELL_HDR_DLC, SHELL_DLC = 48, 16, 20, 8, 24, 12
SHELL_CRC = 0x76B
FUSED_CONFIG = replace(ALL_TRACKS_CONFIG, range_fusion_gain=0.1)
KALMAN_CONFIG = replace(ALL_TRACKS_CONFIG, fused_speed_filter=True, publish_speed_std_mps=99.0)
SETTLED_AGE = 60
BIT_MAP = REPO / "data" / "reference" / "slot_bit_map.json"
DBC_OUT = REPO / "dbc" / "ars510_objects_vbus.dbc"

# One line per signal: the current reading of each field (docs/03_slot_fields.md has the evidence).
SIGNAL_COMMENTS = {
    # slot: kinematics
    "DREL": "Distance forward of the radar, m: (code - 160) / 16. Add 1.52 m for openpilot's camera-referenced distance (radard does).",
    "YREL_LEFT": f"Lateral offset, m, left positive: (code - 2048) / 64. |code - 2048| >= {LAT_INVALID_ABS_CODE} is a sentinel.",
    "VLONG_OVER_GROUND": "Longitudinal velocity over ground, m/s: (code - 510.5) * 0.15. vRel = this - ego speed. Code 1023 is a saturated reading.",
    "VLAT_OVER_GROUND_PROV": "Lateral velocity over ground, m/s, left positive: (code - 510.5) * about 0.145 (0.15 used).",
    "ALONG_LIKE_84": "Longitudinal acceleration over ground, filtered: (code - 511) * about 0.04 m/s^2; follows velocity by 0.5-1 s.",
    "UNK_96": "Lateral acceleration over ground, filtered: (code - 511) * 0.05 m/s^2; follows the kinematic value by about 0.5 s.",
    "UNK_208_6": "Heading-like angle output, approximately pi/64 rad per code. Empirical clipped velocity-angle relation on settled moving tracks; can update while both published velocity codes remain unchanged. Exact inputs/filter/physical direction and timing remain provisional.",
    # slot: lifecycle and confidence
    "STATE_CODE": "Track state: 1 update-like, 2 prediction-like/coasting candidate; 0 rare. State does not certify measurement availability or accuracy. While 2, SCORE_CODE drops by 20 (or 1) per cycle.",
    "SLOT_INDEX_CODE": "Physical slot index 0-19; 63 when the slot is unallocated.",
    "UNK_8_6": "Bits 8-12: startup code, min(30, floor(31 * (2/3)^max(age - 4, 0))) while the motion code is 5 (initializing). Bit 13: separate raw flag.",
    "ONCOMING_FLAG": "Oncoming-like internal motion state. Can persist after slowing and reset before the native allocation ends; a clear flag does not certify past target motion.",
    "SCORE_CODE": "Existence-like score, 0-100: can decline in either state; drops by exactly 20 (or 1) per cycle in state 2. State 1 return does not guarantee recovery; not a calibrated probability. The slot is freed near 20.",
    "AGE": "Track age in radar cycles (60 ms): 1 at birth, saturates at 126; 0 = slot retiring. A restart is a new track. Converged from about 60.",
    "MOVE_STATE": "Low two bits of the motion code. Full code = MOVE_STATE | ((UNK_111_4 & 1) << 2): 0 moving forward, 1 slow or standing, 2 oncoming, 3 moving right, 4 moving left, 5 initializing, 7 stopped after moving.",
    "UNK_111_4": "Bit 111 = bit 2 of the motion code (see MOVE_STATE); bits 112-114 raw.",
    "UNK_107_1": "Coasting-flag candidate: rarely set in settled life, often set just before deletion.",
    # slot: lane assignment
    "UNK_128_2": "Lane-assignment state, low bits (full = UNK_128_2 | UNK_130_1 << 2): 3 ego lane, 2 right lane, 4 left lane; 1, 5, 7 = no lane weights.",
    "UNK_130_1": "Lane-assignment state, bit 2 (see UNK_128_2).",
    "UNK_148_8": "Lane weights in 1/15 steps: low nibble (148|4) right lane, high nibble (152|4) left lane. With UNK_156_4 (ego lane) they sum to 15 or 16.",
    "UNK_156_4": "Ego-lane weight in 1/15 steps (see UNK_148_8).",
    # slot: class and size
    "UNK_163_3": "Object class: 1 not yet classified, 2 car, 3 large vehicle, 4 pedestrian, 5 rare (post-like), 6 two-wheeler.",
    "UNK_140_3": "Object class, second encoding of UNK_163_3: 0, 5, 7, 1, 3, 4 = class 1, 2, 3, 4, 5, 6.",
    "UNK_136_4": "Class-confidence candidate, 0-15; 15 on nearly all pedestrians and two-wheelers.",
    "UNK_56_7": "Object length, about 0.1 m per code: car ~4.9 m, large vehicle ~5.7 m, two-wheeler ~1.7 m, pedestrian ~0.4 m.",
    "UNK_216_6": "Object width, about (code + 1) * 0.1 m: car ~1.8 m, large vehicle ~2.0 m, two-wheeler ~0.7 m, pedestrian ~0.5 m.",
    "UNK_272_5": "Height-like size code (candidate); larger for large vehicles.",
    # slot: uncertainty and quality
    "UNK_224_7": "Range standard deviation (candidate sigma dRel): grows with range, shrinks with track age.",
    "UNK_232_7": "Lateral standard deviation (candidate sigma yRel): grows with |yRel|.",
    "UNK_240_7": "Longitudinal velocity standard deviation (candidate sigma vx): grows with range, higher during velocity excursions. 127 accompanies saturated velocity.",
    "UNK_248_7": "Lateral velocity standard deviation (candidate sigma vy).",
    "UNK_200_7": "Angular uncertainty-like code (candidate), metric units provisional. Raw63 pairs with zero angle in the recorded corpus; raw127 has nonzero-angle exceptions. Preserve all seven bits; not a universal invalidity flag.",
    "UNK_256_6": "Existence-like quantity: rises with track age, drops before deletion.",
    "UNK_262_2": "Upper bits of the existence-like quantity at 256.",
    "UNK_264_5": "Measurement-state-like quantity: settled values depend on range (4 ~10 m, 3 ~12 m, 1 ~30 m, 2 ~47 m); near/far-scan candidate.",
    "UNK_269_3": "Upper bits of the measurement-state-like quantity at 264.",
    "UNK_183_7": "Bit 183 raw; bits 184-189 are the low bits of a secondary score byte 184|8 (59-100).",
    "UNK_190_10": "Bits 190-191 = top of the secondary score byte 184|8; bits 192-199 raw.",
    "UNK_168_10": "Flag word: only codes 0, 768, 832 and 1023 occur.",
    "UNK_15_1": "Raw; mostly set on newborn zero-range rows.",
    "UNK_239_1": "Raw; often set near track birth.",
    "UNK_277_11": "Raw; bit 277 rarely set on newborn tracks.",
    # record header
    "UNK_HDR8_5": "Part of the clock code in record bytes 1-4 (little-endian), which equals the 0x85 fine clock // 100.",
    "UNK_HDR13_4": "Part of the clock code in record bytes 1-4 (see UNK_HDR8_5).",
    "UNK_HDR17_15": "Part of the clock code in record bytes 1-4 (see UNK_HDR8_5).",
    "UNK_HDR33_1": "Part of the clock code in record bytes 1-4 (see UNK_HDR8_5).",
    "UNK_HDR41_15": "Record counter: record bytes 5-6 (little-endian) >> 1; equals the 0x85 counter of the same cycle.",
    "UNK_HDR104_3": "Timing-offset candidate (104|11 region): its change tracks the record's arrival-time offset at about 1 ms per count.",
    "UNK_HDR107_4": "Timing-offset candidate (see UNK_HDR104_3).",
    "UNK_HDR111_4": "Raw; usually 3.",
    "OBJECT_COUNT": "Number of allocated slots (slots whose index field equals their position, including retiring slots). Allocated slots need not be the first N.",
}


def signal_comment(name: str) -> str:
    if name in SIGNAL_COMMENTS:
        return SIGNAL_COMMENTS[name]
    if name.startswith("CONST_"):
        return "Constant in the captured data."
    return "Raw, unnamed."


# Raw windows from the expanded captures that replace the historical bit-map split (data/reference/slot_bit_map.json).
RAW_FIELD_CORRECTIONS = {
    15: [(15, 1, "Mostly set on newborn zero-range rows, with exceptions; not a validity gate.")],
    63: [(63, 1, "Rare changing bit; only two rows in the expanded corpus.")],
    136: [(136, 4, "Independent low nibble beside categorical140|3; units and confidence meaning unresolved."),
          (140, 3, "Categorical raw view. Observed163|3 codes1,2,3,4,5,6 map exactly to0,5,7,1,3,4 here. Physical classes unknown; preserve unexpected pairs.")],
    142: [],
    163: [(163, 3, "Full categorical raw view, including former bit165. Exactly recodes140|3 on tested captures; no verified car/truck/pedestrian labels.")],
    165: [(166, 2, "Remaining upper raw bits after full163|3; no assigned semantics.")],
    182: [(182, 1, "Rare changing bit; observed in one short track episode.")],
    190: [(190, 10, "Observed codes 0 and 1. Usually follows positive age, with three exceptions; not a validity gate.")],
    239: [(239, 1, "Changes within tracks; often active near birth. The former PER_TRACK label was too strong.")],
    256: [(256, 6, "Expanded raw window: repeated 31-to-32 and reverse carries in discovery, confirmation and further drives. Full field width, units and meaning unresolved."),
          (262, 2, "Remaining upper bits are not universally constant. May belong to the preceding quantity; boundary unresolved.")],
    261: [],
    264: [(264, 5, "Expanded raw window: repeated 15-to-16 and reverse carries. Full field width and scan/uncertainty semantics unresolved; old four-bit analyses used only its low bits."),
          (269, 3, "Rare nonzero upper bits; may belong to the preceding quantity. Boundary unresolved.")],
    268: [],
    277: [(277, 11, "Bit277 is set in four CRC-valid early-track samples in a further retained drive. This raw window is not constant. Its semantic boundary with272|5 and physical meaning remain unresolved.")],
}


def _sig(name, start, length, factor, offset, lo, hi, unit, signed=False, rx="XXX"):
    return f' SG_ {name} : {start}|{length}@1{"-" if signed else "+"} ({factor:.10g},{offset:.10g}) [{lo:.10g}|{hi:.10g}] "{unit}" {rx}'


def _named_sig(name):
    if name == "ALONG_LIKE_84":
        return _sig(name, ACCEL_LIKE.bit_start, ACCEL_LIKE.bit_len, 1, -511, -511, 512, "code")
    if name == "UNK_96":
        return _sig(name, 96, 10, 1, 0, 0, 1023, "raw")
    if name == "AGE":
        return _sig(name, AGE.bit_start, AGE.bit_len, 1, 0, 0, 126, "cycles")
    f = {"DREL": LONG_DIST, "YREL_LEFT": LAT_DIST, "VLONG_OVER_GROUND": LONG_VEL_GROUND, "VLAT_OVER_GROUND_PROV": LAT_VEL}[name]
    off = -f.zero_code * f.scale
    return _sig(name, f.bit_start, f.bit_len, f.scale, off, off, ((1 << f.bit_len) - 1) * f.scale + off, f.unit)


def _heuristic(f: dict, start: int | None = None) -> tuple[str, str, str]:
    s, n = (f["start"] if start is None else start), f["len"]
    corr = f" Strongest correlation: {f['best_corr_with']} r={f['best_corr']:+.2f}." if f.get("best_corr_with") else ""
    if f["kind"] == "constant" and f["distinct"] > 1:
        nm = f["name"].replace("CONST_", "PER_TRACK_")
        text = f"Constant within a track, differs between tracks ({f['distinct']} values {f['min']}..{f['max']}): object attribute candidate, unverified.{corr}"
    elif f["kind"] == "constant":
        nm = f["name"]
        text = f"Constant {f['value']} (0x{f['value']:X}) in the original small-corpus survey; not proof of reserved/padding bits or universal constancy."
    else:
        nm = f["name"]
        text = (f"Candidate from the carry-chain split, unverified: LSB flips {f['lsb_flip_rate']:.3f} per cycle, "
                f"{f['distinct']} distinct values {f['min']}..{f['max']}.{corr}")
    return _sig(nm, s, n, 1, 0, 0, (1 << n) - 1, "raw"), nm, text


def dbc_text() -> str:
    bm = json.loads(BIT_MAP.read_text())
    out = ['VERSION "ARS510 reassembled object / shell records on a virtual bus (generated by tools/build_cabana_route.py)"', "",
           "NS_ :", "    CM_", "    VAL_", "", "BS_:", "", "BU_: RADAR XXX", ""]
    comments, vals = [], []
    for s in range(ID80_OBJECT_COUNT):
        m = OBJ_BASE + s
        out.append(f"BO_ {m} ARS510_OBJ_{s:02d}: {OBJ_DLC} RADAR")
        comments.append(f'CM_ BO_ {m} "Reassembled 0x80 object slot {s} (record bytes {ID80_OBJECT_START + 36 * s}-{ID80_OBJECT_START + 36 * s + 35}), sent only when occupied. Little-endian bit field: bit 0 = LSB of slot byte 0.";')
        for f in bm["slot_fields"]:
            if f["start"] in RAW_FIELD_CORRECTIONS:
                for start, width, note in RAW_FIELD_CORRECTIONS[f["start"]]:
                    name = f"UNK_{start}_{width}"
                    out.append(_sig(name, start, width, 1, 0, 0, (1 << width) - 1, "raw"))
                    comments.append(f'CM_ SG_ {m} {name} "{signal_comment(name)}";')
                continue
            if f["start"] == 0 and f["len"] == 2:
                out.append(_sig("STATE_CODE", 0, 2, 1, 0, 0, 3, "raw"))
                comments.append(f'CM_ SG_ {m} STATE_CODE "{signal_comment("STATE_CODE")}";')
                continue
            if f["start"] == 109 and f["len"] == 2:
                out.append(_sig("MOVE_STATE", 109, 2, 1, 0, 0, 3, ""))
                comments.append(f'CM_ SG_ {m} MOVE_STATE "{signal_comment("MOVE_STATE")}";')
                vals.append(f'VAL_ {m} MOVE_STATE 0 "moving forward (or left, with bit 111)" 1 "slow / standing (or initializing)" 2 "oncoming" 3 "moving right (or stopped after moving)" ;')
                continue
            if f["start"] == 14 and f["len"] == 1:
                out.append(_sig("ONCOMING_FLAG", 14, 1, 1, 0, 0, 1, ""))
                comments.append(f'CM_ SG_ {m} ONCOMING_FLAG "{signal_comment("ONCOMING_FLAG")}";')
                vals.append(f'VAL_ {m} ONCOMING_FLAG 0 "clear" 1 "oncoming-like state" ;')
                continue
            if f["start"] == 2 and f["len"] == 6:
                out.append(_sig("SLOT_INDEX_CODE", 2, 6, 1, 0, 0, 63, "raw"))
                comments.append(f'CM_ SG_ {m} SLOT_INDEX_CODE "{signal_comment("SLOT_INDEX_CODE")}";')
                continue
            if 16 <= f["start"] < 24:
                if f["start"] == 16:
                    out.append(_sig("SCORE_CODE", 16, 8, 1, 0, 0, 255, "raw"))
                    comments.append(f'CM_ SG_ {m} SCORE_CODE "{signal_comment("SCORE_CODE")}";')
                continue
            if f["kind"] == "named":
                out.append(_named_sig(f["name"]))
                comments.append(f'CM_ SG_ {m} {f["name"]} "{signal_comment(f["name"])}";')
            else:
                line, nm, text = _heuristic(f)
                out.append(line)
                comments.append(f'CM_ SG_ {m} {nm} "{signal_comment(nm)}";')
        out.append("")
    for s in range(ID80_OBJECT_COUNT):
        m = DERIVED_BASE + s
        out += [f"BO_ {m} ARS510_OBJ_{s:02d}_DERIVED: {DERIVED_DLC} XXX",
                _sig("TRACK_ID_OP", 0, 16, 1, 0, 0, 65535, ""), _sig("TRACK_ID_RAW", 16, 16, 1, 0, 0, 65535, ""),
                _sig("PUBLISHED_OP", 32, 1, 1, 0, 0, 1, ""), _sig("SETTLED", 33, 1, 1, 0, 0, 1, ""),
                _sig("VREL_VALID", 34, 1, 1, 0, 0, 1, ""), _sig("DREL_FUSED_VALID", 35, 1, 1, 0, 0, 1, ""),
                _sig("VREL_KALMAN_VALID", 36, 1, 1, 0, 0, 1, ""),
                _sig("VREL", 40, 16, 0.01, 0, -327.68, 327.67, "m/s", signed=True), _sig("V_EGO_0xB4", 56, 16, 0.01, 0, 0, 655.35, "m/s"),
                _sig("DREL_FUSED", 72, 16, 0.01, 0, 0, 655.35, "m"), _sig("VREL_KALMAN", 88, 16, 0.01, 0, -327.68, 327.67, "m/s", signed=True), ""]
        comments += [
            f'CM_ BO_ {m} "NOT radar bytes: values the ars510 interface computes for 0x80 slot {s}, for plotting next to the raw fields.";',
            f'CM_ SG_ {m} TRACK_ID_OP "trackId openpilot would see under BASE_CONFIG (held until age {BASE_CONFIG.min_publish_age}, re-link within {BASE_CONFIG.relink_max_gap_s:g} s); 0 when not published.";',
            f'CM_ SG_ {m} TRACK_ID_RAW "trackId from the radar slot/age lifecycle alone (ALL_TRACKS_CONFIG).";',
            f'CM_ SG_ {m} VREL "VLONG_OVER_GROUND - Toyota 0xB4 speed, m/s.";',
            f'CM_ SG_ {m} V_EGO_0xB4 "Toyota 0xB4 SPEED used for VREL, m/s (reads ~1.5% below GPS / wheel speed).";',
            f'CM_ SG_ {m} DREL_FUSED "Velocity-aided range (range_fusion_gain {FUSED_CONFIG.range_fusion_gain:g}, part of the fused profile); halves short-term range walks.";',
            f'CM_ SG_ {m} VREL_KALMAN "vRel from the Kalman speed filter of the fused profile (object list, ACC target and summaries weighted by their uncertainty).";',
        ]
        vals += [f'VAL_ {m} PUBLISHED_OP 0 "held back or absent" 1 "published" ;', f'VAL_ {m} SETTLED 0 "settling (age<60)" 1 "settled" ;']

    out.append(f"BO_ {HEADER_ADDR} ARS510_REC_HEADER: {HEADER_DLC} RADAR")
    comments.append(f'CM_ BO_ {HEADER_ADDR} "0x80 record bytes 0-16, before the 20 object slots. Byte 0 is 0xE4 (transport length low byte).";')
    for f in bm["id80_header_fields"]:
        if f["start"] == 111 and f["len"] == 4:
            out.append(_sig("UNK_HDR111_4", 111, 4, 1, 0, 0, 15, "raw"))
            comments.append(f'CM_ SG_ {HEADER_ADDR} UNK_HDR111_4 "{signal_comment("UNK_HDR111_4")}";')
            continue
        if f["name"] == "OBJECT_COUNT":
            out.append(_sig("OBJECT_COUNT", f["start"], f["len"], 1, 0, 0, 20, "slots"))
            comments.append(f'CM_ SG_ {HEADER_ADDR} OBJECT_COUNT "{signal_comment("OBJECT_COUNT")}";')
            continue
        line, nm, text = _heuristic(f)
        out.append(line)
        comments.append(f'CM_ SG_ {HEADER_ADDR} {nm} "{signal_comment(nm)}";')
    out += ["", f"BO_ {TRAILER_ADDR} ARS510_REC_TRAILER: {TRAILER_DLC} RADAR", _sig("RECORD_CRC32", 0, 32, 1, 0, 0, 4294967295, ""),
            _sig("RECORD_B741", 32, 8, 1, 0, 0, 255, "raw"), ""]
    comments.append(f'CM_ SG_ {TRAILER_ADDR} RECORD_CRC32 "zlib CRC32 over record bytes 1-736, little-endian; failing records are not exported.";')

    out += [f"BO_ {SHELL_HDR} ARS510_SHELL85_HDR: {SHELL_HDR_DLC} RADAR"]
    for b in range(HEADER_LEN):
        out.append(_sig(f"PREFIX_BYTE_{b:02d}", 8 * b, 8, 1, 0, 0, 255, "raw"))
    out.append("")
    comments.append(f'CM_ BO_ {SHELL_HDR} "0x85 record bytes 0-20 (prefix). Byte 0 is the length-low byte 0x90; bytes 1-4 fine clock, 5-6 counter.";')
    for k in range(CELL_COUNT):
        m = SHELL_BASE + k
        out.append(f"BO_ {m} ARS510_SHELL85_CELL_{k:02d}: {SHELL_DLC} RADAR")
        for b in range(CELL_LEN):
            out.append(_sig(f"RAW_BYTE_{b:02d}", b * 8, 8, 1, 0, 0, 255, "raw"))
        out.append(_sig("PARAMETERS_PRESENT", 30, 1, 1, 0, 0, 1, ""))
        comments.append(f'CM_ SG_ {m} PARAMETERS_PRESENT "1 = the cell holds parameters (bytes 6-9 differ from the default 84 03 F4 01).";')
        out.append(_sig("CURVE_OFFSET_M", 32, 12, 0.01, -20, -20, 20.95, "m"))
        comments.append(f'CM_ SG_ {m} CURVE_OFFSET_M "c0: (32|12 - 2000) * 0.01 m, left positive. Meaningful when PARAMETERS_PRESENT = 1.";')
        out.append(_sig("CURVE_HEADING_RAD", 48, 16, -1.8e-5, 0.5616, -0.62, 0.57, "rad"))
        comments.append(f'CM_ SG_ {m} CURVE_HEADING_RAD "c1: nominal -1.8e-5 rad per code from zero 31200, left-positive tangent (unit bounded to about 1.6-2.2e-5). Meaningful when PARAMETERS_PRESENT = 1.";')
        out.append(_sig("CURVE_CURVATURE_PER_M", 64, 15, 2.5e-6, -0.04005, -0.0401, 0.0418, "1/m"))
        comments.append(f'CM_ SG_ {m} CURVE_CURVATURE_PER_M "c2: nominal 2.5e-6 1/m per code from zero 16020, left positive (unit bounded to about 2.0-2.7e-6). Meaningful when PARAMETERS_PRESENT = 1.";')
        out.append(_sig("CURVE_RATE_PER_M2", 10, 10, 4e-6, -0.002, -0.0021, 0.0020, "1/m^2"))
        comments.append(f'CM_ SG_ {m} CURVE_RATE_PER_M2 "c3: curvature rate d(kappa)/ds, offset binary around code 500, nominal 4e-6 1/m^2 per code (sign and zero replicated; unit not pinned). Meaningful when PARAMETERS_PRESENT = 1.";')
        out.append(_sig("CURVE_FLAG", 79, 1, 1, 0, 0, 1, "raw"))
        comments.append(f'CM_ SG_ {m} CURVE_FLAG "Bit 79, separate from the curvature value; set on 79-80 % of populated cells 2/3 and 43-44 % of 8/9 (identical in cells 2 and 3). Meaning unresolved.";')
        out.append("")
        o = HEADER_LEN + CELL_LEN * k
        comments.append(f'CM_ BO_ {m} "0x85 cell {k}, record bytes {o}-{o + 11}. Each populated cell is one lane / road-boundary curve y(x) = c0 + c1 x + c2 x^2 / 2 (docs/04); cells 2/3 and 8/9 are two estimates of the ego-lane pair.";')
    out += [f"BO_ {SHELL_CRC} ARS510_SHELL85_CRC: 8 RADAR",
            _sig("RECORD_CRC32", 0, 32, 1, 0, 0, 4294967295, "raw"),
            _sig("TRAILER_BYTES", 32, 16, 1, 0, 0, 65535, "raw"), ""]
    comments.append(f'CM_ BO_ {SHELL_CRC} "CRC at record[141:145] over record[1:141], followed by trailer[145:147]. Failing records are not exported.";')

    first = ["CM_ " + '"Virtual-bus view of the ARS510 0x80 / 0x85 records. Only valid for logs produced by tools/build_cabana_route.py.";']
    return "\n".join(out + [""] + first + comments + vals) + "\n"


def _pad(b: bytes, n: int) -> bytes:
    return b + bytes(n - len(b))


def derived_bytes(track_op, published, track_raw, age, vrel, v_ego, drel_fused=None, vrel_kalman=None) -> bytes:
    value = (track_op & 0xFFFF) | ((track_raw & 0xFFFF) << 16)
    value |= int(published) << 32 | int(age >= SETTLED_AGE) << 33
    ok = vrel == vrel
    value |= int(ok) << 34
    value |= (int(round(vrel * 100)) & 0xFFFF if ok else 0) << 40
    value |= (int(round((v_ego or 0.0) * 100)) & 0xFFFF) << 56
    f_ok = drel_fused is not None and drel_fused == drel_fused
    s_ok = vrel_kalman is not None and vrel_kalman == vrel_kalman
    value |= int(f_ok) << 35 | int(s_ok) << 36
    value |= (int(round(drel_fused * 100)) & 0xFFFF if f_ok else 0) << 72
    value |= (int(round(vrel_kalman * 100)) & 0xFFFF if s_ok else 0) << 88
    return value.to_bytes(DERIVED_DLC, "little")


def _cereal_log():
    try:
        from openpilot.cereal import log  # type: ignore
    except ImportError:
        try:
            from cereal import log  # type: ignore
        except ImportError as e:
            raise SystemExit("building logs needs openpilot's cereal on PYTHONPATH (use --dbc-only otherwise)") from e
    return log


def _raw_log_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".bz2":
        return bz2.decompress(data)
    if path.suffix == ".zst":
        import zstandard  # type: ignore
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    return data


def build_segment(seg_dir: Path, out_route_dir: Path) -> dict:
    log = _cereal_log()
    src = next((seg_dir / n for n in ("rlog", "rlog.zst", "rlog.bz2", "qlog", "qlog.zst", "qlog.bz2") if (seg_dir / n).exists()), None)
    if src is None:
        raise SystemExit(f"no rlog/qlog in {seg_dir}")
    raw = _raw_log_bytes(src)
    out_dir = out_route_dir / seg_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    a80, a85 = Id80RecordAssembler(), Id85RecordAssembler()
    ifaces = {k: Ars510NativeRadarInterface(c) for k, c in
              (("raw", ALL_TRACKS_CONFIG), ("op", BASE_CONFIG), ("fused", FUSED_CONFIG), ("kalman", KALMAN_CONFIG))}
    used, events, n80, n85, v_ego = set(), [], 0, 0, None

    def can_event(t_ns, frames):
        evt = log.Event.new_message(logMonoTime=t_ns, valid=True)
        can = evt.init("can", len(frames))
        for c, (addr, dat) in zip(can, frames):
            c.address, c.dat, c.src = addr, dat, VBUS
        return evt.to_bytes()

    for msg in log.Event.read_multiple_bytes(raw):
        if msg.which() != "can":
            continue
        t = msg.logMonoTime / 1e9
        for f in msg.can:
            used.add(f.address)
            dat = bytes(f.dat)
            if f.src == 0 and f.address == 0xB4 and len(dat) >= 7:
                v_ego = int.from_bytes(dat[5:7], "big") * 0.01 / 3.6
            p = {k: i.update_frame(t, f.src, f.address, dat) for k, i in ifaces.items()}
            if f.src != 1:
                continue
            if f.address == 0x80:
                rec = a80.push(t, dat)
                if rec is None or not id80_crc_ok(rec.payload) or p["raw"] is None:
                    continue
                n80 += 1
                pts = {k: {q["slot"]: q for q in (v or {"radarData": {"points": []}})["radarData"]["points"]} for k, v in p.items()}
                out = [(HEADER_ADDR, _pad(rec.payload[:17], HEADER_DLC)), (TRAILER_ADDR, _pad(rec.payload[737:742], TRAILER_DLC))]
                for s in range(ID80_OBJECT_COUNT):
                    b = rec.payload[ID80_OBJECT_START + s * ID80_OBJECT_LEN:ID80_OBJECT_START + (s + 1) * ID80_OBJECT_LEN]
                    if b == ID80_IDLE_SLOT:
                        continue
                    out.append((OBJ_BASE + s, _pad(b, OBJ_DLC)))
                    rp, op = pts["raw"].get(s), pts["op"].get(s)
                    if rp is not None:
                        out.append((DERIVED_BASE + s, derived_bytes(op["trackId"] if op else 0, op is not None, rp["trackId"], rp["age"],
                                                                     rp["vRel"], v_ego, pts["fused"].get(s, {}).get("dRel"),
                                                                     pts["kalman"].get(s, {}).get("vRel"))))
                events.append(can_event(int(rec.time_s * 1e9), out))
            elif f.address == 0x85:
                rec = a85.push(t, dat)
                if rec is None or not id85_crc_ok(rec.payload):
                    continue
                n85 += 1
                out = [(SHELL_HDR, _pad(rec.payload[:HEADER_LEN], SHELL_HDR_DLC)),
                       (SHELL_CRC, _pad(rec.payload[141:147], 8))]
                for k in range(CELL_COUNT):
                    o = HEADER_LEN + CELL_LEN * k
                    out.append((SHELL_BASE + k, rec.payload[o:o + CELL_LEN]))
                events.append(can_event(int(rec.time_s * 1e9), out))
    synthetic = ({OBJ_BASE + s for s in range(ID80_OBJECT_COUNT)} | {DERIVED_BASE + s for s in range(ID80_OBJECT_COUNT)}
                 | {HEADER_ADDR, TRAILER_ADDR, SHELL_HDR, SHELL_CRC} | {SHELL_BASE + k for k in range(CELL_COUNT)})
    clash = sorted(used & synthetic)
    if clash:
        raise SystemExit(f"{seg_dir}: virtual addresses already used on a real bus: {[hex(a) for a in clash]}")
    with open(out_dir / "rlog", "wb") as fh:
        fh.write(raw)
        for e in events:
            fh.write(e)
    for cam in ("fcamera.hevc", "ecamera.hevc", "qcamera.ts"):
        if (seg_dir / cam).exists() and not (out_dir / cam).exists():
            (out_dir / cam).symlink_to((seg_dir / cam).resolve())
    return {"segment": seg_dir.name, "id80_records": n80, "id85_records": n85}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("segments", nargs="*", type=Path, help="segment directories named <route>--<n>")
    ap.add_argument("--out", type=Path, default=Path("cabana_out"))
    ap.add_argument("--dbc-only", action="store_true")
    args = ap.parse_args()
    DBC_OUT.write_text(dbc_text())
    print("dbc:", DBC_OUT)
    if args.dbc_only:
        return 0
    for seg in args.segments:
        print(build_segment(seg, args.out / "route"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
