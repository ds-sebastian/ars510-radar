#!/usr/bin/env python3
"""Replay logged drives through openpilot's REAL radard + longitudinal planner with ARS510 radar points.

For every logged modelV2 message (radard's cadence), one pipeline per profile steps side by side. Each is an
unmodified `RadarD` feeding an unmodified `LongitudinalPlanner`:
  - vision:     empty radar points (what a radarless car runs)
  - raw:        ars510 RAW_CONFIG
  - openpilot:  ars510 OPENPILOT_CONFIG
  - plus any candidate profile from PROFILES below
radard gets the latest radar record completed before each model message. Planner inputs are the logged
carState, controlsState, selfdriveState, vehicleParameters and carControl.

This is OPEN-LOOP: ego motion stays as recorded, so plans after the first divergence are what openpilot
would have requested, not what the car would have done. It is a regression tool, not a safety proof.

Usage (openpilot venv; nothing is written into the checkout):
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$OP:$REPO $OP/.venv/bin/python tools/openpilot_replay/replay_radard.py \\
      --openpilot $OP [--mpc-shadow op_shadow] --force-engaged --out replay_out  seg1/rlog seg2/rlog ...
Pass consecutive segments of one drive in order. Radar-interface state (track IDs, re-link history) and consumer
state (radard, planner, message state, latest radar record) carry across them, so the output matches one continuous
pass over the drive. Everything resets when the CAN stream has a gap longer than MAX_CAN_GAP_S (a different drive
or a missing segment). FakeSM bypasses messaging-health checks: numeric injection is not a timeout test.

Outputs: <out>/ticks.csv.gz (one row per model tick and profile columns) and <out>/summary.json:
FCW ticks per profile, and "native-only braking episodes" (profile aTarget <= -1 m/s^2 while vision-only
>= -0.3), which is the census to review against video or a camera reference.
Tested against openpilot 10b9e73 (September 2026); radard / planner APIs change between versions.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from ars510 import OPENPILOT_CONFIG, RAW_CONFIG, Ars510NativeRadarInterface  # noqa: E402

PROFILES = {
    "raw": RAW_CONFIG,
    "openpilot": OPENPILOT_CONFIG,
    # candidates (each failed a pre-registered test; see docs/06)
    "openpilot_fused": replace(OPENPILOT_CONFIG, range_fusion_gain=0.1),
    "openpilot_rangeclip": replace(OPENPILOT_CONFIG, vrel_range_clip_window_s=4.0, vrel_range_clip_mps=3.5),
    "openpilot_vsmooth": replace(OPENPILOT_CONFIG, vrel_smooth_far_tau_s=1.0),
}
SM_KEYS = ("carState", "controlsState", "selfdriveState", "vehicleParameters", "carControl")
MAX_CAN_GAP_S = 2.0


class FakeSM:
    """The subset of SubMaster that RadarD.update reads."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.seen = defaultdict(bool)
        self.recv_frame = defaultdict(int)
        self.logMonoTime = defaultdict(int)
        self._frames = defaultdict(int)

    def __getitem__(self, key):
        return self.data[key]

    def put(self, name, value, t_ns) -> None:
        self.data[name] = value
        self.seen[name] = True
        self._frames[name] += 1
        self.recv_frame[name] = self._frames[name]
        self.logMonoTime[name] = t_ns

    def all_checks(self) -> bool:
        return True


def radar_tracks(LogReader, rlog: Path, ifaces: dict, last_t: float | None):
    """Feed one rlog to the (persistent) interfaces.

    Returns ({profile: [(completion logMonoTime, [(trackId, dRel, yRel, vRel), ...]), ...]}, ifaces, last CAN time,
    reset) where `reset` is True when a CAN gap forced fresh interfaces at the start of this rlog.
    """
    out = {p: [] for p in ifaces}
    reset = False
    for msg in LogReader(str(rlog)):
        if msg.which() != "can":
            continue
        t = msg.logMonoTime / 1e9
        if last_t is None or t - last_t > MAX_CAN_GAP_S:
            if last_t is not None:
                reset = reset or not any(out.values())  # gap before this rlog's first record: a new drive
            ifaces = {p: Ars510NativeRadarInterface(PROFILES[p]) for p in ifaces}
        last_t = t
        for f in msg.can:
            dat = bytes(f.dat)
            for p, iface in ifaces.items():
                r = iface.update_frame(t, f.src, f.address, dat)
                if r is not None:
                    pts = [(q["trackId"], q["dRel"], q["yRel"], q["vRel"]) for q in r["radarData"]["points"]]
                    out[p].append((msg.logMonoTime, pts))
    return out, ifaces, last_t, reset


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rlogs", nargs="+", type=Path)
    ap.add_argument("--openpilot", type=Path, required=True)
    ap.add_argument("--mpc-shadow", type=Path, default=None, help="dir from build_long_mpc_shadow.py (unbuilt checkouts)")
    ap.add_argument("--profiles", nargs="+", default=["raw", "openpilot"], choices=list(PROFILES))
    ap.add_argument("--fingerprint", default="TOYOTA_RAV4_TSS2_2022")
    ap.add_argument("--force-engaged", action="store_true", help="force longControlState=pid so every tick is scored as engaged")
    ap.add_argument("--out", type=Path, default=Path("replay_out"))
    args = ap.parse_args()

    if args.mpc_shadow is not None:
        import openpilot.selfdrive.controls.lib as lib  # type: ignore
        lib.__path__.insert(0, str(args.mpc_shadow.resolve()))
    from opendbc.car.structs import car  # type: ignore
    from opendbc.car.toyota.interface import CarInterface  # type: ignore
    from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner  # type: ignore
    from openpilot.selfdrive.controls.radard import RadarD  # type: ignore
    from openpilot.tools.lib.logreader import LogReader  # type: ignore

    def radar_data(points):
        rd = car.RadarData.new_message()
        arr = rd.init("points", len(points))
        for p, (tid, d, y, v) in zip(arr, points):
            p.trackId, p.dRel, p.yRel, p.vRel = tid, d, y, v
        return rd

    CP = CarInterface.get_non_essential_params(args.fingerprint)
    CP.openpilotLongitudinalControl = True
    names = ["vision"] + args.profiles
    empty = radar_data([])
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    ifaces = {p: Ars510NativeRadarInterface(PROFILES[p]) for p in args.profiles}
    last_t, pipes = None, None
    for rlog in args.rlogs:
        tracks, ifaces, last_t, reset = radar_tracks(LogReader, rlog, ifaces, last_t)
        if pipes is None or reset:  # first rlog, or a CAN gap: start the consumer fresh as well
            pipes = {p: (RadarD(CP.radarDelay), LongitudinalPlanner(CP)) for p in names}
            sm, latest = FakeSM(), {p: empty for p in names}
        ptr = {p: 0 for p in tracks}
        for msg in LogReader(str(rlog), sort_by_time=True):
            w, t = msg.which(), msg.logMonoTime
            for p, recs in tracks.items():
                while ptr[p] < len(recs) and recs[ptr[p]][0] <= t:
                    latest[p] = radar_data(recs[ptr[p]][1])
                    ptr[p] += 1
            if w in SM_KEYS:
                val = getattr(msg, w)
                if w == "controlsState" and args.force_engaged:
                    val = val.as_builder()
                    val.longControlState = "pid"
                sm.put(w, val, t)
            elif w == "modelV2":
                sm.put("modelV2", msg.modelV2, t)
                if not all(k in sm.data for k in SM_KEYS):
                    continue
                cs = sm["carState"].as_builder()
                cs.vCruise = float(cs.cruiseState.speed) * 3.6 if cs.cruiseState.speed > 0 else (100.0 if args.force_engaged else 255.0)
                row = {"segment": rlog.parent.name, "t_s": round(t / 1e9, 3), "v_ego": round(cs.vEgo, 3),
                       "engaged": int(str(sm["controlsState"].longControlState) != "off")}
                for p, (rd, lp) in pipes.items():
                    rd.update(sm, latest[p])
                    lp.update({"carState": cs, "controlsState": sm["controlsState"], "selfdriveState": sm["selfdriveState"],
                               "vehicleParameters": sm["vehicleParameters"], "carControl": sm["carControl"], "modelV2": msg.modelV2,
                               "radarState": rd.radar_state})
                    l1 = rd.radar_state.leadOne
                    row.update({f"{p}_aTarget": round(float(lp.output_a_target), 4), f"{p}_fcw": int(lp.fcw),
                                f"{p}_lead_radar": int(l1.radar), f"{p}_lead_trackId": int(l1.radarTrackId) if l1.radar else -1,
                                f"{p}_lead_dRel": round(l1.dRel, 2), f"{p}_lead_vLead": round(l1.vLead, 2)})
                rows.append(row)
        print(rlog, "ticks so far", len(rows), flush=True)

    with gzip.open(args.out / "ticks.csv.gz", "wt", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)

    summary = {"ticks": len(rows), "engaged_ticks": sum(r["engaged"] for r in rows), "profiles": {}}
    for p in names:
        s = {"fcw_ticks": sum(r[f"{p}_fcw"] for r in rows if r["engaged"])}
        if p != "vision":
            eps, cur = [], None
            for r in rows:
                hit = r["engaged"] and r[f"{p}_aTarget"] <= -1.0 and r["vision_aTarget"] >= -0.3
                if hit and cur is not None and r["t_s"] - cur["end"] <= 1.0:
                    cur["end"] = r["t_s"]
                    cur["min_aTarget"] = min(cur["min_aTarget"], r[f"{p}_aTarget"])
                elif hit:
                    cur = {"segment": r["segment"], "start": r["t_s"], "end": r["t_s"], "min_aTarget": r[f"{p}_aTarget"],
                           "radar_led": bool(r[f"{p}_lead_radar"]), "lead_dRel": r[f"{p}_lead_dRel"]}
                    eps.append(cur)
            s["native_only_braking_episodes"] = eps
            s["episodes_per_engaged_hour"] = round(len(eps) / max(summary["engaged_ticks"] / 20.0 / 3600.0, 1e-9), 2)
        summary["profiles"][p] = s
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({p: {k: v for k, v in s.items() if k != "native_only_braking_episodes"} for p, s in summary["profiles"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
