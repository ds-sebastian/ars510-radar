#!/usr/bin/env python3
"""Regenerate docs/img/vrel_excursion_sample.png from the bundled CAN sample (needs matplotlib)."""
from __future__ import annotations

import csv
import gzip
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ars510 import ALL_TRACKS_CONFIG, Ars510NativeRadarInterface  # noqa: E402

IMG = REPO / "docs" / "img"


def excursion_figure() -> None:
    iface = Ars510NativeRadarInterface(ALL_TRACKS_CONFIG)
    rows = csv.DictReader(gzip.open(REPO / "data/sample/highway_vrel_excursion_25s.csv.gz", "rt"))
    frames = ((float(r["t_s"]), int(r["bus"]), int(r["address"], 0), bytes.fromhex(r["data_hex"])) for r in rows)
    tr = defaultdict(list)
    for p in iface.update_many(frames):
        for pt in p["radarData"]["points"]:
            if pt["age"] >= 60 and abs(pt["yRel"]) < 1.8 and pt["dRel"] < 80:
                tr[pt["trackId"]].append((p["time_s"], pt["dRel"], pt["vRel"]))
    tid, pts = max(tr.items(), key=lambda kv: len(kv[1]))
    t = [a for a, _, _ in pts]
    d = [b for _, b, _ in pts]
    v = [c for _, _, c in pts]
    slope = [float("nan")] * len(t)
    for i in range(len(t)):  # centred 4 s least-squares range slope, for reference only
        idx = [j for j in range(len(t)) if abs(t[j] - t[i]) <= 2.0]
        if len(idx) > 10:
            mt = sum(t[j] for j in idx) / len(idx)
            md = sum(d[j] for j in idx) / len(idx)
            den = sum((t[j] - mt) ** 2 for j in idx)
            slope[i] = sum((t[j] - mt) * (d[j] - md) for j in idx) / den
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.5), sharex=True)
    a1.plot(t, d, ".", ms=2)
    a1.set_ylabel("dRel (m)")
    a1.set_title(f"Settled in-lane lead (age 126) on the highway: the range keeps opening while vRel dips")
    a2.plot(t, v, lw=1, label="native vRel (over-ground - ego)")
    a2.plot(t, slope, lw=1.5, label="4 s range slope (noisy reference)")
    a2.axhline(0, color="k", lw=0.5)
    a2.set_ylabel("m/s")
    a2.set_xlabel("time (s)")
    a2.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(IMG / "vrel_excursion_sample.png", dpi=130)


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    excursion_figure()
    print("wrote", sorted(p.name for p in IMG.glob("*.png")))
