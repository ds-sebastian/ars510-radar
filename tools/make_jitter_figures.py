#!/usr/bin/env python3
"""Regenerate the figures of docs/16_the_jitter_problem.md from data/analysis/summaries/jitter_problem_figures.json.

    python tools/make_jitter_figures.py

The JSON holds provenance-labelled numbers from research-workspace replays (the rlogs are not bundled).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DATA = json.loads((REPO / "data/analysis/summaries/jitter_problem_figures.json").read_text())
OUT = REPO / "docs" / "img" / "analysis"

# Same validated palette as make_analysis_figures.py: slot 1 = radar, slot 2 = vision.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
RADAR, VISION, S3 = "#2a78d6", "#eb6834", "#1baf7a"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9.5,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8.5, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2.0, "font.size": 9.5,
})


def save(fig, name: str, note: str | None = None) -> None:
    if note:
        fig.text(0.01, -0.01, note, fontsize=7.5, color=INK2, ha="left", va="top", wrap=True)
    fig.savefig(OUT / f"{name}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def event() -> None:
    e = DATA["drive_d_event"]
    r, v = e["radar"], e["vision"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8.2, 5.6), sharex=True)
    a1.plot(v["t"], v["vrel"], color=VISION, lw=2, label="vision lead")
    a1.plot(r["t"], r["vrel"], color=RADAR, lw=2, label="radar track (native vRel)")
    a1.axhline(0, color="#b9b8b2", lw=0.8)
    a1.set_ylabel("relative speed (m/s)\nnegative = closing")
    a1.set_title("A far false closing (drive D4): the radar's velocity drifts, its own range does not follow", loc="left")
    a1.text(r["t"][-1] + 0.1, r["vrel"][-1], "radar", color=INK, fontsize=8.5, va="center")
    a1.text(v["t"][-1] + 0.1, v["vrel"][-1], "vision", color=INK, fontsize=8.5, va="center")
    a1.legend(loc="lower left")
    a2.plot(v["t"], v["d"], color=VISION, lw=2, label="vision lead distance")
    a2.scatter(r["t"], r["d"], s=9, color=RADAR, label="radar range (same track)", zorder=3)
    a2.plot(r["t"], r["d_implied_by_vrel"], color=RADAR, lw=2, ls="--", label="range the radar's vRel implies")
    a2.set_ylabel("distance ahead (m)")
    a2.set_xlabel("time from the start of the drift (s)")
    a2.legend(loc="lower left")
    lo = min(min(r["d_implied_by_vrel"]), min(r["d"])) - 5
    a2.set_ylim(lo, max(max(v["d"]), max(r["d"])) + 5)
    save(fig, "jitter_false_closing_event",
         "Logged radarState of the owner's first closed-loop drive (FrogPilot 0.9.7 + ARS510 port). For ~9 s the track's "
         "vRel says up to -12 m/s closing; integrated, that is ~50 m, but its measured range stays at 85-110 m and "
         "vision holds ~0. radard kept the track matched (the distance gate around vision is 25% = ~28 m). "
         "The slowdown felt in the car was mostly the cruise set speed; this track bound the plan only briefly.")


def roughness_by_state() -> None:
    rs = DATA["roughness_by_state"]
    states = [("steady radar lead", "steady\nradar lead"), ("switch window", "within 0.5 s of a\nlead switch"),
              ("steady vision lead", "steady\nvision lead")]
    x = np.arange(len(states))
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    rv = [rs[s]["rms_radar"] for s, _ in states]
    vv = [rs[s]["rms_vision_same_ticks"] for s, _ in states]
    ax.bar(x - 0.2, vv, 0.38, color=VISION, label="vision-only build")
    ax.bar(x + 0.2, rv, 0.38, color=RADAR, label="radar + vision build")
    for i, (s, _) in enumerate(states):
        d = rs[s]
        ax.text(i + 0.2, rv[i] + 0.003, f"+{d['diff']:.3f}\n[{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]", ha="center",
                va="bottom", fontsize=7.5, color=INK)
        ax.text(i, -0.022, f"{d['tick_share']:.0%} of the time", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, [lab for _, lab in states])
    ax.set_ylabel("aTarget roughness, rms above ~1 Hz (m/s²)")
    ax.set_ylim(-0.03, 0.18)
    ax.axhline(0, color="#b9b8b2", lw=0.8)
    ax.set_title("Where the extra jitter is: around radard's lead switches,\ni.e. when radar and vision disagree", loc="left")
    ax.legend(loc="upper left")
    save(fig, "jitter_roughness_by_state",
         "Held-out routes, same ticks in both builds (lead present, vEgo > 3 m/s, driver in control of speed). "
         "Labels: radar - vision difference with route-bootstrap 95% CI. Switch windows hold ~70% of the extra "
         "roughness energy; steady radar following adds only +0.005 m/s².")


def switching_symptom() -> None:
    c = DATA["candidates_heldout"]
    base, hyst = c["ars510"], c["H"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.2, 3.6))
    labels = ["radard as is", "radard + hysteresis\n(diagnostic)"]
    a1.bar([0, 1], [base["lead_switches_per_h"], hyst["lead_switches_per_h"]], 0.55, color=[RADAR, S3])
    a1.set_xticks([0, 1], labels)
    a1.set_title("lead switches per hour", loc="left")
    a2.bar([0, 1], [base["roughness_excess_vs_vision"], hyst["roughness_excess_vs_vision"]], 0.55, color=[RADAR, S3])
    a2.set_xticks([0, 1], labels)
    a2.set_title("extra roughness over vision-only (m/s²)", loc="left")
    for ax, vals, fmt in ((a1, [base["lead_switches_per_h"], hyst["lead_switches_per_h"]], "{:.0f}"),
                          (a2, [base["roughness_excess_vs_vision"], hyst["roughness_excess_vs_vision"]], "{:.4f}")):
        for i, val in enumerate(vals):
            ax.text(i, val, fmt.format(val), ha="center", va="bottom", fontsize=8.5, color=INK)
    fig.suptitle("Switching is a symptom: removing 80% of the switches leaves the jitter", x=0.01, y=1.06, ha="left",
                 fontsize=11, color=INK)
    save(fig, "jitter_switching_is_a_symptom",
         "Diagnostic only (not a proposal): a copy of radard that keeps the previous radar track while it stays within "
         "max(40% d, 8 m) of vision. On the moments that were switch windows before, it is still as rough "
         "(0.137 vs 0.141 m/s² rms; vision 0.109). The roughness belongs to the radar values at those moments.")


def tradeoff() -> None:
    c = {k: v for k, v in DATA["candidates_heldout"].items() if k not in ("H",)}
    base = c["ars510"]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), sharex=True)
    for ax, key, title in ((axes[0], "e4_excess_vs_vision", "agreement with the driver:\nshare of radar's excess error removed"),
                           (axes[1], "roughness_excess_vs_vision", "jitter:\nshare of radar's excess roughness removed")):
        pts = []
        for k, v in c.items():
            x = v["lag_vs_baseline_s"]
            y = 100 * (1 - v[key] / base[key])
            hi = k in ("K4", "AT0")
            ax.scatter(x, y, s=46 if hi else 30, color=RADAR if k != "ars510" else INK2, edgecolor=SURFACE, linewidth=1.5, zorder=3)
            if k != "ars510":
                pts.append([x, y, [k]])
        # hand-placed labels: (text, anchor key, offset in points); points near the origin share one label
        near = [k for k in ("K1", "K5", "MA2", "MA3") if k in c]
        if key == "e4_excess_vs_vision":
            place = [(" / ".join(near), "MA2", (-6, -14)), ("R2", "R2", (-6, 7)), ("AT3", "AT3", (5, 5)),
                     ("K6", "K6", (5, -12)), ("K3", "K3", (5, 4)), ("K4", "K4", (5, 4)), ("K2", "K2", (5, 4)),
                     ("R1", "R1", (5, 4)), ("K7 / K8", "K7", (5, 4)), ("RC", "RC", (5, -10)), ("AT0", "AT0", (5, 4))]
        else:
            place = [(" / ".join(near), "MA2", (-6, -14)), ("AT3", "AT3", (5, -2)), ("R2", "R2", (5, 4)),
                     ("K3", "K3", (5, 4)), ("K6", "K6", (5, -4)), ("K4", "K4", (5, 4)), ("K2", "K2", (5, 4)),
                     ("R1", "R1", (5, 4)), ("K8", "K8", (5, 3)), ("K7", "K7", (5, -8)), ("RC", "RC", (5, 4)),
                     ("AT0", "AT0", (5, 4))]
        for text, k, off in place:
            if k not in c:
                continue
            x, y = c[k]["lag_vs_baseline_s"], 100 * (1 - c[k][key] / base[key])
            ax.annotate(text, (x, y), xytext=off, textcoords="offset points", fontsize=8, color=INK,
                        fontweight="bold" if k in ("K4", "AT0") else "normal")
        ax.axhline(0, color="#b9b8b2", lw=0.8)
        ax.axvline(0, color="#b9b8b2", lw=0.8)
        ax.axhline(100, color=S3, lw=1, ls="--")
        ax.text(0.165, 103, "matches vision-only", ha="right", fontsize=7.5, color=INK2)
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_ylim(-80, 110)
        ax.set_xlabel("reaction time given up vs baseline (s)")
    axes[0].set_ylabel("% of the gap to vision-only closed")
    axes[0].text(-0.02, -74, "no candidate reaches the top-left", fontsize=8, color=INK2)
    fig.suptitle("Every interface-only fix tested sits on one trade-off", x=0.01, y=1.07, ha="left", fontsize=11, color=INK)
    names = "; ".join(f"{k} {v['name']}" for k, v in c.items() if k != "ars510")
    save(fig, "jitter_tradeoff", f"Held-out routes, one scorer for all rows. At baseline radar starts braking ~0.22 s before "
         f"vision-only around the driver's brake presses. {names}.")


def coverage() -> None:
    cv = DATA["acc_target_coverage_by_range"]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = np.arange(len(cv["bands_m"]))
    ax.bar(x, [100 * s for s in cv["share"]], 0.6, color=RADAR)
    for i, s in enumerate(cv["share"]):
        ax.text(i, 100 * s, f"{s:.0%}", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x, cv["bands_m"])
    ax.set_xlabel("radar lead distance (m)")
    ax.set_ylabel("% of radar-lead ticks")
    ax.set_ylim(0, 100)
    ax.set_title("The radar's own ACC target (0x235) rarely describes far leads", loc="left")
    save(fig, "jitter_acc_target_coverage",
         "Share of radard's radar-lead ticks whose object is matched to the ACC target (0x237 position), fresh drives. "
         "Far range is where velocity excursions concentrate (20-30x more often at 60-80 m than at 20-40 m).")


def real_gallery() -> None:
    g = DATA["real_drives"]["gallery"]
    fig, axes = plt.subplots(3, len(g), figsize=(4.0 * len(g), 8.4), sharex="col")
    for j, e in enumerate(g):
        r, v, p = e["radar"], e["vision"], e["plan"]
        a1, a2, a3 = axes[0, j], axes[1, j], axes[2, j]
        for ax in (a1, a2, a3):
            ax.axvspan(e["episode_s"][0], e["episode_s"][1], color="#e4e3df", alpha=0.6, lw=0)
        a1.plot(v["t"], v["vrel"], color=VISION, lw=1.8, label="vision")
        a1.plot(r["t"], r["vrel"], color=RADAR, lw=1.8, label="radar")
        a1.axhline(0, color="#b9b8b2", lw=0.8)
        a1.set_title(f"{e['label']}\n(drive {e['drive']}, {e['v_ego_kmh']} km/h)", loc="left", fontsize=9.5)
        a2.plot(v["t"], v["d"], color=VISION, lw=1.8, label="vision distance")
        a2.scatter(r["t"], r["d"], s=7, color=RADAR, label="radar range", zorder=3)
        a2.plot(r["t"], r["d_implied"], color=RADAR, lw=1.6, ls="--", label="range radar vRel implies")
        a2.text(0.02, 0.04, f"vRel says {e['radar_vrel_says_m']:+.0f} m, range moved {e['radar_range_moved_m']:+.0f} m",
                transform=a2.transAxes, fontsize=7.5, color=INK)
        a3.plot(p["t"], p["aT_vision_replay"], color=VISION, lw=1.8, label="vision-only would request")
        logged = [a if on else np.nan for a, on in zip(p["aT_logged"], p["long_active"])]
        a3.plot(p["t"], logged, color=RADAR, lw=1.8, label="openpilot requested (logged, while driving)")
        a3.axhline(0, color="#b9b8b2", lw=0.8)
        a3.set_xlabel("time from episode start (s)")
        if j == 0:
            a1.set_ylabel("relative speed (m/s)")
            a2.set_ylabel("distance (m)")
            a3.set_ylabel("acceleration request (m/s²)")
            a1.legend(loc="lower left", fontsize=7.5)
            a2.legend(loc="upper left", fontsize=7.5)
            a3.legend(loc="lower left", fontsize=7.5)
    fig.suptitle("Real closed-loop drives: the same disagreement is sometimes a radar error, sometimes radar's early warning",
                 x=0.01, y=1.01, ha="left", fontsize=11, color=INK)
    save(fig, "jitter_real_drive_gallery",
         "Owner's drives D1-D4 (FrogPilot 0.9.7 + ARS510 port), logged radarState and longitudinalPlan; 'vision-only would request' "
         "is an open-loop replay of the same moments without radar tracks. Grey band: the disagreement episode. Left two: the "
         "radar's own range contradicts its vRel (vision was right) and openpilot braked up to ~0.8 m/s² harder than vision-only. "
         "Right two: the range confirms the closing and radar braked earlier than vision. In the first second the two kinds look alike.")


def real_census() -> None:
    rd = DATA["real_drives"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.2, 3.9), gridspec_kw={"wspace": 0.35})
    bands = list(rd["share_of_radar_lead_time_disagreeing_by_range"].keys())
    vals = [100 * rd["share_of_radar_lead_time_disagreeing_by_range"][b] for b in bands]
    a1.bar(range(len(bands)), vals, 0.6, color=RADAR)
    for i, val in enumerate(vals):
        a1.text(i, val, f"{val:.0f}%", ha="center", va="bottom", fontsize=8.5, color=INK)
    a1.set_xticks(range(len(bands)), [b.replace("80-200", "80+") for b in bands])
    a1.set_xlabel("radar lead distance (m)")
    a1.set_ylabel("% of radar-lead time")
    a1.set_title("radar and vision speeds differ by >= 2 m/s", loc="left", fontsize=10)
    cl = rd["closure_by_direction"]
    dirs = ["radar more closing", "radar less closing"]
    vis = [cl[d]["radar_range_sides_with_vision"] for d in dirs]
    rad = [cl[d]["radar_range_sides_with_radar_vrel"] for d in dirs]
    y = np.arange(len(dirs))
    a2.barh(y, vis, 0.5, color=VISION, label="range agrees with vision (radar vRel wrong)")
    a2.barh(y, rad, 0.5, left=[v_ + 0.15 for v_ in vis], color=RADAR, label="range agrees with radar vRel")
    for i in range(len(dirs)):
        a2.text(vis[i] / 2, i, str(vis[i]), ha="center", va="center", fontsize=8.5, color="#ffffff")
        a2.text(vis[i] + 0.15 + rad[i] / 2, i, str(rad[i]), ha="center", va="center", fontsize=8.5, color="#ffffff")
    a2.set_yticks(y, [f"{d}\nthan vision" for d in dirs])
    a2.invert_yaxis()
    a2.set_xlabel("disagreement episodes (>= 1 s)")
    a2.set_xlim(0, max(v_ + r_ for v_, r_ in zip(vis, rad)) + 2)
    a2.set_title("whose side does the radar's own range take?", loc="left", fontsize=10)
    a2.legend(loc="center", bbox_to_anchor=(0.55, 0.5), fontsize=7.5)
    h = rd["hours"]
    fig.suptitle(f"{rd['n_episodes']} disagreements in {h['radar_lead_h']:.2f} h of radar-lead driving (drives D1-D4): "
                 "about one every 20 s", x=0.01, y=1.04, ha="left", fontsize=11, color=INK)
    save(fig, "jitter_real_drive_census",
         "Radar-lead ticks with vision prob > 0.5 and vEgo > 3 m/s. Right: over each episode (±0.5 s), the change of the radar's "
         "measured range compared with the change its vRel implies and the change vision's speed implies. False closings are "
         "mostly radar errors; 'less closing' disagreements are more often vision lagging.")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (event, roughness_by_state, switching_symptom, tradeoff, coverage, real_gallery, real_census):
        f()
