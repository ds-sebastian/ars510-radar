"""0x85 lane / road-curve cells: field extraction, the heading relation on the bundled samples, and the prefix flag copies."""
from __future__ import annotations

import csv
import gzip
from pathlib import Path

from ars510.interface import parse_toyota_speed_mps
from ars510.shell85 import (
    CELL_LEN,
    CURVE_CURVATURE_ZERO,
    CURVE_HEADING_ZERO,
    ShellCell,
    parse_shell,
    prefix_flags_consistent,
)
from ars510.transport import Id85RecordAssembler

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample"
NAMES = ("highway_following_30s.csv.gz", "highway_vrel_excursion_25s.csv.gz", "highway_acc_anchor_24s.csv.gz")


def cell_payload(offset=2000, heading=31200, curvature=16020, flag=0, present=True, rate=500) -> bytes:
    value = (rate & 0x3FF) << 10 | (offset & 0xFFF) << 32 | (heading & 0xFFFF) << 48 | (curvature & 0x7FFF) << 64 | (flag & 1) << 79
    if present:
        value |= 1 << 30
    return value.to_bytes(CELL_LEN, "little")


def test_fields_extract_at_documented_bits_and_flag_is_separate_from_curvature():
    cell = ShellCell(2, cell_payload(offset=2173, heading=31061, curvature=16200, flag=1))
    assert cell.parameters_present
    assert (cell.offset_code, cell.heading_code, cell.curvature_code, cell.curve_flag) == (2173, 31061, 16200, 1)
    assert cell.rate_code == 500 and abs(cell.curvature_rate_per_m2) < 1e-12
    assert abs(cell.lane_offset_m - 1.73) < 1e-9
    assert cell.heading_rad > 0 and cell.curvature_per_m > 0                      # code below / above the zero
    flipped = ShellCell(2, cell_payload(offset=2173, heading=31061, curvature=16200, flag=0))
    assert flipped.curvature_code == 16200 and flipped.curve_flag == 0           # bit 79 does not move the 15-bit value
    zero = ShellCell(3, cell_payload(heading=CURVE_HEADING_ZERO, curvature=CURVE_CURVATURE_ZERO))
    assert abs(zero.heading_rad) < 1e-12 and abs(zero.curvature_per_m) < 1e-12


def test_default_cell_holds_defaults_and_has_no_conversions():
    default = ShellCell(0, bytes.fromhex("000000000000" + "8403f401" + "0000"))
    assert not default.parameters_present
    assert (default.heading_code, default.curvature_code, default.curve_flag) == (900, 500, 0)
    assert default.rate_code == 0 or default.curvature_rate_per_m2 is None
    assert default.lane_offset_m is None and default.heading_rad is None and default.curvature_per_m is None


def _cells_and_speeds(name):
    asm, recs, speeds = Id85RecordAssembler(), [], []
    with gzip.open(SAMPLES / name, "rt") as fh:
        for r in csv.DictReader(fh):
            t, bus, addr, data = float(r["t_s"]), int(r["bus"]), int(r["address"], 0), bytes.fromhex(r["data_hex"])
            if bus == 1 and addr == 0x85:
                rec = asm.push(t, data)
                if rec is not None:
                    recs.append((rec.time_s, rec.payload))
            elif bus == 0 and addr == 0xB4 and (v := parse_toyota_speed_mps(data)) is not None:
                speeds.append((t, v))
    return recs, speeds


def _rank(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    for r, i in enumerate(order):
        ranks[i] = float(r)
    return ranks


def _spearman(x, y):
    a, b = _rank(x), _rank(y)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((p - ma) * (q - mb) for p, q in zip(a, b))
    return num / (sum((p - ma) ** 2 for p in a) * sum((q - mb) ** 2 for q in b)) ** 0.5


def test_prefix_flag_copies_and_heading_offset_rate_relation_on_bundled_samples():
    rate, code, records = {2: [], 3: []}, {2: [], 3: []}, 0
    for name in NAMES:
        recs, speeds = _cells_and_speeds(name)
        last = {}
        for t, payload in recs:
            prefix, cells = parse_shell(payload)
            records += 1
            assert prefix_flags_consistent(prefix, cells)
            v = min(speeds, key=lambda s: abs(s[0] - t))[1]
            for k in (2, 3):
                cell = cells[k]
                if not cell.parameters_present:
                    last.pop(k, None)
                    continue
                if k in last:
                    t0, off0, v0 = last[k]
                    dt = t - t0
                    if 0.05 < dt < 0.07 and abs(cell.offset_code - off0) < 100 and v0 > 8:
                        rate[k].append((cell.offset_code - off0) * 0.01 / dt / v0)
                        code[k].append(cell.heading_code)
                last[k] = (t, cell.offset_code, v)
    assert records > 1000
    for k in (2, 3):
        assert len(rate[k]) > 500
        # lane offset rate per metre driven falls as the heading code rises: ~ -0.55 on these 70 s of highway
        assert _spearman(code[k], rate[k]) < -0.4
