#!/usr/bin/env python3
"""One pass over a drive's rlogs -> the inputs fork_replay.py needs, in one directory.

  ticks.pkl      per modelV2 message: time, carState, both vision leads, lane lines (pickle: use only your own files)
  pts_raw.csv    radar points of the `raw` profile (time_s, trackId, dRel, yRel, vRel)
  pts_fused.csv  the same for `fused`
  pts_acc.csv    the radar's own ACC target (0x235 / 0x237) as one point per sample: the reference (the radar's own ACC tracker)

Needs openpilot's `LogReader` importable (run from an openpilot checkout's venv, or PYTHONPATH=checkout), like
decode_log.py. Pass consecutive segments of one drive in order.

  python tools/fork_lead/prepare_route.py -o route_dir seg0/rlog.zst seg1/rlog.zst ...
"""
from __future__ import annotations

import argparse
import csv
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ars510 import BASE_CONFIG, FUSED_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.support import parse_acc_target  # noqa: E402


def log_reader():
    try:
        from openpilot.tools.lib.logreader import LogReader  # type: ignore
    except ImportError:
        try:
            from tools.lib.logreader import LogReader  # type: ignore
        except ImportError as e:
            raise SystemExit("needs openpilot's LogReader on PYTHONPATH") from e
    return LogReader


def lead_dict(lead) -> dict:
    return dict(prob=float(lead.prob), x=list(lead.x), y=list(lead.y), v=list(lead.v), a=list(lead.a),
                xStd=list(lead.xStd), yStd=list(lead.yStd), vStd=list(lead.vStd), aStd=list(lead.aStd))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    LogReader = log_reader()
    ifaces = {"raw": Ars510NativeRadarInterface(BASE_CONFIG), "fused": Ars510NativeRadarInterface(FUSED_CONFIG)}
    files = {}
    writers = {}
    for name in ("raw", "fused", "acc"):
        files[name] = open(args.out / f"pts_{name}.csv", "w", newline="")
        writers[name] = csv.writer(files[name])
        writers[name].writerow(["time_s", "trackId", "dRel", "yRel", "vRel"])

    ticks: list[dict] = []
    car = None
    last235 = None
    for path in args.logs:
        try:
            for m in LogReader(str(path)):
                which = m.which()
                t = m.logMonoTime / 1e9
                if which == "can":
                    for f in m.can:
                        if not (f.src == 1 or (f.src == 0 and f.address == 0xB4)):
                            continue
                        data = bytes(f.dat)
                        for name, iface in ifaces.items():
                            rec = iface.update_frame(t, f.src, f.address, data)
                            if rec is not None:
                                for p in rec["radarData"]["points"]:
                                    writers[name].writerow([f"{t:.4f}", p["trackId"], f"{p['dRel']:.3f}",
                                                            f"{p['yRel']:.3f}", f"{p['vRel']:.3f}"])
                        if f.src == 1 and f.address == 0x235:
                            last235 = data
                        elif f.src == 1 and f.address == 0x237 and last235 is not None:
                            tg = parse_acc_target(last235, data)
                            if tg is not None and tg.d_rel > 1.0:
                                writers["acc"].writerow([f"{t:.4f}", 1000 + tg.target_id, f"{tg.d_rel:.3f}",
                                                         f"{tg.y_rel:.3f}", f"{tg.v_rel:.3f}"])
                elif which == "carState":
                    c = m.carState
                    car = dict(vEgo=float(c.vEgo), aEgo=float(c.aEgo), standstill=bool(c.standstill))
                elif which == "modelV2" and car is not None:
                    md = m.modelV2
                    if len(md.leadsV3) < 2:
                        continue
                    ticks.append(dict(
                        t=t, car=dict(car), leads=[lead_dict(md.leadsV3[0]), lead_dict(md.leadsV3[1])],
                        lanes=[(list(md.laneLines[i].x), list(md.laneLines[i].y)) for i in range(4)],
                        pos_x_last=float(md.position.x[-1]),
                        model_v_ego=float(md.velocity.x[0]) if len(md.velocity.x) else car["vEgo"],
                        lc_state=str(md.meta.laneChangeState), lc_dir=str(md.meta.laneChangeDirection)))
        except Exception as e:  # noqa: BLE001  # a segment cut off at the end of a drive
            print(f"{path}: stopped early ({type(e).__name__})", file=sys.stderr)
    for f in files.values():
        f.close()
    with open(args.out / "ticks.pkl", "wb") as fh:
        pickle.dump(ticks, fh)
    print(f"{len(ticks)} ticks ({len(ticks) / 20 / 60:.1f} min) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
