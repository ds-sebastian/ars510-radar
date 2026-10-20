#!/usr/bin/env python3
"""Figures for the opendbc proposal (docs/17): the `acc` and `acc_summaries` profiles against vision only.

    python tools/make_upstream_figures.py      # writes docs/img/analysis/upstream_*.png

upstream_vs_vision.png: oracle unnecessary / missed braking over every drive set (acc_target_parser.json,
acc_summaries_40m.json). upstream_vs_vision_checks.png: the same comparison against three references, by drive set, and
judged by the driver (upstream_case.json, acc_target_parser.json, acc_summaries_40m.json, profiles_vs_vision.json).
upstream_revealed_queue.png: one road moment, logged leads and a closed-loop replay (analysis/revealed_queue_case.csv.gz).
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from make_profile_figures import GRID, INK, INK2, S4, S5  # noqa: E402

OUT = REPO / "docs" / "img" / "analysis"
SUM = REPO / "data" / "analysis" / "summaries"
VIS = "#7a5fb0"
COL = {"vision only": VIS, "acc": S4, "acc_summaries": S5}
TICK = {"vision only": "vision\nonly", "acc": "acc\n(default)", "acc_summaries": "acc_summaries"}
SETS = (("27 replay drives", "27 replay\ndrives", "suite"), ("owner road drives + 2 second-car drives", "owner road\nset", "road"),
        ("second car (issue #66 tester, never tuned on)", "second car\n(never tuned on)", "second"))


def j(name: str) -> dict:
  return json.loads((SUM / name).read_text())


def all_sets() -> dict:
  """Oracle seconds over every drive set: vision only and acc from acc_target_parser.json, acc_summaries (40 m) from acc_summaries_40m.json."""
  A, S = j("acc_target_parser.json")["by_version_and_set"], j("acc_summaries_40m.json")["by_set"]["fast"]["acc_summaries 40 m (published)"]
  return {"vision only": A["vision only"]["all sets"], "acc": A["ACC target only"]["all sets"], "acc_summaries": S}


def _bars(ax, names, vals, fmt="{:g}", pad=0.012):
  top = max(vals)
  for i, (n, v) in enumerate(zip(names, vals)):
    ax.bar(i, v, 0.62, color=COL[n])
    ax.text(i, v + top * pad, fmt.format(v), ha="center", va="bottom", fontsize=9, color=INK)
  ax.set_xticks(range(len(names)), [TICK[n] for n in names]); ax.grid(axis="x", visible=False)
  ax.set_ylim(0, top * 1.12)


def vs_vision() -> None:
  """The headline: unnecessary and missed braking seconds against the hindsight oracle, every drive set."""
  V = all_sets(); names = list(V); h = V["acc"]["moving_h"]
  fig, axs = plt.subplots(1, 2, figsize=(8.2, 4.3))
  for ax, m, t in ((axs[0], "unnecessary_s", "unnecessary braking (oracle)"), (axs[1], "missed_s", "missed braking (oracle)")):
    _bars(ax, names, [round(V[n][m], 1) for n in names]); ax.set_ylabel("s"); ax.set_title(t, loc="left")
  fig.text(0.01, 0.015, f"Open-loop replays of 62 routes ({h:.1f} moving h, 2 cars) through openpilot's unchanged radard and planner.\n"
           "Unnecessary: braked > 0.5 m/s² harder than openpilot's planner on a hindsight lead. Missed: stayed above −0.5 m/s²\n"
           "while it asked ≤ −1. The hindsight lead is built mostly from the radar's ACC target, so it favours the radar;\n"
           "upstream_vs_vision_checks.png repeats the comparison against references that do not.", fontsize=7.4, color=INK2, va="bottom")
  fig.tight_layout(rect=(0, 0.17, 1, 1)); fig.savefig(OUT / "upstream_vs_vision.png", dpi=130); plt.close(fig)


def checks() -> None:
  """Three checks on the headline: the reference, the drive set, and the driver."""
  C = j("upstream_case.json"); R = C["reference_check"]["all"]
  A, S = j("acc_target_parser.json")["by_version_and_set"], j("acc_summaries_40m.json")["fast_suite_by_set"]
  P = j("profiles_vs_vision.json")
  fig, axs = plt.subplots(1, 3, figsize=(14, 4.6), gridspec_kw={"width_ratios": [1.15, 1.25, 0.9]})

  ax = axs[0]
  refs = (("ORACLE", "hindsight lead\n(mostly ACC target)"), ("AGREE", "moments where\nboth references agree"), ("CAMREF", "camera-only\nhindsight lead"))
  x = np.arange(len(refs)); w = 0.36
  for k, (lab, key) in enumerate((("vision only", "vision only"), ("acc", "acc"))):
    y = [R[r]["per_moving_h"][key]["unnecessary"] for r, _ in refs]
    ax.bar(x + (k - 0.5) * w, y, w * 0.94, color=COL[lab], label=lab)
    for xi, yi in zip(x + (k - 0.5) * w, y):
      ax.text(xi, yi + 0.12, f"{yi:.2f}", ha="center", fontsize=8, color=INK)
  for xi, (r, _) in zip(x, refs):
    d = R[r]["acc_minus_vision_per_moving_h"]["unnecessary"]
    top = max(R[r]["per_moving_h"]["vision only"]["unnecessary"], R[r]["per_moving_h"]["acc"]["unnecessary"])
    ax.text(xi, top + 1.0, f"acc − vision\n{d['diff']:+.2f} [{d['ci95'][0]:+.2f}, {d['ci95'][1]:+.2f}]", ha="center", fontsize=7.5, color=INK2)
  ax.set_xticks(x, [t for _, t in refs]); ax.set_ylim(0, 11.5); ax.grid(axis="x", visible=False); ax.legend(loc="upper left")
  ax.set_ylabel("unnecessary braking, s per moving hour")
  ax.set_title(f"Against three references ({R['routes']} routes, {R['moving_h']:.1f} moving h)", loc="left")

  ax = axs[1]; x = np.arange(len(SETS)); w = 0.26
  for k, n in enumerate(("vision only", "acc", "acc_summaries")):
    y = []
    for name, _, key in SETS:
      r = A["vision only" if n == "vision only" else "ACC target only"][name] if n != "acc_summaries" else S[key]["acc_summaries 40 m (published)"]
      y.append((r["unnecessary_s"] + r["missed_s"]) / r["moving_h"])
    ax.bar(x + (k - 1) * w, y, w * 0.94, color=COL[n], label=n)
    for xi, yi in zip(x + (k - 1) * w, y):
      ax.text(xi, yi + 0.15, f"{yi:.1f}", ha="center", fontsize=7.5, color=INK)
  ax.set_xticks(x, [f"{t}\n({A['ACC target only'][n]['moving_h']:.1f} moving h)" for n, t, _ in SETS])
  ax.set_ylabel("unnecessary + missed braking (oracle), s per moving hour"); ax.grid(axis="x", visible=False); ax.legend(loc="upper left")
  ax.set_title("By drive set", loc="left")

  ax = axs[2]; E = P["heldout_events"]; O = P["heldout_one_system_requests_and_overrides"]
  names = ["vision only", "acc", "acc_summaries"]
  y = [E["acc"]["vision_ant10"] * 100, E["acc"]["radar_ant10"] * 100, E["acc_summaries"]["radar_ant10"] * 100]
  _bars(ax, names, y, "{:.1f} %", pad=0.015); ax.set_ylim(0, 60)
  ax.set_ylabel("driver brake presses already asked ≤ −1 m/s²\n(from 3 s before to 0.5 s after)")
  o = O["acc"]["overrides"]
  ax.text(0.98, 0.97, f"{E['acc']['events']} driver brake presses, 4.56 h\ndriver overrides ({o['n']}): radar request\ncloser to the driver {o['radar_closer_to_driver']}, "
          f"further {o['radar_further']}\nbraking only the radar asked for: 0 /h", transform=ax.transAxes, ha="right", va="top", fontsize=7.5, color=INK2)
  ax.set_title("Judged by the driver (20 held-out routes)", loc="left")
  for a in axs:
    a.yaxis.grid(True, color=GRID)
  fig.tight_layout(); fig.savefig(OUT / "upstream_vs_vision_checks.png", dpi=130); plt.close(fig)


def revealed_queue() -> None:
  """A lead moves out and reveals a near-stopped car: logged leads, then the planner replayed with each radar input."""
  d = pd.read_csv(REPO / "data" / "analysis" / "revealed_queue_case.csv.gz"); Q = j("upstream_case.json")["revealed_queue"]
  lo, hi = -3.0, 8.0; d = d[(d.t >= lo) & (d.t <= hi)]
  L = d[d.series == "logged"]
  fig, axs = plt.subplots(1, 3, figsize=(14, 4.2))
  ax = axs[0]
  ax.plot(L.t, L.acc_target_v, color=S4, label="radar's ACC target"); ax.plot(L.t, L.camera_lead_v, color=VIS, label="camera lead")
  ax.plot(L.t, L.v_ego, color=INK2, lw=1, ls=":", label="ego (logged; the driver braked)")
  ax.set_ylabel("lead speed over ground (m/s)"); ax.legend(loc="upper right"); ax.set_ylim(-1, 17)
  ax.set_title("Logged: the ACC target reads the slow car at once", loc="left")
  ax.annotate(f"camera lead below 5 m/s\n{Q['camera_lead_speed_below_5_mps_after_s']:.2f} s later", xy=(Q["camera_lead_speed_below_5_mps_after_s"], 5),
              xytext=(1.8, 6.5), fontsize=7.5, color=INK2, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.7))
  style = {"acc": dict(color=S4), "acc_summaries": dict(color=S5, ls="--"), "vision only": dict(color=VIS)}
  R = Q["replay"]["loop closed 7.5 s before the press"]
  for n, st in style.items():
    s = d[d.series == n]
    axs[1].plot(s.t, s.request, label=f"{n}: first ≤ −1 at {R[n]['first_request_le_m1_s']:+.2f} s", **st)
    axs[2].plot(s.t, s.gap, label=f"{n}: closest {R[n]['min_gap_m']:.1f} m", **st)
  axs[1].set_ylabel("planner request (m/s²)"); axs[1].legend(loc="lower left", frameon=True, facecolor="white", edgecolor=GRID, framealpha=0.92); axs[1].set_title("Replayed: braking request", loc="left")
  axs[2].set_ylabel("gap to the car ahead (m)"); axs[2].legend(loc="upper right"); axs[2].set_ylim(-2, 60)
  axs[2].axhline(0, color=INK2, lw=0.7); axs[2].set_title("Replayed: gap", loc="left")
  for ax in axs:
    ax.axvline(0, color=INK2, lw=0.7, ls="--"); ax.set_xlim(lo, hi); ax.set_xlabel("s from the ACC target's switch to the slow car")
  fig.text(0.01, 0.01, "Owner acc road drive: the lead at 28 m moves right and reveals a near-stopped car 56 m ahead (the driver braked at the same moment). "
           "Replay: the device's planner from 7.5 s before the driver's\nbrake press, driver inputs removed, closed loop; camera model open loop. "
           "One event, exploratory (gaps good to about 1-2 m; a 25 s window gives 3.8 m with acc against 2.1 m with vision only).",
           fontsize=7.2, color=INK2, va="bottom")
  fig.tight_layout(rect=(0, 0.09, 1, 1)); fig.savefig(OUT / "upstream_revealed_queue.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
  vs_vision(); checks(); revealed_queue()
  print("wrote", ", ".join(sorted(p.name for p in OUT.glob("upstream_*.png"))))
