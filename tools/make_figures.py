#!/usr/bin/env python3
"""Regenerate docs/img/*.png from data in this repo (needs matplotlib)."""
from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ars510 import RAW_CONFIG, Ars510NativeRadarInterface  # noqa: E402

IMG = REPO / "docs" / "img"


def flip_rate_figure() -> None:
    bm = json.loads((REPO / "data/reference/slot_bit_map.json").read_text())
    rate = bm["slot_bit_flip_rate"]
    fig, ax = plt.subplots(figsize=(13, 3.6))
    ax.bar(range(len(rate)), rate, width=1.0, color="#555")
    colors = {"AGE": "#e377c2", "DREL": "#1f77b4", "YREL_LEFT": "#2ca02c", "VLONG_OVER_GROUND": "#d62728",
              "VLAT_OVER_GROUND_PROV": "#ff7f0e", "ALONG_LIKE_84": "#9467bd", "UNK_96": "#8c564b"}
    for f in bm["slot_fields"]:
        if f["name"] in colors:
            ax.axvspan(f["start"] - 0.5, f["start"] + f["len"] - 0.5, color=colors[f["name"]], alpha=0.25, lw=0)
            short = {"VLONG_OVER_GROUND": "VLONG", "VLAT_OVER_GROUND_PROV": "VLAT", "ALONG_LIKE_84": "ACCEL?", "YREL_LEFT": "YREL"}.get(f["name"], f["name"])
            ax.text(f["start"] + f["len"] / 2, max(rate) * 1.02, f"{short}\n{f['start']}|{f['len']}", ha="center", va="bottom", fontsize=8)
    ax.set_xlim(-1, 150)
    ax.set_ylim(0, max(rate) * 1.35)
    ax.set_xlabel("slot bit (little-endian: bit 0 = LSB of slot byte 0)")
    ax.set_ylabel("flip rate per cycle")
    ax.set_title("0x80 object slot: per-bit flip rate between consecutive cycles of the same track (first 150 of 288 bits)")
    fig.tight_layout()
    fig.savefig(IMG / "slot_bit_flip_rate.png", dpi=130)


def excursion_figure() -> None:
    iface = Ars510NativeRadarInterface(RAW_CONFIG)
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
    flip_rate_figure()
    excursion_figure()
    print("wrote", sorted(p.name for p in IMG.glob("*.png")))
