#!/usr/bin/env python3
"""Synthetic scenarios with a known truth, through each fork's own radard and MPC lead handling.

  python tools/fork_lead/fork_synth.py --sunnypilot ~/sunnypilot --frogpilot ~/frogpilot --starpilot ~/starpilot \\
      --template route_dir [--json synth.json]

A tick from a prepared drive supplies lane lines and the vision model's uncertainties; everything else is synthetic.
Ego drives at a constant 30 m/s (open loop). Demand is the proxy of forksim.py (m/s^2).

  E1  A lead pace-matched to the ego, with a false closing speed in the radar's vRel: ramps up over 1.5 s, holds 1 s,
      decays over 2 s (a synthetic stand-in for the far-range excursions of docs/07, which ramp up over about 1 s).
      Reported: the extra demand over the same fork without the error. StarPilot's lead filters start warm (at the lead's speed).
  E2  A radar-only, in-lane, moving object slower than the ego, with no vision lead (the camera sees nothing):
      does the fork take it as the lead?
"""
from __future__ import annotations

import argparse
import copy
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forksim import MpcLead, RadarFork, brake_demand, nominal_demand  # noqa: E402

DT = 0.05
V_EGO = 30.0
CONFIGS = {"sunnypilot": ("sunnypilot", False), "frogpilot-hf": ("frogpilot", True),
           "frogpilot": ("frogpilot", False), "starpilot": ("starpilot", False)}


class Scenario:
    def __init__(self, template: dict):
        self.tpl = template

    def _lead(self, x, v_abs, y=0.0, prob=0.95):
        t = self.tpl["leads"][0]
        ks = np.arange(6) * 2.0
        return dict(prob=prob, x=list(x + v_abs * ks), y=[y] * 6, v=[v_abs] * 6, a=[0.0] * 6, xStd=t["xStd"], yStd=t["yStd"],
                    vStd=t["vStd"], aStd=t["aStd"])

    def tick(self, t: float, vision: dict | None) -> dict:
        tk = {k: copy.deepcopy(self.tpl[k]) for k in ("lanes", "pos_x_last", "lc_state", "lc_dir")}
        tk.update(t=t, model_v_ego=V_EGO, car=dict(vEgo=V_EGO, aEgo=0.0, standstill=False))
        empty = self._lead([0.0], 0.0, prob=0.02)
        tk["leads"] = [self._lead(vision["x0"], vision["v_abs"], prob=vision["prob"]) if vision else empty, empty]
        return tk

    def excursion(self, gap: float, err: float, duration: float = 25.0):
        def shape(t):
            t0, up, hold, down = 10.0, 1.5, 1.0, 2.0
            if t < t0: return 0.0
            if t < t0 + up: return err * (t - t0) / up
            if t < t0 + up + hold: return err
            return err * max(1 - (t - t0 - up - hold) / down, 0.0)
        return [(self.tick(t, dict(x0=gap + 1.52, v_abs=V_EGO, prob=0.95)), [(1, gap, 0.0, shape(t))])
                for t in np.arange(0, duration, DT)]

    def radar_only(self, v_lead: float, seconds: float, gap: float = 55.0, duration: float = 25.0):
        sc = []
        for t in np.arange(0, duration, DT):
            pts = [(7, gap + (v_lead - V_EGO) * (t - 10.0), 0.2, v_lead - V_EGO)] if 10.0 <= t < 10.0 + seconds else []
            sc.append((self.tick(t, None), pts))
        return sc


def run(scn: list, config: str, paths: dict) -> np.ndarray:
    fork, hf = CONFIGS[config]
    rf = RadarFork(fork, paths[fork])
    mpc = MpcLead(fork, paths[fork], hf)
    mpc.seed_filters(V_EGO, 0.0)
    out = []
    for tk, pts in scn:
        l1, _ = rf.step(tk, pts)
        xv = mpc.lead_xv(V_EGO, 0.0, l1, tk["leads"][0]) if l1["status"] else None
        out.append((tk["t"], l1["status"], l1["radar"], l1.get("vLead", np.nan), l1.get("aLeadK", np.nan),
                    brake_demand(xv, V_EGO) if xv is not None else 0.0,
                    nominal_demand(xv, V_EGO) if xv is not None else 0.0))
    return np.array(out, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for fork in ("sunnypilot", "frogpilot", "starpilot"):
        ap.add_argument(f"--{fork}", type=Path)
    ap.add_argument("--template", type=Path, required=True, help="a prepared drive (ticks.pkl) for lane lines")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    paths = {f: getattr(args, f) for f in ("sunnypilot", "frogpilot", "starpilot") if getattr(args, f)}
    ticks = pickle.load(open(args.template / "ticks.pkl", "rb"))
    tpl = next(t for t in ticks[2000:] if t["leads"][0]["prob"] > 0.95 and t["car"]["vEgo"] > 28)
    sc = Scenario(tpl)
    configs = [c for c, (f, _) in CONFIGS.items() if f in paths]
    res: dict = {}

    print("E1: false closing speed on a pace-matched lead; extra demand (m/s2) over the same fork without the error")
    print(f"  {'config':14s} {'gap m':>5s} {'error m/s':>9s} | {'peak aLeadK':>11s} {'extra demand':>12s} {'s >= 0.5':>8s}")
    res["E1_excursion"] = {}
    for gap in (45.0, 70.0):
        base = {c: run(sc.excursion(gap, 0.0), c, paths) for c in configs}
        for err in (-1.0, -2.0, -4.0):
            for c in configs:
                o = run(sc.excursion(gap, err), c, paths)
                m = (o[:, 0] >= 9.0) & (o[:, 0] <= 18.0)
                extra = (o[:, 5] - base[c][:, 5])[m]
                print(f"  {c:14s} {gap:5.0f} {err:9.1f} | {np.nanmin(o[m, 4]):11.2f} {extra.max():12.2f} {(extra >= 0.5).sum() * DT:8.2f}")
                res["E1_excursion"][f"{c}/gap{gap:.0f}/err{err:+.0f}"] = dict(
                    peak_aLeadK=round(float(np.nanmin(o[m, 4])), 2), extra_demand=round(float(extra.max()), 2),
                    seconds_ge_0p5=round(float((extra >= 0.5).sum() * DT), 2))

    print("\nE2: radar-only in-lane moving object, no vision lead; does the fork take it as the lead?")
    res["E2_radar_only_object"] = {}
    for v_lead, seconds in ((20.0, 1.5), (20.0, 3.0), (10.0, 3.0)):
        for c in configs:
            o = run(sc.radar_only(v_lead, seconds), c, paths)
            acc = o[(o[:, 0] >= 10.0) & (o[:, 1] == 1)]
            after = float(acc[0, 0] - 10.0) if len(acc) else None
            peak = float(acc[:, 6].max()) if len(acc) else 0.0
            print(f"  v_lead {v_lead:4.0f} m/s for {seconds:3.1f} s  {c:14s} taken as lead: {'yes, after %.2f s' % after if after is not None else 'no':18s} peak demand {peak:.2f}")
            res["E2_radar_only_object"][f"{c}/v{v_lead:.0f}/{seconds:.1f}s"] = dict(
                taken=after is not None, after_s=None if after is None else round(after, 2), peak_demand=round(peak, 2))
    if args.json:
        args.json.write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
