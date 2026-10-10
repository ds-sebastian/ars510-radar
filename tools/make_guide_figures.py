#!/usr/bin/env python3
"""Figures for docs/00_start_here.md (the parser in pictures).

    python tools/make_guide_figures.py      # writes docs/img/analysis/guide_*.png

guide_pipeline.png and guide_lead_guards.png are schematics with numbers from the summaries. guide_cases.png plots
data/analysis/lead_choice_cases.csv.gz: two road moments replayed through openpilot's planner with vision only, 2.1 and
2.3 (relative time, no route identifiers; 2.4 asks the same as 2.3 in both, lead_choice_guards.json). guide_road_stats.png plots data/analysis/summaries/road_v21.json;
guide_parts_ledger.png plots data/analysis/summaries/openpilot_file_parts.json; guide_oracle.png plots
data/analysis/summaries/oracle_reference.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from make_profile_figures import GRAY, GRID, INK, INK2, S1, S2, S3, S4, SURFACE  # noqa: E402,F401

OUT = REPO / "docs" / "img" / "analysis"
SUM = REPO / "data" / "analysis" / "summaries"
VIS, V21, V23 = "#7a5fb0", S2, S1  # validated together (dataviz validator, light surface)


def _box(ax, x, y, w, h, title, body, color):
  ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc="white", ec=color, lw=1.6))
  ax.add_patch(Rectangle((x, y + h - 0.07), w, 0.07, fc=color, ec="none"))
  ax.text(x + w / 2, y + h - 0.2, title, ha="center", va="center", fontsize=9.2, color=INK, weight="bold")
  ax.text(x + w / 2, y + (h - 0.3) / 2, body, ha="center", va="center", fontsize=7.6, color=INK2, linespacing=1.35)


def pipeline() -> None:
  """CAN frames to radard, one box per stage with its key numbers."""
  lv = json.loads((SUM / "lead_choice_guards.json").read_text())["radar_share_of_leads_beyond_60m"]
  stages = [
    ("1  Radar bus", "0x80 frames on bus 1\n106 frames = 1 record\nevery ~60 ms (16.7 Hz)", GRAY),
    ("2  Reassemble", "742-byte record\nCRC32 check\nbad records dropped", GRAY),
    ("3  Decode slots", "20 slots, ~2 objects\ndRel, yRel, ground speed,\nage, uncertainty 240|7", GRAY),
    ("4  Track IDs", "slot + age counting up\n= one radar track", GRAY),
    ("5  Radar's own tracker", "ACC target 0x235/0x237\nmatched to a track by position\n(range scale 0.4 x)", S4),
    ("6  Kalman speed filter", "one per track, 1 state\nσ = 0.045 m/s × 240|7\nACC target σ = 0.5 m/s", S3),
    ("7  Range", "velocity-aided, gain 0.1\nfollowed car: ACC distance", S3),
    ("8  Publish", "age ≥ 60 (~3.6 s)\nspeed σ ≤ 0.75 m/s\npath gate beyond 15 m", S1),
    ("9  openpilot", "RadarPoint(dRel, yRel, vRel)\n→ radard pairs with vision\n→ planner", INK2),
  ]
  fig, ax = plt.subplots(figsize=(13.5, 4.6)); ax.set_xlim(0, 13.5); ax.set_ylim(0, 4.6); ax.axis("off"); ax.grid(False)
  w, h = 2.7, 1.55
  pos = [(0.2 + i * 3.35, 2.75) for i in range(4)] + [(0.2 + i * 3.35, 0.45) for i in range(4, -1, -1)]
  pos = pos[:4] + [(13.5 - 0.2 - w - (i - 4) * 3.35 * 0 - 0, 0) for i in range(4, 5)]
  top = [(0.2 + i * 3.35, 2.75) for i in range(4)]
  bot = [(10.25 - i * 2.5, 0.45) for i in range(5)]
  wb = 2.25
  for (title, body, c), (x, y) in zip(stages[:4], top):
    _box(ax, x, y, w, h, title, body, c)
  for (title, body, c), (x, y) in zip(stages[4:], bot):
    _box(ax, x + 0.45, y, wb, h, title, body, c)
  for i in range(3):
    ax.add_patch(FancyArrowPatch((top[i][0] + w + 0.05, 3.5), (top[i + 1][0] - 0.05, 3.5), arrowstyle="-|>", mutation_scale=14, color=INK2))
  ax.add_patch(FancyArrowPatch((top[3][0] + w / 2, 2.72), (bot[0][0] + 0.45 + wb / 2, 2.03), arrowstyle="-|>", mutation_scale=14, color=INK2,
                               connectionstyle="arc3,rad=-0.2"))
  for i in range(4):
    ax.add_patch(FancyArrowPatch((bot[i][0] + 0.42, 1.2), (bot[i + 1][0] + 0.45 + wb + 0.03, 1.2), arrowstyle="-|>", mutation_scale=14, color=INK2))
  ax.text(0.2, 4.62, "From CAN frames to openpilot: the parser's nine steps", fontsize=11.5, weight="bold", va="top")
  ax.text(0.2, 0.12, f"Grey: decode (no tuning).  Yellow: the radar's own tracker outputs.  Green: the filter.  Blue: what reaches openpilot. "
          f"Radar provides {lv['2.3 fused']:.0%} of leads beyond 60 m with the path gate ({lv['2.1 fused']:.0%} without); vision covers the rest.",
          fontsize=7.8, color=INK2)
  fig.savefig(OUT / "guide_pipeline.png", dpi=130, bbox_inches="tight"); plt.close(fig)


def _car(ax, x, y, color, kept=True):
  ax.scatter([x], [y], s=260, marker="s", color=color if kept else "white", edgecolor=color, linewidth=2, hatch=None if kept else "////",
             zorder=5)


def _lanes(ax, d, center, color=GRAY):
  for off in (-5.4, -1.8, 1.8, 5.4):
    ax.plot(center + off, d, color=color, lw=1, ls=(0, (6, 6)) if abs(off) < 3 else "-", zorder=1)


def lead_guards() -> None:
  """Top-down: the path gate on a straight road (next-lane car gated, close car kept) and on a right curve."""
  fig, axs = plt.subplots(1, 2, figsize=(12.5, 6.2))
  d = np.linspace(-6, 130, 300)
  ax = axs[0]; ax.set_xlim(9, -9); ax.set_ylim(-6, 62); ax.grid(False); _lanes(ax, d, 0 * d)
  ax.fill_betweenx(d[d > 15], -2.5, 2.5, color=S1, alpha=0.10, lw=0); ax.axhline(15, color=INK2, lw=0.8, ls=":")
  ax.text(8.6, 13.5, "15 m: the gate starts", fontsize=7.5, color=INK2, va="top")
  _car(ax, 0, -2, INK2); ax.annotate("ego", (0, -2), xytext=(-2.2, -2), va="center", fontsize=8.5)
  _car(ax, 0, 40, S4); ax.annotate("lead (and ACC target):\nkept", (0, 40), xytext=(4.5, 50), fontsize=8,
                                   arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8), ha="center")
  _car(ax, -3.6, 41, S2, kept=False); ax.annotate("car in the next lane:\nwithheld", (-3.6, 41), xytext=(-6.0, 52), fontsize=8,
                                                  arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8), ha="center")
  _car(ax, -3.6, 9, S4); ax.annotate("closer than 15 m:\nkept (it may be cutting in)", (-3.6, 9), xytext=(-5.5, 24), fontsize=8,
                                     arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8), ha="center")
  ax.annotate("", xy=(-3.6, 33), xytext=(0, 33), arrowprops=dict(arrowstyle="<->", color=INK2, lw=1))
  ax.text(-1.8, 30.5, "> 2.5 m", ha="center", fontsize=8, color=INK2)
  ax.set_title("Straight road", loc="left"); ax.set_xlabel("lateral (m, left +)"); ax.set_ylabel("ahead (m)")
  ax = axs[1]; v, yaw = 30.0, -0.025; path = yaw / v * d ** 2 / 2
  ax.set_xlim(6, -14); ax.set_ylim(-6, 125); ax.grid(False); _lanes(ax, d, path)
  g = d > 15
  ax.fill_betweenx(d[g], (path - 2.5)[g], (path + 2.5)[g], color=S1, alpha=0.10, lw=0)
  ax.plot(path[d >= 0], d[d >= 0], color=S1, lw=1.8, ls="--")
  ax.text(-9.5, 124, "path predicted from\nyaw rate and speed,\n± 2.5 m", fontsize=7.8, color=S1, va="top")
  _car(ax, 0, -2, INK2)
  k = np.searchsorted(d, 100)
  _car(ax, path[k], 100, S4); ax.annotate("lead on the path: kept", (path[k], 100), xytext=(-9.0, 88), fontsize=8,
                                          arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
  _car(ax, path[k] + 3.6, 98, S2, kept=False); ax.annotate("car a lane over\n(straight ahead of ego!):\nwithheld", (path[k] + 3.6, 98),
                                                       xytext=(4.5, 108), fontsize=8, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
  ax.set_title("Right curve", loc="left"); ax.set_xlabel("lateral (m, left +)")
  fig.suptitle("Path gate: radard pairs the camera's lead with the radar track nearest in range, whatever its lateral position",
               x=0.01, ha="left", fontsize=10.5, color=INK, weight="bold")
  fig.tight_layout(); fig.savefig(OUT / "guide_lead_guards.png", dpi=130); plt.close(fig)


def cases() -> None:
  """Two road moments: what vision only, 2.1 and 2.3 would have asked the planner for."""
  C = pd.read_csv(REPO / "data" / "analysis" / "lead_choice_cases.csv.gz")
  spec = {"late_brake": ("A slowing pickup first seen at ~66 m", (-6, 2)),
          "next_lane": ("A slower car a lane over from the lead, on a right curve (no ACC target)", (-6, 3))}
  series = (("vision", VIS, "vision only", 4.0, 0.45), ("v21", V21, "2.1", 2.0, 1.0), ("v23", V23, "2.3 / 2.4", 2.0, 1.0))
  fig, axs = plt.subplots(2, 2, figsize=(12.5, 6.6), sharex="col", gridspec_kw={"height_ratios": [1.15, 1]})
  for j, case in enumerate(spec):
    title, (lo, hi) = spec[case]
    g = C[(C.case == case) & (C.t >= lo) & (C.t <= hi)]; t = g.t
    ax = axs[0, j]
    ax.plot(t, g.camera_d, ".", ms=2.5, color=GRAY, label="camera lead")
    ax.plot(t, g.acc_target_d, color=INK, lw=1.2, label="radar ACC target")
    for k, c, name, lw, al in series[1:]:
      d = g[f"{k}_lead_d"].where((g[f"{k}_lead_present"] == 1) & (g[f"{k}_lead_radar"] == 1))
      ax.plot(t, d, color=c, lw=lw, label=f"{name}: radar lead")
    ax.set_ylabel("range (m)"); ax.set_title(title, loc="left")
    ax = axs[1, j]; lows = []
    for k, c, name, lw, al in series:
      a = g[f"{k}_a_target"]; ax.plot(t, a, color=c, lw=lw, alpha=al, label=name, solid_capstyle="round")
      lows.append(f"{name}  {a.min():+.2f}")
    ax.text(0.98, 0.05, "lowest request (m/s²)\n" + "\n".join(lows), transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            color=INK, bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=GRID))
    ax.axhline(0, color=INK2, lw=0.6); ax.set_ylabel("planner request (m/s²)"); ax.set_xlabel("time (s), 0 = driver's bookmark")
  axs[0, 0].legend(loc="upper right"); axs[1, 0].legend(loc="lower left", ncols=3)
  fig.suptitle("Two road moments replayed through openpilot's planner (vision only is drawn wide underneath: where it is hidden, it agrees)",
               x=0.01, ha="left", fontsize=10.5, weight="bold")
  fig.tight_layout(); fig.savefig(OUT / "guide_cases.png", dpi=130); plt.close(fig)


def road_stats() -> None:
  """Owner's 2.1 drives against the numbers of issue #66 (a 2025 RAV4 Hybrid)."""
  R = json.loads((SUM / "road_v21.json").read_text())
  fig, axs = plt.subplots(1, 3, figsize=(13.5, 3.9), gridspec_kw={"width_ratios": [1.2, 1, 0.8]})
  ax = axs[0]; rg = R["range_radar_minus_camera_m"]; bins = list(rg)
  x = np.arange(len(bins)); med = [rg[b]["median"] for b in bins]; sd = [rg[b]["mad_sigma"] for b in bins]
  ax.errorbar(x, med, yerr=sd, fmt="o", ms=7, color=S1, ecolor=S1, elinewidth=1.6, capsize=4)
  for xi, m, s in zip(x, med, sd):
    ax.text(xi + 0.12, m, f"{m:+.1f} ± {s:.1f}", fontsize=7.8, va="center", color=INK)
  ax.axhline(0, color=INK2, lw=0.7); ax.set_xticks(x, [f"{b} m" for b in bins]); ax.set_xlim(-0.4, len(bins) - 0.1)
  ax.set_ylabel("radar − camera range (m)"); ax.set_title("Range: radar vs camera, same car\n(median ± robust spread, 300 k ticks)", loc="left")
  w = 0.36
  ax = axs[1]; o, i6 = R["acc_target_present_share"]["owner"], R["acc_target_present_share"]["issue66"]; bins = list(o); x = np.arange(len(bins))
  for k, (vals, c, name) in enumerate(((o, S1, "owner (7.4 h)"), (i6, S4, "issue #66 car"))):
    b = ax.bar(x + (k - 0.5) * w, [vals[q] * 100 for q in bins], w * 0.92, color=c, label=name)
    ax.bar_label(b, fmt="%.0f", fontsize=7.8, padding=2, color=INK)
  ax.set_xticks(x, [f"{q} m" for q in bins]); ax.set_ylim(0, 112); ax.set_ylabel("% of radar-lead time")
  ax.set_title("The radar's ACC target is present", loc="left")
  fig.legend(*ax.get_legend_handles_labels(), loc="upper right", ncols=2, bbox_to_anchor=(0.99, 1.0))
  ax = axs[2]; sg = R["speed_gap_over_3mps_share"]; keys = [("all", "all ranges"), ("beyond70", "beyond 70 m")]; x = np.arange(2)
  for k, (vals, c, name) in enumerate(((sg["owner"], S1, "owner"), (sg["issue66"], S4, "issue #66"))):
    b = ax.bar(x + (k - 0.5) * w, [vals[q] * 100 for q, _ in keys], w * 0.92, color=c, label=name)
    ax.bar_label(b, fmt="%.1f", fontsize=7.8, padding=2, color=INK)
  ax.set_xticks(x, [n for _, n in keys]); ax.set_ylabel("% of same-car time"); ax.set_ylim(0, 10)
  ax.set_title("Radar and camera closing speed\ndisagree by > 3 m/s", loc="left")
  fig.suptitle("Two cars, same radar firmware, same numbers (fused 2.1 on the road)", x=0.01, ha="left", fontsize=11, weight="bold")
  fig.tight_layout(); fig.savefig(OUT / "guide_road_stats.png", dpi=130); plt.close(fig)


SHORT = {"transport": "decode: transport, CRC, slots, track IDs, wrapper", "state pruning": "state pruning",
         "ACC target": "ACC target decode + association", "Kalman": "Kalman speed filter", "range fusion": "range fusion + ACC distance",
         "young-track factor": "young-track factor", "speed-std": "speed-std publication gate", "age-60": "age-60 publication gate",
         "fork compatibility": "fork compatibility", "ego-speed": "ego-speed alignment",
         "path gate": "path gate (yaw rate)"}


def _short(part: str) -> str:
  for k, v in SHORT.items():
    if part.startswith(k) or k in part.split(" (")[0]:
      return v
  return part


def parts_ledger() -> None:
  """Code lines of each part of the openpilot file, by upstream status."""
  L = json.loads((SUM / "openpilot_file_parts.json").read_text())
  status = lambda u: "required" if u.startswith("required") else "keep" if u.startswith("keep") else \
      "first to drop" if u.startswith("first") else "droppable / candidate"
  colors = {"required": INK2, "keep": S3, "droppable / candidate": S4, "first to drop": S2}
  parts = sorted(L["parts"], key=lambda p: (list(colors).index(status(p["upstream"])), -p["code_lines"]))
  fig, ax = plt.subplots(figsize=(12, 5.6)); y = np.arange(len(parts))[::-1]
  for yi, p in zip(y, parts):
    s = status(p["upstream"]); ax.barh(yi, p["code_lines"], 0.7, color=colors[s])
    ax.text(p["code_lines"] + 1.2, yi, f"{p['code_lines']}  ·  {p['without']}", va="center", fontsize=7.6, color=INK2)
  ax.set_yticks(y, [f"{_short(p['part'])}  [{p['since'].split(' ')[0]}]" for p in parts], fontsize=8.5)
  ax.set_xlim(0, 215); ax.set_xlabel("code lines in upstream/ars510_radar.py (comments, docstrings and blank lines excluded)")
  for s, c in colors.items():
    ax.barh(np.nan, 0, color=c, label=s)
  ax.legend(loc="upper right", title="for an upstream PR", title_fontsize=8)
  ax.set_title(f"What each of the openpilot file's {L['file_code_lines']} code lines buys (label: lines · cost of removing it)", loc="left")
  ax.grid(axis="y", visible=False)
  fig.tight_layout(); fig.savefig(OUT / "guide_parts_ledger.png", dpi=130); plt.close(fig)


def oracle() -> None:
  """Unnecessary and missed braking against openpilot's planner on a hindsight lead (confident moments), two data sets."""
  O = json.loads((SUM / "oracle_reference.json").read_text())
  sets = (("owner's road drives (7.65 h)", O["confident"], ["vision", "2.1", "2.3", "2.4"]),
          ("27 replay drives, independent (6.72 h)", O["suite_34_drives"]["confident"], ["vision", "2.1", "2.3", "2.4"]))
  names = {"vision": "vision only", "2.1": "2.1", "2.3": "2.3", "2.4": "2.4 (default)"}; col = {"vision": VIS, "2.1": V21, "2.3": GRAY, "2.4": V23}
  fig, axs = plt.subplots(2, 2, figsize=(11.5, 5.8))
  for r, (label, C, vers) in enumerate(sets):
    for c, (kind, title) in enumerate((("unnecessary", "braked > 0.5 m/s² harder than needed"), ("missed", "missed braking the oracle asked for"))):
      ax = axs[r, c]; v = [C[k][kind]["seconds"] for k in vers]; n = [C[k][kind]["episodes"] for k in vers]
      b = ax.barh(range(len(vers))[::-1], v, 0.62, color=[col[k] for k in vers])
      for bi, vi, ni in zip(b, v, n):
        ax.text(vi + 0.4, bi.get_y() + bi.get_height() / 2, f"{vi:.1f} s · {ni}", va="center", fontsize=8, color=INK)
      ax.set_yticks(range(len(vers))[::-1], [names[k] for k in vers] if c == 0 else [""] * len(vers))
      ax.set_xlim(0, 38); ax.grid(axis="y", visible=False); ax.set_title(f"{label}: {title}", loc="left", fontsize=9.5)
      if r == 1:
        ax.set_xlabel("seconds (label: seconds · episodes), confident moments")
  fig.suptitle("What should the car have done? openpilot's own planner on a hindsight lead, as the reference", x=0.01, ha="left",
               fontsize=10.5, weight="bold")
  fig.tight_layout(); fig.savefig(OUT / "guide_oracle.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
  pipeline(); lead_guards(); cases(); road_stats(); parts_ledger(); oracle()
  print("wrote", ", ".join(sorted(p.name for p in OUT.glob("guide_*.png"))))
