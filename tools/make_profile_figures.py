#!/usr/bin/env python3
"""Figures for the install profiles and each smoothing layer, decoded from the bundled CAN samples.

    python tools/make_profile_figures.py      # writes docs/img/analysis/profile_*.png and layer_*.png

Every panel runs ars510.Ars510NativeRadarInterface on data/sample/*.csv.gz and plots the in-lane lead (|yRel| < 1.8 m,
nearest) as published, so the figures can be regenerated from the repository alone.
"""
from __future__ import annotations

import csv
import gzip
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ars510 import ANCHOR_CONFIG, OPENPILOT_CONFIG, STEADY_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.constants import ID80_IDLE_SLOT  # noqa: E402
from ars510.objects import encode_slot  # noqa: E402
from ars510.support import parse_acc_target_vrel  # noqa: E402
import zlib  # noqa: E402

OUT = REPO / "docs" / "img" / "analysis"
SAMPLE = REPO / "data" / "sample"
INK, INK2, GRID, SURFACE = "#1d1d1b", "#5b5a55", "#e6e5df", "#fbfaf7"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
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


def synthetic(kind: str):
    """Synthetic CAN for effects the samples do not show: 'glitch' (one-record velocity spike on a settled lead)
    and 'far' (a new track appearing at 90 m)."""
    def record(slots):
        rec = bytearray(742); rec[0] = 0xE4
        for i in range(20):
            rec[17 + 36 * i:17 + 36 * (i + 1)] = slots.get(i, ID80_IDLE_SLOT)
        rec[737:741] = (zlib.crc32(bytes(rec[1:737])) & 0xFFFFFFFF).to_bytes(4, "little")
        return bytes(rec)
    for k in range(200):
        t = 0.06 * k
        yield t, 0, 0xB4, bytes(5) + round(25.0 * 3.6 / 0.01).to_bytes(2, "big") + b"\x00"
        if kind == "glitch":
            vg = 25.0 - 0.5 + (12.0 if k == 100 else 0.0)
            slot = encode_slot(long_dist=round(160 + 50 * 16), lat_dist_left=2048, long_vel_over_ground=round(510.5 + vg / 0.15),
                               age_cycles=min(126, 80 + k))
        else:
            slot = encode_slot(long_dist=round(160 + (90 - 0.05 * k) * 16), lat_dist_left=2048,
                               long_vel_over_ground=round(510.5 + 24.2 / 0.15), age_cycles=min(126, 1 + k))
        rec = record({0: slot})
        yield t + 0.002, 1, 0x80, bytes([0x12]) + rec[0:7]
        for j in range(1, 106):
            yield t + 0.002 + 0.0001 * j, 1, 0x80, bytes([0x20]) + rec[7 * j:7 * j + 7]


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
K4_RANGE = replace(STOCK, range_fusion_gain=0.1)
K4 = replace(K4_RANGE, vrel_smooth_far_tau_s=1.0)
K4_JUMP = replace(K4, vjump_thresh_mps=8.0)
K4_JUMP_RAMP = replace(K4_JUMP, ramp_up_mps2=4.0, ramp_down_mps2=6.0)


def profiles_figure() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2), sharex="col")
    for col, (name, title) in enumerate((("highway_vrel_excursion_25s.csv.gz", "Drive A: settled lead, ~1 s excursion"),
                                         ("highway_acc_anchor_24s.csv.gz", "Drive E: excursion that drags the range"))):
        runs = {lab: lead(name, cfg) for lab, cfg in (("stock", STOCK), ("steady", STEADY_CONFIG), ("anchor", ANCHOR_CONFIG))}
        av, ad = axes[0, col], axes[1, col]
        if runs["stock"]["acc_t"]:
            av.plot(runs["stock"]["acc_t"], runs["stock"]["acc_v"], color=INK, lw=1.0, ls="--", label="radar's ACC target (0x235)")
        for lab, color in (("stock", GRAY), ("steady", S1), ("anchor", S2)):
            r = runs[lab]
            av.plot(r["t"], r["v"], color=color, label=lab)
            ad.plot(r["t"], r["d"], color=color, label=lab)
        av.set_title(title); av.set_ylabel("lead vRel (m/s)"); ad.set_ylabel("lead dRel (m)"); ad.set_xlabel("time (s)")
        av.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(OUT / "profile_comparison.png", dpi=130); plt.close(fig)


def layers_figure() -> None:
    exc, fol, anc = "highway_vrel_excursion_25s.csv.gz", "highway_following_30s.csv.gz", "highway_acc_anchor_24s.csv.gz"
    glitch, far = (lambda: synthetic("glitch")), (lambda: synthetic("far"))
    panels = [
        (fol, "d", [("stock", STOCK, GRAY), ("+ range fusion (gain 0.1)", K4_RANGE, S1)],
         "1  Range fusion (drive A)", "lead dRel (m)", None),
        (fol, "v", [("stock", STOCK, GRAY), ("+ far smoothing (tau 0-1 s)", K4, S1)],
         "2  Far smoothing (drive A)", "lead vRel (m/s)", None),
        (glitch, "v", [("without", K4, GRAY), ("+ 8 m/s jump guard", K4_JUMP, S3)],
         "3  Jump guard (synthetic one-record spike)", "lead vRel (m/s)", None),
        (exc, "v", [("K4 + jump guard", K4_JUMP, GRAY), ("+ ramp limiter (+4 / -6 m/s²)", K4_JUMP_RAMP, S4)],
         "4  Ramp limiter (drive A excursion)", "lead vRel (m/s)", None),
        (far, "d", [("stock: published from age 60", STOCK, GRAY), ("steady: from age 100 above 70 m", STEADY_CONFIG, S1)],
         "5  Far-track settling (synthetic new track at 90 m)", "dRel (m)", (0, 12)),
        (anc, "v", [("steady", STEADY_CONFIG, S1), ("anchor: within ±3 m/s of the ACC target", ANCHOR_CONFIG, S2)],
         "6  ACC anchor (drive E excursion)", "lead vRel (m/s)", (14, 19.5)),
    ]
    fig, axes = plt.subplots(3, 2, figsize=(11, 9.4))
    for ax, (name, key, runs, title, ylabel, xlim) in zip(axes.flat, panels):
        for lab, cfg, color in runs:
            r = lead(name, cfg)
            ax.plot(r["t"], r[key], color=color, label=lab)
            if key == "v" and r["acc_t"] and lab.startswith("anchor"):
                ax.plot(r["acc_t"], r["acc_v"], color=INK, lw=1.0, ls="--", label="radar's ACC target")
        if xlim:
            ax.set_xlim(*xlim)
        ax.set_title(title); ax.set_ylabel(ylabel); ax.set_xlabel("time (s)"); ax.legend(loc="best")
    fig.tight_layout(); fig.savefig(OUT / "layer_examples.png", dpi=130); plt.close(fig)


def staircase_figure() -> None:
    import json
    d = json.loads((REPO / "data/analysis/summaries/layer_ablation.json").read_text())["cumulative_heldout"]
    import textwrap
    labels = [textwrap.fill(x["step"], 18) for x in d]
    vals = [x["hard_ticks"] for x in d]
    colors = [GRAY, GRAY, S1, S1, S1, S1, S2]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    bars = ax.bar(range(len(vals)), vals, color=colors)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, str(v), ha="center", fontsize=9, color=INK)
    ax.set_xticks(range(len(vals)), labels, fontsize=8)
    ax.set_ylabel("hard radar-only braking ticks")
    ax.set_title("Each layer added in turn: 20 held-out routes, 4.6 h (far settling's gain is on other drives)")
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
    layers_figure()
    staircase_figure()
    clock_figure()
    print("wrote", OUT / "profile_comparison.png", OUT / "layer_examples.png")
