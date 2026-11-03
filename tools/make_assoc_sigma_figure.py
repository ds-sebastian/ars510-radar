#!/usr/bin/env python3
"""Figure for docs/03: how the published range and speed sigma codes move on one track when the camera association changes at night.

    python tools/make_assoc_sigma_figure.py      # writes docs/img/analysis/camera_assoc_sigma.png

Every number comes from data/analysis/summaries/camera_assoc_sigma.json. Needs only matplotlib.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SUM = REPO / "data" / "analysis" / "summaries"
OUT = REPO / "docs" / "img" / "analysis"

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2 = "#2a78d6", "#eb6834"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9.5,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8.5, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9.5,
})


def main() -> None:
    d = json.loads((SUM / "camera_assoc_sigma.json").read_text())
    rows = [r for r in d["bands"] if r["state"] == "night"]
    bands = ["30-50", "50-80", "80-130"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.7), sharey=True)
    for ax, key, title in ((axes[0], "range_sigma", "range sigma 224|7"), (axes[1], "speed_sigma", "speed sigma 240|7")):
        ax.axhline(0, color="#b9b8b2", lw=1)
        for kind, color, marker, off, name in (("onset", S1, "o", -0.08, "camera association starts"), ("loss", S2, "s", 0.08, "camera association ends")):
            for i, b in enumerate(bands):
                r = next(x for x in rows if x["kind"] == kind and x["range_m"] == b)
                v = r[key]
                ax.errorbar(i + off, v["step"], yerr=[[v["step"] - v["ci"][0]], [v["ci"][1] - v["step"]]], color=color, marker=marker, ms=8, mec=SURFACE, mew=2, lw=2, capsize=0,
                            label=name if i == 0 else None)
        ax.set_xticks(range(3), [f"{b} m" for b in bands]); ax.set_xlim(-0.5, 2.5); ax.set_title(title, loc="left"); ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("code counts, after minus before"); axes[0].legend(loc="upper left")
    n = sum(r["events"] for r in rows)
    fig.text(0.01, 0.01, f"Night, {n} events on the owner's car and the second car: same track, range unchanged within 1.5 m. Bars: 95 % interval over routes.\n"
             "Published codes only: this shows the radar's stated uncertainty moving, not a measured accuracy gain.", fontsize=8, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.11, 1, 1))
    fig.savefig(OUT / "camera_assoc_sigma.png", dpi=130)


if __name__ == "__main__":
    main()
