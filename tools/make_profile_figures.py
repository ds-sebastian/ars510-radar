#!/usr/bin/env python3
"""Figures for the install profiles, decoded from the bundled CAN samples.

    python tools/make_profile_figures.py      # writes docs/img/analysis/profile_comparison.png, layer_staircase.png, acc_sender_clock.png

Every panel runs ars510.Ars510NativeRadarInterface on data/sample/*.csv.gz and plots the in-lane lead (|yRel| < 1.8 m,
nearest) as published, so the figures can be regenerated from the repository alone.
"""
from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ars510 import FUSED_CONFIG, OPENPILOT_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.support import parse_acc_target_vrel  # noqa: E402

OUT = REPO / "docs" / "img" / "analysis"
SAMPLE = REPO / "data" / "sample"
INK, INK2, GRID, SURFACE = "#1d1d1b", "#5b5a55", "#e6e5df", "#fbfaf7"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
S5 = "#e87ba4"
GRAY = "#a9a8a2"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 10.5, "axes.labelsize": 9.5,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.8, "font.size": 9.5,
})


def frames(name: str):
    with gzip.open(SAMPLE / name, "rt") as f:
        for r in csv.DictReader(f):
            yield float(r["t_s"]), int(r["bus"]), int(r["address"], 16), bytes.fromhex(r["data_hex"])


def lead(name, cfg) -> dict:
    """Published in-lane lead per radar cycle, plus the radar's ACC target closing speed when present."""
    radar = Ars510NativeRadarInterface(cfg)
    out = {"t": [], "v": [], "d": [], "acc_t": [], "acc_v": []}
    for t, bus, addr, data in (frames(name) if isinstance(name, str) else name()):
        if bus == 1 and addr == 0x235 and len(data) == 8 and data[1] & 4:
            v = parse_acc_target_vrel(data)
            if v is not None:
                out["acc_t"].append(t); out["acc_v"].append(v)
        res = radar.update_frame(t, bus, addr, data)
        if not res:
            continue
        pts = [p for p in res["radarData"]["points"] if abs(p["yRel"]) < 1.8 and p["vRel"] == p["vRel"]]
        if pts:
            p = min(pts, key=lambda p: p["dRel"])
            out["t"].append(res["time_s"]); out["v"].append(p["vRel"]); out["d"].append(p["dRel"])
    return out


STOCK = OPENPILOT_CONFIG


def profiles_figure() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2), sharex="col")
    for col, (name, title) in enumerate((("highway_vrel_excursion_25s.csv.gz", "Drive A: settled lead, ~1 s excursion"),
                                         ("highway_acc_anchor_24s.csv.gz", "Drive E: excursion that drags the range"))):
        runs = {lab: lead(name, cfg) for lab, cfg in (("raw", STOCK), ("fused", FUSED_CONFIG))}
        av, ad = axes[0, col], axes[1, col]
        if runs["raw"]["acc_t"]:
            av.plot(runs["raw"]["acc_t"], runs["raw"]["acc_v"], color=INK, lw=1.0, ls="--", label="radar's ACC target (0x235)")
        for lab, color in (("raw", GRAY), ("fused", S3)):
            r = runs[lab]
            av.plot(r["t"], r["v"], color=color, label=lab)
            ad.plot(r["t"], r["d"], color=color, label=lab)
        av.set_title(title); av.set_ylabel("lead vRel (m/s)"); ad.set_ylabel("lead dRel (m)"); ad.set_xlabel("time (s)")
        av.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(OUT / "profile_comparison.png", dpi=130); plt.close(fig)


def staircase_figure() -> None:
    import json
    d = json.loads((REPO / "data/analysis/summaries/layer_ablation.json").read_text())["cumulative_heldout"]
    import textwrap
    fused = json.loads((REPO / "data/analysis/summaries/fused_filter.json").read_text())["replay_34_drives"]["fused"]
    labels = [textwrap.fill(x["step"], 18) for x in d] + [textwrap.fill("raw + range fusion + one Kalman filter (= fused, default)", 18)]
    vals = [x["hard_ticks"] for x in d] + [fused["heldout_hard_ticks"]]
    colors = [GRAY, GRAY, S1, S1, S1, S1, S2, S3]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    xs = list(range(len(vals) - 1)) + [len(vals) - 0.4]  # the fused bar stands apart: it replaces steps 3-7
    bars = ax.bar(xs, vals, color=colors)
    ax.axvline(len(vals) - 1.2, color=GRID, lw=1.2)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, str(v), ha="center", fontsize=9, color=INK)
    ax.set_xticks(xs, labels, fontsize=8)
    ax.set_ylabel("hard radar-only braking ticks")
    ax.set_title("Each layer added in turn, and fused instead of the layers: 20 held-out routes, 4.6 h")
    fig.tight_layout(); fig.savefig(OUT / "layer_staircase.png", dpi=130); plt.close(fig)


def clock_figure() -> None:
    import json
    d = json.loads((REPO / "data/analysis/summaries/acc_sender_clock.json").read_text())["drive_E_minute_phase_vs_radar_0x190_ms"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    style = {"0x235 (ACC target)": (S2, "-"), "0x191 (radar control)": (S1, "--"), "0x180 (camera control)": (GRAY, "-"),
             "0x240 (camera)": (INK2, ":")}
    for name, vals in d.items():
        c, ls = style.get(name, (INK, "-"))
        ax.step(range(len(vals)), vals, where="mid", color=c, ls=ls, label=name)
    ax.set_xlabel("minute of drive E"); ax.set_ylabel("phase vs radar 0x190 (ms)")
    ax.set_title("Who sends 0x235? It keeps the radar's clock; camera messages drift away")
    ax.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(OUT / "acc_sender_clock.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    profiles_figure()
    staircase_figure()
    clock_figure()
    print("wrote", OUT / "profile_comparison.png", OUT / "layer_staircase.png", OUT / "acc_sender_clock.png")
