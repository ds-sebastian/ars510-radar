#!/usr/bin/env python3
"""Figures for how the radar's tracker picks cars (docs/05): the summary pair and the ACC target.

    python tools/make_tracker_selection_figures.py      # writes docs/img/analysis/summary_selection.png, acc_corridor.png

summary_selection.png: which key the radar ranks summary cars by, and who replaces whom (summary_tracker_selection.json).
acc_corridor.png: how often the ACC target lies inside a corridor around each path definition (acc_corridor.json).
Needs only matplotlib; every number is read from data/analysis/summaries/.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SUM = REPO / "data" / "analysis" / "summaries"
OUT = REPO / "docs" / "img" / "analysis"

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9.5,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8.5, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9.5,
})


def load(name: str) -> dict:
    return json.loads((SUM / f"{name}.json").read_text())


def save(fig, name: str, note: str) -> None:
    fig.text(0.01, -0.01, note, fontsize=7.5, color=INK2, ha="left", va="top", wrap=True)
    fig.savefig(OUT / f"{name}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def summary_selection() -> None:
    D = load("summary_tracker_selection")
    keys = D["rival_pairs"]["keys"]
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.3), gridspec_kw={"width_ratios": [1.25, 1]})
    a = ax[0]
    y = np.arange(len(keys))[::-1]
    h = 0.36
    a.barh(y + h / 2, D["rival_pairs"]["second_2"], h, color=S1, label="second car, held out (1)")
    a.barh(y - h / 2, D["rival_pairs"]["second_3"], h, color=S3, label="second car, held out (2)")
    a.axvline(0.5, color=INK2, lw=0.8, ls=":")
    a.set_yticks(y, keys)
    a.set_xlim(0.3, 1.0)
    a.set_xlabel("share of rival pairs in which the displayed car has the smaller key")
    a.set_title("Range ranks the summary pair; no other key does")
    a.legend(loc="lower right")
    a = ax[1]
    bands = D["displacement_by_leaver_range"]["bands_m"]
    share = D["displacement_by_leaver_range"]["newcomer_farther"]
    n = D["displacement_by_leaver_range"]["events"]
    x = np.arange(len(bands))
    a.bar(x, share, 0.62, color=S2)
    for xi, s, k in zip(x, share, n):
        a.text(xi, s + 0.02, f"{100 * s:.0f} %\nn={k}", ha="center", fontsize=8)
    a.set_xticks(x, bands)
    a.set_ylim(0, 1.18)
    a.set_xlabel("range of the car that leaves the full pair (m)")
    a.set_ylabel("newcomer is farther than the leaver")
    a.set_title("A nearer car passing alongside frees its place")
    fig.tight_layout()
    save(fig, "summary_selection", "Owner car and second car, radar-published state with the object list linked by association; left: strictly eligible "
         "rival pairs, two held-out sets; right: displacements in a full pair, four sets pooled. Numbers: data/analysis/summaries/summary_tracker_selection.json.")


def acc_corridor() -> None:
    D = load("acc_corridor")
    sets = ["owner", "second_1", "second_2", "second_3"]
    names = ["owner car", "second car, set 1", "second car, set 2", "second car, set 3"]
    defs = [("radar_path", "radar's own path (0x33E byte 5)", S1), ("yaw_rate_path", "path from yaw rate", S4),
            ("raw_lateral", "raw lateral offset", S2)]
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.2), gridspec_kw={"width_ratios": [1.5, 1]})
    a = ax[0]
    x = np.arange(len(sets))
    w = 0.26
    for i, (k, lab, col) in enumerate(defs):
        a.bar(x + (i - 1) * w, [D["containment_2_5_m"][k][s] for s in sets], w, color=col, label=lab)
    a.plot(x + 0 * w, [D["nearest_corridor_candidate_is_target"][s] for s in sets], "k_", ms=24, mew=2,
           label="nearest corridor candidate is the target")
    a.set_xticks(x, names)
    a.set_ylim(0.6, 1.12)
    a.set_ylabel("ACC acquisitions with the target inside 2.5 m of the path")
    a.set_title("The ACC target comes from a corridor around the radar's path")
    a.legend(loc="upper center", ncol=2, fontsize=8)
    a = ax[1]
    labs = ["corridor rule\n(smallest |y_path|)", "nearest mover\n(no corridor)"]
    vals = [(D["corridor_rule_free_running"]["second_2"] + D["corridor_rule_free_running"]["second_3"]) / 2,
            sum(D["corridor_rule_free_running"]["nearest_mover_without_corridor"]) / 2]
    a.bar([0, 1], vals, 0.55, color=[S1, S2])
    for xi, v in zip([0, 1], vals):
        a.text(xi, v + 0.02, f"{100 * v:.0f} %", ha="center", fontsize=9)
    a.set_xticks([0, 1], labs)
    a.set_ylim(0, 1.1)
    a.set_ylabel("cycles on which it names the radar's ACC list track")
    a.set_title("Free-running rule against the radar's choice")
    fig.tight_layout()
    save(fig, "acc_corridor", "New ACC acquisitions with a linked object-list track and a valid radar path: 192 / 57 / 261 / 333 events; right: mean of the two held-out "
         "second-car sets. Radar-witness agreement, not a physical reference. Numbers: data/analysis/summaries/acc_corridor.json.")


if __name__ == "__main__":
    summary_selection()
    acc_corridor()
