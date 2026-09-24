#!/usr/bin/env python3
"""Make ARS510 objects visible in Cabana: a virtual-bus DBC plus rlogs with the reassembled records appended.

The object list is a 742-byte record segmented over 106 frames on 0x80, so no DBC can decode it from the raw
frames. This tool reassembles each record and appends, on a virtual bus (default 10), one CAN-FD-sized message
per occupied object slot with the slot's own 36 bytes, so the bit positions in the DBC are the real slot bit
positions. The original log is copied unchanged; Cabana sorts events by time.

Virtual bus messages (dbc/ars510_objects_vbus.dbc):
  0x700+slot  ARS510_OBJ_xx          raw slot bytes (36, padded to 48), native fields + unverified candidates
  0x720+slot  ARS510_OBJ_xx_DERIVED  NOT radar bytes: values the interface computes (vRel, trackIds, flags)
  0x740       ARS510_REC_HEADER      0x80 record bytes 0-16
  0x741       ARS510_REC_TRAILER     CRC32 + byte 741
  0x760       ARS510_SHELL85_HDR     0x85 proposed prefix bytes 0-20
  0x761+k     ARS510_SHELL85_CELL_k  ten provisional raw cells, no object semantics
  0x76B       ARS510_SHELL85_CRC     verified CRC32 + two trailer bytes

Usage:
  python tools/build_cabana_route.py --dbc-only                       # regenerate dbc/ars510_objects_vbus.dbc
  python tools/build_cabana_route.py SEG_DIR [SEG_DIR ...] --out OUT  # SEG_DIR holds rlog(.zst|.bz2) (+ cameras)
Then: cabana --data_dir OUT/route "<route name>" --dbc dbc/ars510_objects_vbus.dbc  (see docs/cabana.md)

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
from ars510.interface import OPENPILOT_CONFIG, RAW_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.objects import ACCEL_LIKE, AGE, LAT_DIST, LAT_INVALID_ABS_CODE, LAT_VEL, LONG_DIST, LONG_VEL_GROUND  # noqa: E402
from ars510.record import id80_crc_ok  # noqa: E402
from ars510.shell85 import CELL_COUNT, CELL_LEN, HEADER_LEN, id85_crc_ok  # noqa: E402
from ars510.transport import Id80RecordAssembler, Id85RecordAssembler  # noqa: E402

VBUS = 10
OBJ_BASE, DERIVED_BASE, HEADER_ADDR, TRAILER_ADDR, SHELL_HDR, SHELL_BASE = 0x700, 0x720, 0x740, 0x741, 0x760, 0x761
OBJ_DLC, DERIVED_DLC, HEADER_DLC, TRAILER_DLC, SHELL_HDR_DLC, SHELL_DLC = 48, 16, 20, 8, 24, 12
SHELL_CRC = 0x76B
FUSED_CONFIG = replace(RAW_CONFIG, range_fusion_gain=0.1)
SMOOTH_CONFIG = replace(RAW_CONFIG, vrel_smooth_far_tau_s=1.0)
SETTLED_AGE = 60
BIT_MAP = REPO / "data" / "reference" / "slot_bit_map.json"
DBC_OUT = REPO / "dbc" / "ars510_objects_vbus.dbc"

NAMED_COMMENTS = {
    "AGE": "Track age in radar cycles (~60 ms): 1 at birth, saturates at 126; 0 = slot being retired (geometry is the previous occupant's). A restart is a new track. Tracks younger than ~60 carry unconverged range and velocity.",
    "DREL": "Longitudinal distance forward of the radar, m. 1/16 m, zero code 160 (exactly -10 m). Camera ground contact at 5-25 m: slope 0.99-1.00 on three drives, zero within 0.2 m (0.7 m on a hilly drive). Settled tracks walk by metres record to record at 40 m+; young tracks can be far off.",
    "YREL_LEFT": f"Lateral offset, LEFT positive (openpilot yRel), m. 1/64 m, offset binary around 2048. Cartesian (constant across range), not an angle. Correct side 97.9-99.3% on held-out drives; scale bounded to about +/-10%. |code-2048| >= {LAT_INVALID_ABS_CODE} is a sentinel.",
    "VLONG_OVER_GROUND": "Longitudinal velocity OVER GROUND, m/s. 0.15 m/s/code, zero 510.5. vRel = this - ego speed. Radar-only scale check (own range slope vs GPS ego) gives 0.150/0.149/0.153 on three drives. Beats zero and range differencing against a camera reference, but has unflagged ~1 s excursions at range. Unsettled for age < ~60.",
    "VLAT_OVER_GROUND_PROV": "Provisional lateral velocity over ground (left positive), same scale and zero as VLONG; not independently pinned.",
    "ALONG_LIKE_84": "Acceleration-like, zero code 511 at standstill. Follows the VLONG change over the PREVIOUS ~1 s, so it cannot flag or lead a velocity excursion. Scale not pinned; centred codes.",
    "UNK_96": "Unnamed 10-bit carry chain centred near 511; no relation to velocity or range error on three drives.",
}
CANDIDATE_NOTES = {
    "UNK_8_6": " Ramps up with age and saturates at 62; tracks range and scenario, not measured error.",
    "UNK_224_7": " Scales with range (r~0.8); no range-controlled relation to velocity or range error.",
    "UNK_240_7": " Scales with range (r~0.8); after range control a weak velocity-error correlate (rho 0.15-0.20), uncertainty-like, but it does not single out excursions.",
    "UNK_232_7": " Scales with |yRel| (r~0.6): lateral-uncertainty-like; no range-controlled error relation.",
    "UNK_248_7": " Scales with |yRel| (r~0.56); no range-controlled error relation.",
    "UNK_256_5": " Rises with track age (r~+0.7): existence/confidence-like candidate.",
    "UNK_264_5": " Falls with track age (r~-0.8): uncertainty-like candidate.",
    "CONST_2_6": " Physical slot index or 63 when unallocated; not an object category. Lane correlations reflect allocation.",
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
        text = f"Constant {f['value']} (0x{f['value']:X}) in every record observed: reserved/padding or configuration."
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
            if f["start"] == 0 and f["len"] == 2:
                out.append(_sig("STATE_CODE", 0, 2, 1, 0, 0, 3, "raw"))
                comments.append(f'CM_ SG_ {m} STATE_CODE "Raw lifecycle state. Measured/predicted semantics not proved; not an accuracy gate.";')
                continue
            if f["start"] == 2 and f["len"] == 6:
                out.append(_sig("SLOT_INDEX_CODE", 2, 6, 1, 0, 0, 63, "raw"))
                comments.append(f'CM_ SG_ {m} SLOT_INDEX_CODE "Physical slot index or 63 in unallocated-form headers; verified against slot positions. Not class or reference point.";')
                continue
            if 16 <= f["start"] < 24:
                if f["start"] == 16:
                    out.append(_sig("SCORE_CODE", 16, 8, 1, 0, 0, 255, "raw"))
                    comments.append(f'CM_ SG_ {m} SCORE_CODE "Bounded score-like byte, not calibrated confidence or percent. Value 100 does not guarantee accurate geometry or velocity.";')
                continue
            if f["kind"] == "named":
                out.append(_named_sig(f["name"]))
                comments.append(f'CM_ SG_ {m} {f["name"]} "{NAMED_COMMENTS[f["name"]]}";')
            else:
                line, nm, text = _heuristic(f)
                out.append(line)
                comments.append(f'CM_ SG_ {m} {nm} "{text}{CANDIDATE_NOTES.get(f["name"], "")}";')
        out.append("")
    for s in range(ID80_OBJECT_COUNT):
        m = DERIVED_BASE + s
        out += [f"BO_ {m} ARS510_OBJ_{s:02d}_DERIVED: {DERIVED_DLC} XXX",
                _sig("TRACK_ID_OP", 0, 16, 1, 0, 0, 65535, ""), _sig("TRACK_ID_RAW", 16, 16, 1, 0, 0, 65535, ""),
                _sig("PUBLISHED_OP", 32, 1, 1, 0, 0, 1, ""), _sig("SETTLED", 33, 1, 1, 0, 0, 1, ""),
                _sig("VREL_VALID", 34, 1, 1, 0, 0, 1, ""), _sig("DREL_FUSED_VALID", 35, 1, 1, 0, 0, 1, ""),
                _sig("VREL_SMOOTHED_VALID", 36, 1, 1, 0, 0, 1, ""),
                _sig("VREL", 40, 16, 0.01, 0, -327.68, 327.67, "m/s", signed=True), _sig("V_EGO_0xB4", 56, 16, 0.01, 0, 0, 655.35, "m/s"),
                _sig("DREL_FUSED", 72, 16, 0.01, 0, 0, 655.35, "m"), _sig("VREL_SMOOTHED", 88, 16, 0.01, 0, -327.68, 327.67, "m/s", signed=True), ""]
        comments += [
            f'CM_ BO_ {m} "NOT radar bytes: values the ars510 interface computes for 0x80 slot {s}, for plotting next to the raw fields.";',
            f'CM_ SG_ {m} TRACK_ID_OP "trackId openpilot would see under OPENPILOT_CONFIG (held until age {OPENPILOT_CONFIG.min_publish_age}, re-link within {OPENPILOT_CONFIG.relink_max_gap_s:g} s); 0 when not published.";',
            f'CM_ SG_ {m} TRACK_ID_RAW "trackId from the radar slot/age lifecycle alone (RAW_CONFIG).";',
            f'CM_ SG_ {m} VREL "VLONG_OVER_GROUND - Toyota 0xB4 speed, m/s.";',
            f'CM_ SG_ {m} V_EGO_0xB4 "Toyota 0xB4 SPEED used for VREL, m/s (reads ~1.5% below GPS / wheel speed).";',
            f'CM_ SG_ {m} DREL_FUSED "Candidate, not in OPENPILOT_CONFIG: velocity-aided range (gain {FUSED_CONFIG.range_fusion_gain:g}); halves short-term range walks vs the camera.";',
            f'CM_ SG_ {m} VREL_SMOOTHED "Candidate, not in OPENPILOT_CONFIG: causal EMA on VREL, tau 0 s below 30 m rising to {SMOOTH_CONFIG.vrel_smooth_far_tau_s:g} s from 60 m; ~0.5 s later true braking.";',
        ]
        vals += [f'VAL_ {m} PUBLISHED_OP 0 "held back or absent" 1 "published" ;', f'VAL_ {m} SETTLED 0 "settling (age<60)" 1 "settled" ;']

    out.append(f"BO_ {HEADER_ADDR} ARS510_REC_HEADER: {HEADER_DLC} RADAR")
    comments.append(f'CM_ BO_ {HEADER_ADDR} "0x80 record bytes 0-16, before the 20 object slots. Byte 0 is 0xE4 (transport length low byte).";')
    for f in bm["id80_header_fields"]:
        line, nm, text = _heuristic(f)
        out.append(line)
        comments.append(f'CM_ SG_ {HEADER_ADDR} {nm} "{text}";')
    out += ["", f"BO_ {TRAILER_ADDR} ARS510_REC_TRAILER: {TRAILER_DLC} RADAR", _sig("RECORD_CRC32", 0, 32, 1, 0, 0, 4294967295, ""),
            _sig("RECORD_B741", 32, 8, 1, 0, 0, 255, "raw"), ""]
    comments.append(f'CM_ SG_ {TRAILER_ADDR} RECORD_CRC32 "zlib CRC32 over record bytes 1-736, little-endian; failing records are not exported.";')

    out += [f"BO_ {SHELL_HDR} ARS510_SHELL85_HDR: {SHELL_HDR_DLC} RADAR"]
    for b in range(HEADER_LEN):
        out.append(_sig(f"PREFIX_BYTE_{b:02d}", 8 * b, 8, 1, 0, 0, 255, "raw"))
    out.append("")
    comments.append(f'CM_ BO_ {SHELL_HDR} "0x85 bytes 0-20, proposed prefix only. Byte 0 is length-low 0x90. Cell alignment and semantics remain provisional.";')
    for k in range(CELL_COUNT):
        m = SHELL_BASE + k
        out.append(f"BO_ {m} ARS510_SHELL85_CELL_{k:02d}: {SHELL_DLC} RADAR")
        for b in range(CELL_LEN):
            out.append(_sig(f"RAW_BYTE_{b:02d}", b * 8, 8, 1, 0, 0, 255, "raw"))
        out.append("")
        o = HEADER_LEN + CELL_LEN * k
        comments.append(f'CM_ BO_ {m} "Provisional 0x85 analysis cell {k}, bytes {o}-{o + 11}; raw bytes, not a proven object. Excludes CRC and trailer.";')
    out += [f"BO_ {SHELL_CRC} ARS510_SHELL85_CRC: 8 RADAR",
            _sig("RECORD_CRC32", 0, 32, 1, 0, 0, 4294967295, "raw"),
            _sig("TRAILER_BYTES", 32, 16, 1, 0, 0, 65535, "raw"), ""]
    comments.append(f'CM_ BO_ {SHELL_CRC} "CRC at record[141:145] over record[1:141], followed by trailer[145:147]. Failing records are not exported.";')

    first = ["CM_ " + '"Virtual-bus view of the ARS510 0x80 / 0x85 records. Only valid for logs produced by tools/build_cabana_route.py.";']
    return "\n".join(out + [""] + first + comments + vals) + "\n"


def _pad(b: bytes, n: int) -> bytes:
    return b + bytes(n - len(b))


def derived_bytes(track_op, published, track_raw, age, vrel, v_ego, drel_fused=None, vrel_smoothed=None) -> bytes:
    value = (track_op & 0xFFFF) | ((track_raw & 0xFFFF) << 16)
    value |= int(published) << 32 | int(age >= SETTLED_AGE) << 33
    ok = vrel == vrel
    value |= int(ok) << 34
    value |= (int(round(vrel * 100)) & 0xFFFF if ok else 0) << 40
    value |= (int(round((v_ego or 0.0) * 100)) & 0xFFFF) << 56
    f_ok = drel_fused is not None and drel_fused == drel_fused
    s_ok = vrel_smoothed is not None and vrel_smoothed == vrel_smoothed
    value |= int(f_ok) << 35 | int(s_ok) << 36
    value |= (int(round(drel_fused * 100)) & 0xFFFF if f_ok else 0) << 72
    value |= (int(round(vrel_smoothed * 100)) & 0xFFFF if s_ok else 0) << 88
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
              (("raw", RAW_CONFIG), ("op", OPENPILOT_CONFIG), ("fused", FUSED_CONFIG), ("smooth", SMOOTH_CONFIG))}
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
                                                                     pts["smooth"].get(s, {}).get("vRel"))))
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
