#!/usr/bin/env python3
"""Decode ARS510 objects from a CAN CSV or an openpilot rlog/qlog and write one row per published point.

Inputs:
  - CSV with header t_s,bus,address,data_hex (the format of data/sample/*.csv.gz; .gz is fine)
  - an openpilot rlog / qlog (.bz2 / .zst / raw): needs openpilot's `tools.lib.logreader` importable
    (run from an openpilot checkout's venv, or set PYTHONPATH to the checkout)

Examples:
  python tools/decode_log.py data/sample/highway_following_30s.csv.gz -o tracks.csv
  python tools/decode_log.py /path/to/rlog.zst --profile raw -o tracks.csv
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ars510 import OPENPILOT_CONFIG, RAW_CONFIG, Ars510NativeRadarInterface  # noqa: E402


def frames_from_csv(path: Path) -> Iterator[tuple[float, int, int, bytes]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        for row in csv.DictReader(fh):
            yield float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])


def frames_from_openpilot_log(path: Path) -> Iterator[tuple[float, int, int, bytes]]:
    try:
        from openpilot.tools.lib.logreader import LogReader  # type: ignore
    except ImportError:
        try:
            from tools.lib.logreader import LogReader  # type: ignore
        except ImportError as e:
            raise SystemExit("reading rlog/qlog needs openpilot's LogReader on PYTHONPATH") from e
    for m in LogReader(str(path)):
        if m.which() != "can":
            continue
        t = m.logMonoTime / 1e9
        for f in m.can:
            yield t, f.src, f.address, bytes(f.dat)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("ars510_points.csv"))
    ap.add_argument("--profile", choices=("openpilot", "raw"), default="openpilot")
    args = ap.parse_args()

    name = args.log.name
    frames = frames_from_csv(args.log) if name.endswith((".csv", ".csv.gz")) else frames_from_openpilot_log(args.log)
    iface = Ars510NativeRadarInterface(OPENPILOT_CONFIG if args.profile == "openpilot" else RAW_CONFIG)
    cols = ["time_s", "trackId", "native_id", "slot", "age", "dRel", "yRel", "vRel", "v_long_ground"]
    n_rec, n_pts, tracks = 0, 0, Counter()
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for t, bus, addr, data in frames:
            p = iface.update_frame(t, bus, addr, data)
            if p is None:
                continue
            n_rec += 1
            for pt in p["radarData"]["points"]:
                n_pts += 1
                tracks[pt["trackId"]] += 1
                w.writerow([f"{t:.4f}"] + [f"{pt[c]:.4f}" if isinstance(pt[c], float) else pt[c] for c in cols[1:]])
    print(f"{n_rec} records ({iface.crc_failures} CRC failures), {n_pts} points, {len(tracks)} track ids -> {args.out}")
    print(f"suppressed: settling {iface.settling_suppressed}, unresolved vRel {iface.unresolved_suppressed}; relinks {iface.relinks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
