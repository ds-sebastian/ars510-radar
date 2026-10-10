#!/usr/bin/env python3
"""Replay prepared drives through each fork's own radard and MPC lead handling, one radar profile at a time.

  python tools/fork_lead/fork_replay.py --sunnypilot ~/sunnypilot --frogpilot ~/frogpilot --starpilot ~/starpilot \\
      --out replay_out route_dir_1 route_dir_2          # route dirs from prepare_route.py

Per route, fork configuration and profile it writes <out>/<route>__<config>__<profile>.npz with one row per model
tick (20 Hz). Configurations: sunnypilot, frogpilot-hf (FrogPilot with Human Following on, its default),
frogpilot (Human Following off), starpilot. Profiles: vision (no radar points), raw, fused, acc (the radar's ACC
target alone: the reference, the radar's own ACC tracker). Forks you do not pass are skipped. At most two jobs run at once (--jobs).

This is open loop and uses a proxy for the planner (see forksim.py). Read the numbers as comparisons between forks
and profiles, not as what the planner would request.
"""
from __future__ import annotations

import argparse
import csv
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forksim import MpcLead, RadarFork, brake_demand, nominal_demand  # noqa: E402

PROFILES = ("vision", "raw", "fused", "acc")
CONFIGS = {  # name -> (fork, human_following)
    "sunnypilot": ("sunnypilot", False),
    "frogpilot-hf": ("frogpilot", True),
    "frogpilot": ("frogpilot", False),
    "starpilot": ("starpilot", False),
}
COLUMNS = ("t vego aego status radar dRel yRel vLead aLeadK aLeadTau track vision_prob status2 demand nominal "
           "v0 x0 legacy filt_v filt_a").split()


def load_points(route: Path, profile: str):
    recs: dict[float, list] = {}
    if profile != "vision":
        with open(route / f"pts_{profile}.csv") as fh:
            for r in csv.DictReader(fh):
                recs.setdefault(float(r["time_s"]), []).append(
                    (int(r["trackId"]), float(r["dRel"]), float(r["yRel"]), float(r["vRel"])))
    return recs, np.array(sorted(recs))


def replay(route: Path, config: str, fork_path: str, profile: str) -> np.ndarray:
    fork, human_following = CONFIGS[config]
    with open(route / "ticks.pkl", "rb") as fh:
        ticks = pickle.load(fh)
    recs, times = load_points(route, profile)
    rf = RadarFork(fork, fork_path)
    mpc = MpcLead(fork, fork_path, human_following)
    mpc.toggles.lead_detection_probability = rf.toggles.lead_detection_probability
    rows = []
    for tk in ticks:
        pts = []
        if len(times):
            i = np.searchsorted(times, tk["t"], side="right") - 1
            if i >= 0 and tk["t"] - times[i] < 0.12:
                pts = recs[times[i]]
        l1, l2 = rf.step(tk, pts)
        v, a = tk["car"]["vEgo"], tk["car"]["aEgo"]
        dem = nom = legacy = fv = fa = x0 = v0 = np.nan
        dem = nom = 0.0
        if v > 1.0 and l1["status"]:
            xv = mpc.lead_xv(v, a, l1, tk["leads"][0])
            dem, nom = brake_demand(xv, v), nominal_demand(xv, v)
            x0, v0 = xv[0]
            if fork == "starpilot":
                legacy = 0.0 if mpc.model_path_used else 1.0
                fv, fa = mpc.filters
        rows.append((tk["t"], v, a, l1["status"], l1["radar"], l1.get("dRel", np.nan), l1.get("yRel", np.nan),
                     l1.get("vLead", np.nan), l1.get("aLeadK", np.nan), l1.get("aLeadTau", np.nan),
                     l1.get("radarTrackId", -1), tk["leads"][0]["prob"], l2["status"], dem, nom, v0, x0, legacy, fv, fa))
    return np.array(rows, dtype=float)


def job(args):
    route, config, fork_path, profile, out = args
    t0 = time.time()
    data = replay(Path(route), config, fork_path, profile)
    np.savez(out, cols=np.array(COLUMNS), data=data)
    return f"{Path(route).name} {config} {profile}: {len(data)} ticks in {time.time() - t0:.0f}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for fork in ("sunnypilot", "frogpilot", "starpilot"):
        ap.add_argument(f"--{fork}", type=Path, help=f"{fork} checkout")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=2, help="parallel jobs (default and advised maximum: 2)")
    ap.add_argument("routes", nargs="+", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    work = []
    for route in args.routes:
        for config, (fork, _) in CONFIGS.items():
            path = getattr(args, fork)
            if path is None:
                continue
            for profile in PROFILES:
                out = args.out / f"{route.name}__{config}__{profile}.npz"
                if not out.exists():
                    work.append((str(route), config, str(path), profile, str(out)))
    with Pool(min(args.jobs, 2)) as pool:
        for line in pool.imap_unordered(job, work):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
