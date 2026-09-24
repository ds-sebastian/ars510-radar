#!/usr/bin/env python3
"""Regenerate docs/img/analysis/*.png from the shipped dataset in data/analysis (needs pandas, pyarrow, matplotlib).

Every chart in docs/11_visual_tour.md comes from this script, so anyone can reproduce or re-slice them.
  python tools/make_analysis_figures.py            # all figures
  python tools/make_analysis_figures.py vrel_hexbin excursion_gallery   # a subset
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from ars510.record import id80_crc_ok  # noqa: E402
from ars510.transport import Id80RecordAssembler  # noqa: E402

DATA = REPO / "data" / "analysis"
OUT = REPO / "docs" / "img" / "analysis"

# Palette (validated reference instance): categorical slots 1-3 for drives / series, blue ramp for density,
# blue <-> red with a gray midpoint for signed correlations.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4, S5 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
DRIVE_COL = {"A": S1, "B": S2, "C": S3}
DRIVE_NAME = {"A": "A (dev, mixed)", "B": "B (held-out city)", "C": "C (held-out highway)"}
BLUES = LinearSegmentedColormap.from_list("blues", ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIVERGE = LinearSegmentedColormap.from_list("div", ["#184f95", "#3987e5", "#f0efec", "#e66767", "#a8292a"])
BANDS = [(3, 30), (30, 60), (60, 100)]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9.5,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8.5, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2.0, "font.size": 9.5,
})

_cache: dict[str, pd.DataFrame] = {}


def load(name: str) -> pd.DataFrame:
    if name not in _cache:
        _cache[name] = pd.read_parquet(DATA / f"{name}.parquet")
    return _cache[name]


def summary(name: str) -> dict:
    return json.loads((DATA / "summaries" / f"{name}.json").read_text())


def settled() -> pd.DataFrame:
    S = load("slots")
    return S[(S.age >= 60) & (S.x > 0.5)]


def save(fig, name: str, note: str | None = None) -> None:
    if note:
        fig.text(0.01, -0.01, note, fontsize=7.5, color=INK2, ha="left", va="top", wrap=True)
    fig.savefig(OUT / f"{name}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- structure -----------------------------------------
def bitmap():
    bm = json.loads((REPO / "data/reference/slot_bit_map.json").read_text())
    flip, ones = np.array(bm["slot_bit_flip_rate"]), np.array(bm["slot_bit_ones"])
    named = {"AGE": "age", "DREL": "dRel", "YREL_LEFT": "yRel", "VLONG_OVER_GROUND": "v_long", "VLAT_OVER_GROUND_PROV": "v_lat",
             "ALONG_LIKE_84": "accel?", "UNK_96": "u96"}
    fig, axes = plt.subplots(2, 1, figsize=(13, 5.2), sharex=True)
    for ax, vals, lab in ((axes[0], flip, "flip rate per cycle\n(same track, consecutive records)"), (axes[1], ones, "share of cycles\nthe bit is 1")):
        ax.bar(np.arange(len(vals)), vals, width=0.85, color=INK2)
        ax.set_ylabel(lab)
        for f in bm["slot_fields"]:
            if f["name"] in named:
                ax.axvspan(f["start"] - 0.5, f["start"] + f["len"] - 0.5, color=S1, alpha=0.13, lw=0)
            elif f["kind"] == "candidate":
                ax.axvspan(f["start"] - 0.5, f["start"] + f["len"] - 0.5, color=S4, alpha=0.10, lw=0)
    for f in bm["slot_fields"]:
        if f["name"] in named:
            axes[0].text(f["start"] + f["len"] / 2, flip.max() * 1.02, named[f["name"]], ha="center", va="bottom", fontsize=8, color=INK)
    for b in range(0, 289, 8):
        axes[1].axvline(b - 0.5, color="#cfcec8", lw=0.5, zorder=0)
    axes[1].set_xlabel("slot bit (little-endian: bit 0 = LSB of slot byte 0); thin lines = byte boundaries")
    axes[0].set_title("0x80 slot, all 288 bits: carry chains (flip rate falling from LSB to MSB) delimit the fields")
    axes[0].set_xlim(-1, 288)
    save(fig, "slot_bit_map", "blue = decoded fields, yellow = unverified candidate fields from the automatic split (data/reference/slot_bit_map.json)")


def sample_records(name="highway_following_30s.csv.gz"):
    asm, recs = Id80RecordAssembler(), []
    with gzip.open(REPO / "data/sample" / name, "rt") as fh:
        for r in csv.DictReader(fh):
            if r["bus"] == "1" and r["address"] == "0x80":
                c = asm.push(float(r["t_s"]), bytes.fromhex(r["data_hex"]))
                if c is not None and id80_crc_ok(c.payload):
                    recs.append(c.payload)
    return np.frombuffer(b"".join(recs), np.uint8).reshape(len(recs), -1)


def record_raster():
    R = sample_records()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [2.3, 1]})
    a1.imshow(R, aspect="auto", cmap="gray", interpolation="nearest")
    for s in range(21):
        a1.axvline(17 + 36 * s - 0.5, color=S2, lw=0.6)
    a1.axvline(737 - 0.5, color=S3, lw=1)
    a1.set_title("30 s of 0x80 records, one row per record, one pixel per byte")
    a1.set_xlabel("record byte (orange = slot boundaries, 17 + 36k; green = CRC32 at 737)")
    a1.set_ylabel("record (60 ms each)")
    a1.grid(False)
    slot0 = R[:, 17:17 + 36]
    bits = np.unpackbits(slot0, axis=1, bitorder="little")
    a2.imshow(bits[:, :112], aspect="auto", cmap="gray_r", interpolation="nearest")
    for start, lab in ((24, "age"), (32, "dRel"), (44, "yRel"), (64, "v_long"), (74, "v_lat"), (84, "accel?"), (96, "u96")):
        a2.axvline(start - 0.5, color=S2, lw=0.7)
        a2.text(start + 0.5, -4, lab, fontsize=7.5, color=INK, rotation=45, ha="left", va="bottom")
    a2.set_title("slot 0, bits 0-111 over time\n(LSBs flicker, MSBs hold: carry chains)", pad=26)
    a2.set_xlabel("slot bit")
    a2.grid(False)
    save(fig, "record_raster", "Source: data/sample/highway_following_30s.csv.gz. Idle slots repeat the fixed idle template (vertical stripes).")


# ---------------------------------------------------------------- scales & semantics --------------------------------
def vground_vs_ego():
    S = load("slots")
    S = S[(S.age >= 20) & S.x.between(0.5, 120)]
    fig, ax = plt.subplots(figsize=(7.2, 6))
    h = ax.hist2d(S.v_ego, S.v_ground, bins=[np.arange(0, 38, 0.4), np.arange(-38, 45, 0.5)], cmap=BLUES, norm=LogNorm(), cmin=1)
    fig.colorbar(h[3], ax=ax, label="track samples (age >= 20)")
    v = np.array([0, 37])
    ax.plot(v, v, color=S2, lw=1.2, ls="--")
    ax.plot(v, 0 * v, color=S3, lw=1.2, ls="--")
    ax.plot(v, -v, color=S5, lw=1.2, ls="--")
    ax.text(30, 32.5, "same direction\n(v_ground = v_ego)", color=INK, fontsize=8.5, ha="right")
    ax.text(30, 1.2, "stationary (v_ground = 0)", color=INK, fontsize=8.5, ha="right")
    ax.text(30, -26, "oncoming (v_ground = -v_ego)", color=INK, fontsize=8.5, ha="right")
    ax.set_xlabel("ego speed, Toyota 0xB4 (m/s)")
    ax.set_ylabel("decoded 64|10 (code - 510.5) x 0.15 (m/s)")
    ax.set_title("64|10 is velocity OVER GROUND: traffic sits on v_ego,\nstationary objects on 0, oncoming on -v_ego (all drives, age >= 20)")
    save(fig, "vground_vs_ego")


def standstill_codes():
    X = load("standstill_codes")
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=False)
    for ax, (d, g) in zip(axes, X.groupby("drive")):
        c = g.vel_code.value_counts().sort_index()
        c = c[(c.index >= 505) & (c.index <= 516)]
        ax.bar(c.index, c.values, color=DRIVE_COL[d], width=0.8)
        ax.axvline(510.5, color=INK, lw=1, ls="--")
        w = (g.vel_code[(g.vel_code >= 505) & (g.vel_code <= 516)]).mean()
        ax.set_title(f"drive {DRIVE_NAME[d]}")
        ax.set_xlabel("64|10 code, ego and object stopped")
        ax.text(0.02, 0.92, f"mean {w:.2f}", transform=ax.transAxes, fontsize=8.5, color=INK2)
    axes[0].set_ylabel("samples")
    save(fig, "standstill_codes", "Stopped objects behind a stopped ego pile up on codes 510/511: zero point 510.5 (dashed).")


def lateral_hist():
    S = settled()
    S = S[S.x.between(20, 90) & (S.v_ego > 20) & (S.y.abs() < 9) & (S.v_ground > 10)]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    bins = np.arange(-9, 9.01, 0.125)
    for d, g in S.groupby("drive"):
        ax.hist(g.y, bins=bins, histtype="step", color=DRIVE_COL[d], lw=1.6, density=True, label=f"drive {DRIVE_NAME[d]}")
    for k in (-2, -1, 1, 2):
        ax.axvline(3.66 * k, color=INK2, lw=0.8, ls=":")
    ax.set_xlabel("yRel = (44|12 code - 2048) / 64  (m, left positive); dotted = 3.66 m lane multiples")
    ax.set_ylabel("density")
    ax.set_title("Moving traffic at highway speed, 20-90 m: lane peaks near +/-3.66 m support the 1/64 scale (+/-10%)")
    ax.legend(loc="upper left")
    save(fig, "lateral_lane_peaks", "Left of zero = right lanes. Lane widths vary, which is why lane peaks bound the scale only to about 10%.")


def bev_density():
    S = settled()
    fig, axes = plt.subplots(1, 3, figsize=(12, 5.4), sharey=True)
    for ax, (d, g) in zip(axes, S.groupby("drive")):
        h = ax.hist2d(g.y, g.x, bins=[np.arange(-15, 15.01, 0.25), np.arange(0, 160, 1.0)], cmap=BLUES, norm=LogNorm(), cmin=1)
        ax.invert_xaxis()
        ax.set_title(f"drive {DRIVE_NAME[d]}")
        ax.set_xlabel("yRel (m), left is left")
    axes[0].set_ylabel("dRel (m)")
    fig.colorbar(h[3], ax=axes, label="settled samples", shrink=0.8)
    fig.suptitle("Where the radar reports settled objects (bird's-eye density)", x=0.45)
    save(fig, "bev_density")


def ground_contact():
    G = load("ground_contact")
    G = G[G.x.between(5, 25)]
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.9), sharey=True)
    for ax, (d, g) in zip(axes, G.groupby("drive")):
        ax.scatter(g.x + 1.52, g.cam_ground_x, s=3, alpha=0.15, color=DRIVE_COL[d], lw=0)
        ax.plot([6, 27], [6, 27], color=INK, lw=1, ls="--")
        res = (g.cam_ground_x - (g.x + 1.52)).median()
        ax.set_title(f"drive {DRIVE_NAME[d]}")
        ax.text(0.04, 0.9, f"median camera - radar: {res:+.2f} m\nn = {len(g)}", transform=ax.transAxes, fontsize=8.5, color=INK2)
        ax.set_xlabel("radar dRel + 1.52 m (distance from camera)")
        ax.set_xlim(5, 28)
        ax.set_ylim(0, 40)
    axes[0].set_ylabel("camera ground-contact distance (m)")
    save(fig, "range_ground_contact",
         "Camera distance = box bottom projected onto a flat road with the log's liveCalibration and openpilot intrinsics (no model output). "
         "Drive B is hilly (flat-road assumption). The flat cluster near 7.7 m on A is the hood clipping box bottoms.")


def lateral_scale():
    L = load("lateral_pairs")
    L = L[L.cam_Y_outer_center.abs() > 1]
    fig, ax = plt.subplots(figsize=(6.8, 5.2))
    for d, g in L.groupby("drive"):
        ax.scatter(g.cam_Y_outer_center, g.lat_code - 2048, s=3, alpha=0.12, color=DRIVE_COL[d], lw=0, label=f"drive {d}")
    y = np.array([-10, 10])
    ax.plot(y, 64 * y, color=INK, lw=1.2, ls="--", label="1/64 m (adopted)")
    ax.plot(y, 70 * y, color=S4, lw=1.2, ls=":", label="1/70 m (camera fit)")
    ax.set_xlabel("camera lateral of the vehicle centre (outer box edge -/+ 0.9 m), m, left +")
    ax.set_ylabel("44|12 code - 2048")
    ax.set_title("Lateral: sign is unambiguous, scale is 1/64-1/70 m per code")
    leg = ax.legend(markerscale=4)
    for lh in leg.legend_handles:
        lh.set_alpha(1)
    save(fig, "lateral_scale_camera")


# ---------------------------------------------------------------- lifecycle ------------------------------------------
def lifetimes():
    S = load("slots")
    T = S.groupby(["drive", "seg", "track"]).agg(t0=("t", "min"), t1=("t", "max"), amax=("age", "max")).reset_index()
    T["dur"] = T.t1 - T.t0
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
    for d, g in T.groupby("drive"):
        v = np.sort(g.dur.clip(lower=0.06))
        a1.plot(v, 1 - np.arange(len(v)) / len(v), color=DRIVE_COL[d], label=f"drive {d} ({len(v)} tracks)")
    a1.set_xscale("log")
    a1.set_yscale("log")
    a1.axvline(3.6, color=INK2, lw=0.8, ls=":")
    a1.text(3.8, 0.5, "age 60 = publish\n(OPENPILOT_CONFIG)", fontsize=8, color=INK2)
    a1.set_xlabel("track lifetime (s), capped by 60 s segment files")
    a1.set_ylabel("share of tracks living at least this long")
    a1.set_title("Most tracks are short; a few live the whole minute")
    a1.legend()
    N = S.groupby(["drive", "seg", "t"]).size().reset_index(name="n")
    for d, g in N.groupby("drive"):
        c = g.n.value_counts(normalize=True).sort_index()
        a2.plot(c.index, c.values, color=DRIVE_COL[d], marker="o", ms=4, label=f"drive {d}")
    a2.set_xlabel("occupied slots per record (max 20)")
    a2.set_ylabel("share of records")
    a2.set_title("Objects per record")
    a2.legend()
    save(fig, "track_lifetimes")


def slot_gantt(seg="C13"):
    S = load("slots")
    g = S[S.seg == seg].sort_values("t")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.3]})
    for (slot, track), q in g.groupby(["slot", "track"]):
        t, age = q.t.to_numpy(), q.age.to_numpy()
        a1.plot(t, np.full(len(t), slot), color="#b7d3f6", lw=5, solid_capstyle="butt")
        m = age >= 60
        if m.any():
            a1.plot(np.where(m, t, np.nan), np.full(len(t), slot), color="#184f95", lw=5, solid_capstyle="butt")
        a1.text(t[0], slot + 0.35, str(track), fontsize=6.5, color=INK2)
    nslot = int(g.slot.max()) + 1
    a1.set_yticks(range(nslot))
    a1.set_ylim(nslot - 0.2, -0.8)
    a1.set_ylabel("0x80 slot")
    a1.set_title(f"Segment {seg} (highway): slot occupancy (only slots 0-{nslot - 1} used: lowest free slot first); light = settling, dark = settled (age >= 60)")
    longest = g.groupby("track").t.agg(lambda s: s.max() - s.min()).sort_values(ascending=False).index[:3]
    for tr, q in g.groupby("track"):
        a2.plot(q.t, q.x, color="#c9c8c2", lw=0.9)
    for c, tr in zip((S1, S2, S3), longest):
        q = g[g.track == tr]
        a2.plot(q.t, q.x, color=c, lw=1.6, label=f"track {tr}")
    a2.set_ylabel("dRel (m)")
    a2.set_xlabel("time in segment (s)")
    a2.legend(loc="upper right")
    a2.set_title("Range of every track (gray) with the three longest highlighted: note the record-to-record range walk")
    save(fig, "slot_occupancy_and_tracks")


def age_convergence():
    C = load("camera_pairs")
    C = C[C.vcam2.notna() & C.x.between(3, 80)]
    bins = [(11, 25), (26, 50), (51, 80), (81, 125), (126, 126)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
    w = 0.26
    for i, (d, g) in enumerate(C.groupby("drive")):
        med = [np.median(np.abs(g.vrel - g.vcam2)[g.age.between(a, b)]) if g.age.between(a, b).sum() > 20 else np.nan for a, b in bins]
        a1.bar(np.arange(len(bins)) + (i - 1) * w, med, width=w - 0.03, color=DRIVE_COL[d], label=f"drive {d}")
    a1.set_xticks(range(len(bins)), [f"{a}-{b}" if a != b else "126 (sat.)" for a, b in bins])
    a1.set_xlabel("track age (radar cycles, 60 ms)")
    a1.set_ylabel("median |native vRel - camera| (m/s)")
    a1.set_title("Young tracks are unconverged")
    a1.legend()
    for d in "ABC":
        rows = summary(f"vrel_camera_rate_{d}").get("direction_of_travel_by_age", [])
        if rows:
            a2.plot([r["age"] for r in rows], [r["direction_agrees"] for r in rows], marker="o", ms=5, color=DRIVE_COL[d], label=f"drive {d}")
    a2.set_ylabel("direction of travel agrees with camera")
    a2.set_xlabel("track age bin")
    a2.set_title("Same-way / stopped / oncoming: right once settled")
    a2.set_ylim(0.7, 1.005)
    a2.legend()
    save(fig, "age_convergence", "Camera-paired rows only exist from age ~11 on. Right: direction over ground (same way / stopped / oncoming) vs camera.")


# ---------------------------------------------------------------- vRel -----------------------------------------------
def vrel_hexbin():
    C = load("camera_pairs")
    C = C[C.vcam2.notna() & (C.age >= 60)]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4), sharey=True)
    for ax, (lo, hi) in zip(axes, BANDS):
        q = C[C.x.between(lo, hi)]
        hb = ax.hexbin(q.vcam2, q.vrel, gridsize=60, extent=(-15, 15, -15, 15), cmap=BLUES, bins="log", mincnt=1)
        ax.plot([-15, 15], [-15, 15], color=S2, lw=1, ls="--")
        rms = np.sqrt(np.mean((q.vrel - q.vcam2) ** 2))
        ax.set_title(f"{lo}-{hi} m\nn = {len(q)}, RMS diff {rms:.2f} m/s", fontsize=10)
        ax.set_xlabel("camera box-growth closing speed (m/s)")
    axes[0].set_ylabel("native vRel (m/s)")
    fig.colorbar(hb, ax=axes, label="samples (log)", shrink=0.85)
    save(fig, "vrel_vs_camera", "Settled, camera-paired samples: RMS is disagreement, not isolated radar accuracy.\n"
                                "Image motion has its own noise; metric camera velocity also inherits radar range and association errors.")


def vrel_mse():
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9), sharey=True)
    w = 0.27
    for ax, d in zip(axes, "ABC"):
        m = {x["band"]: x for x in summary(f"vrel_camera_rate_{d}")["margins"] if x["window_s"] == 2 and x["subset"] == "all_paired"}
        bands = [b for b in ("3-30", "30-60", "60-100") if b in m]
        for i, (key, lab, col) in enumerate((("mse_native", "native vRel", S1), ("mse_zero", "constant 0", S2), ("mse_causal_deriv_1s", "1 s range derivative", S3))):
            ax.bar(np.arange(len(bands)) + (i - 1) * w, [m[b][key] for b in bands], width=w - 0.03, color=col, label=lab)
        ax.set_xticks(range(len(bands)), [f"{b} m" for b in bands])
        ax.set_yscale("log")
        ax.set_title(f"drive {DRIVE_NAME[d]}")
    axes[0].set_ylabel("MSE vs camera box growth ((m/s)², log)")
    axes[0].legend(loc="upper left")
    save(fig, "vrel_mse_baselines", "Native beats both trivial baselines in every band on every drive (A was the development drive, B and C held out).")


def tch_and_stationary():
    T = summary("three_cornered_hat")
    ST = summary("stationary_truth")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.1))
    w = 0.26
    bands = ["3-30", "30-60", "60-100"]
    for i, d in enumerate("ABC"):
        a1.bar(np.arange(3) + (i - 1) * w, [T[d][b]["rms_error"]["native"] for b in bands], width=w - 0.03, color=DRIVE_COL[d], label=f"drive {d}")
    for k, thr in enumerate((1.0, 1.5, 2.0)):
        a1.plot([k - 0.45, k + 0.45], [thr, thr], color=INK, lw=1.2, ls="--")
    a1.text(2.47, 2.02, "proposed\nthreshold", fontsize=7.5, color=INK2, va="bottom", ha="right")
    a1.set_xticks(range(3), [f"{b} m" for b in bands])
    a1.set_ylabel("conditional native random-error SD (m/s)")
    a1.set_title("Three-cornered hat: assumed error independence")
    a1.legend(loc="upper left")
    xs, labs, k = [], [], 0
    for d in "ABC":
        for b in ("5-30", "30-60"):
            r = ST[d]["bands"].get(b, {})
            if r.get("n", 0) >= 30:
                a2.bar(k, r["vrel_err_rms"], color=DRIVE_COL[d], width=0.7)
                a2.text(k, r["vrel_err_rms"] + 0.01, f"{r['tracks']} track" + ("s" if r["tracks"] != 1 else ""), ha="center", fontsize=7.5, color=INK2)
                xs.append(k)
                labs.append(f"drive {d}\n{b} m")
                k += 1
    a2.set_xticks(xs, labs)
    a2.set_ylabel("vRel RMS vs assumed -v_ego (m/s)")
    a2.set_title("Historical range-selected stationary subset")
    save(fig, "vrel_error_truths", "Left: conditional SD, NOT RMSE; bias excluded and shared-input errors may correlate.\n"
                                   "Right: range-selected, low-speed subset; newer video-selected results are less favourable (docs/13).")


def _pairs_with_error():
    C = load("camera_pairs")
    C = C[C.vcam2.notna() & (C.age >= 60)].copy()
    C["e"] = C.vrel - C.vcam2
    return C


def error_tails():
    C = _pairs_with_error()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.1))
    bins = np.arange(-15, 15.01, 0.25)
    for (lo, hi), col in zip(BANDS, (S1, S2, S3)):
        q = C[C.x.between(lo, hi)].e
        a1.hist(q, bins=bins, histtype="step", density=True, color=col, lw=1.6, label=f"{lo}-{hi} m")
        s = 1.4826 * np.median(np.abs(q - q.median()))
        xx = np.linspace(-15, 15, 400)
        a1.plot(xx, np.exp(-0.5 * ((xx - q.median()) / s) ** 2) / (s * np.sqrt(2 * np.pi)), color=col, lw=0.8, ls=":")
    a1.set_yscale("log")
    a1.set_ylim(1e-4, 2)
    a1.set_xlabel("native vRel - camera (m/s)")
    a1.set_ylabel("density (log)")
    a1.set_title("Error distribution: Gaussian core, heavy tails (dotted = Gaussian, same MAD)")
    a1.legend()
    # autocorrelation of the difference, resampled to 0.1 s per (segment, radar track, camera track)
    lags = np.arange(0, 41)
    for (lo, hi), col in zip(BANDS, (S1, S2, S3)):
        acs = []
        for _, g in C[C.x.between(lo, hi)].groupby(["seg", "track", "cam_track"]):
            if len(g) < 80:
                continue
            t, e = g.t_r.to_numpy(), g.e.to_numpy()
            grid = np.arange(t[0], t[-1], 0.1)
            if len(grid) < 60:
                continue
            x = np.interp(grid, t, e)
            x = x - x.mean()
            den = (x * x).sum()
            if den <= 0:
                continue
            acs.append([(x[: len(x) - k] * x[k:]).sum() / den for k in lags])
        if acs:
            a2.plot(lags * 0.1, np.mean(acs, axis=0), color=col, label=f"{lo}-{hi} m ({len(acs)} runs)")
    a2.axhline(0, color=INK2, lw=0.8)
    a2.set_xlabel("lag (s)")
    a2.set_ylabel("autocorrelation of (native - camera)")
    a2.set_title("The error is correlated over ~1 s: not white noise")
    a2.legend()
    save(fig, "vrel_error_tails_and_correlation", "The camera reference is itself a 2 s box-growth estimate, so part of the correlation is the reference's. A radar-only state-space fit "
                                                          "independently puts the radar excursion correlation time at 1-3 s (docs/06).")


def _range_slope(S, seg, tr, t, half=1.0):
    q = S[(S.seg == seg) & (S.track == tr) & S.t.between(t - half, t + half)]
    if len(q) < 12:
        return np.nan
    return float(np.polyfit(q.t, q.x, 1)[0])


def excursion_gallery(n=6):
    """Radar-attributed disagreements: native vRel far from the camera AND the radar's own 2 s range slope sides with the camera."""
    C = _pairs_with_error()
    C = C[(C.y.abs() < 1.8) & C.x.between(15, 90)]
    S = load("slots")
    cands = []
    for key, g in C.groupby(["drive", "seg", "track", "cam_track"]):
        g = g.sort_values("t_r")
        e = g.e.to_numpy()
        if (np.abs(e) > 3).sum() < 6:
            continue
        i = int(np.argmax(np.abs(e)))
        cands.append((abs(e[i]), key, float(g.t_r.iloc[i]), float(g.vrel.iloc[i]), float(g.vcam2.iloc[i])))
    cands.sort(reverse=True)
    picked, seen = [], set()
    for mag, key, tp, vr, vc in cands:
        if (key[1], key[2]) in seen:
            continue
        sl = _range_slope(S, key[1], key[2], tp)
        if not np.isfinite(sl) or abs(sl - vc) > 0.5 * abs(sl - vr):
            continue  # the radar's own range does not side with the camera: likely a camera-side fault
        seen.add((key[1], key[2]))
        picked.append((key, tp))
        if len(picked) == n:
            break
    fig, axes = plt.subplots(2, len(picked), figsize=(2.8 * len(picked), 5.8), sharex="col", squeeze=False)
    for k, ((d, seg, tr, ct), tp) in enumerate(picked):
        g = C[(C.seg == seg) & (C.track == tr) & (C.cam_track == ct) & C.t_r.between(tp - 5, tp + 5)]
        s = S[(S.seg == seg) & (S.track == tr) & S.t.between(tp - 5, tp + 5)]
        ts = np.arange(max(s.t.min(), tp - 4) + 1, min(s.t.max(), tp + 4) - 1, 0.25) if len(s) else []
        sl = [_range_slope(S, seg, tr, t) for t in ts]
        a, b = axes[0, k], axes[1, k]
        a.plot(g.t_r - tp, g.vrel, color=S1, lw=1.5, label="native vRel")
        a.plot(g.t_r - tp, g.vcam2, color=S3, lw=1.5, label="camera box growth")
        a.plot(np.asarray(ts) - tp, sl, color=S2, lw=1.2, ls="--", label="radar 2 s range slope")
        a.set_title(f"{seg} track {tr}, ~{g.x.median():.0f} m", fontsize=9)
        b.plot(s.t - tp, s.x, ".", ms=2.5, color=S1)
        b.set_xlabel("s from peak")
        if k == 0:
            a.set_ylabel("closing speed (m/s)")
            b.set_ylabel("radar dRel (m)")
            a.legend(loc="lower left", fontsize=7)
    fig.suptitle("Radar-attributed vRel excursions on settled in-lane tracks: native disagrees with the camera while the radar's own range agrees with it", y=1.01)
    save(fig, "excursion_gallery", "Auto-selected: |native - camera| > 3 m/s for >= 6 samples, then kept only where the radar's 2 s range slope is at least twice "
                                   "as close to the camera as to native vRel. Not hand-checked against video.")


def track_end_behaviour():
    S = load("slots").sort_values(["seg", "track", "t"])
    g = S.groupby(["seg", "track"])
    S["t_end"] = g.t.transform("max")
    S["dv"] = g.v_ground.diff().abs()
    S["dx"] = (g.x.diff() - S.vrel * g.t.diff()).abs()
    seg_end = S.groupby("seg").t.transform("max")
    ended = (S.t_end < seg_end - 0.5) & (g.age.transform("max") >= 60)
    S["tte"] = S.t_end - S.t
    E = S[ended & (S.age >= 60)]
    base = S[~ended & (S.age >= 60)]
    edges = np.array([0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 10])
    mid = (edges[:-1] + edges[1:]) / 2
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.9))
    for ax, col, lab in ((axes[0], "dv", "|Δ v_over_ground| per record (m/s)"), (axes[1], "dx", "|Δ dRel - vRel·Δt| per record (m)")):
        for q, p, c in (("mean", "mean", S1), (0.99, "p99", S2)):
            f = (lambda z: z.mean()) if q == "mean" else (lambda z, q=q: z.quantile(q))
            vals = [f(E[(E.tte >= a) & (E.tte < b)][col]) for a, b in zip(edges[:-1], edges[1:])]
            ax.plot(mid, vals, marker="o", ms=4, color=c, label=f"{p}, tracks about to end")
            ax.axhline(f(base[col]), color=c, lw=1, ls=":")
        ax.set_xscale("log")
        ax.set_xlabel("time until the track disappears (s)")
        ax.set_ylabel(lab)
        ax.legend(fontsize=7.5)
    axes[0].set_title("Velocity jumps before a track dies")
    axes[1].set_title("Range inconsistency before a track dies")
    for fld, c in (("UNK_256_5", S1), ("UNK_264_5", S2)):
        vals = [E[(E.tte >= a) & (E.tte < b)][fld].mean() for a, b in zip(edges[:-1], edges[1:])]
        axes[2].plot(mid, vals, marker="o", ms=4, color=c, label=fld)
        axes[2].axhline(base[fld].mean(), color=c, lw=1, ls=":")
    axes[2].set_xscale("log")
    axes[2].set_xlabel("time until the track disappears (s)")
    axes[2].set_ylabel("mean raw code")
    axes[2].set_title("256|5 falls and 264|5 rises before a track dies")
    axes[2].legend(fontsize=7.5)
    save(fig, "track_end_behaviour", "EXPLORATORY (not pre-registered). Dotted = same statistic on settled tracks that do not end in the file. "
                                     "Settled tracks only; all drives.")


def field_correlations():
    C = _pairs_with_error()
    S = load("slots")
    C["tk"] = (C.t_r * 1000).round().astype("int64")
    S = S.assign(tk=(S.t * 1000).round().astype("int64"))
    fields = [c for c in S.columns if c.startswith("UNK_")] + ["ALONG_LIKE_84", "VLAT_OVER_GROUND_PROV"]
    J = C[["drive", "seg", "track", "tk", "e", "x", "y", "age", "v_ego"]].merge(S[["seg", "track", "tk"] + fields], on=["seg", "track", "tk"])
    J["abs_e"] = J.e.abs()
    J["rbin"] = (J.x // 20).astype(int)
    cols, M = [], []
    for d in "ABC":
        q = J[J.drive == d]
        for tgt, lab in (("abs_e", "|vRel err|"), ("x", "range"), ("age", "age"), ("v_ego", "ego speed")):
            cols.append(f"{d}: {lab}")
            M.append([q[f].rank().corr(q[tgt].rank()) if q[f].nunique() > 1 else np.nan for f in fields])
        # |error| within 20 m range bins (range-controlled), averaged over bins
        per = []
        for f in fields:
            r = [b[f].rank().corr(b.abs_e.rank()) for _, b in q.groupby("rbin") if len(b) > 200 and b[f].nunique() > 1]
            per.append(np.nanmean(r) if r else np.nan)
        cols.append(f"{d}: |err| in range bins")
        M.append(per)
    M = np.array(M).T
    fig, ax = plt.subplots(figsize=(12, 0.26 * len(fields) + 2))
    im = ax.imshow(M, cmap=DIVERGE, vmin=-0.8, vmax=0.8, aspect="auto")
    ax.set_yticks(range(len(fields)), fields, fontsize=7.5)
    ax.set_xticks(range(len(cols)), cols, rotation=45, ha="right", fontsize=8)
    ax.grid(False)
    for k in range(1, 3):
        ax.axvline(5 * k - 0.5, color=SURFACE, lw=3)
    fig.colorbar(im, ax=ax, label="Spearman rho", shrink=0.6)
    ax.set_title("Candidate slot fields vs the radar's velocity error: strong ties to range / age / speed,\nat most weak (|rho| <= 0.2) to the error once range is controlled (last column of each drive)")
    save(fig, "candidate_field_correlations", "Settled camera-paired rows. |err| = |native vRel - camera box growth|.")


def range_walk():
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.8), sharey=True)
    w = 0.36
    for ax, d in zip(axes, "ABC"):
        r = summary(f"teacher_independence_{d}")["range_short_term_consistency_camera"]
        bands = [b for b in ("5-40", "40-80", "80-160") if b in r]
        for i, (key, lab, col) in enumerate((("range_change_err_m_p50_p90", "radar range change", S2), ("integrated_vrel_err_m_p50_p90", "integrated native vRel", S1))):
            p50 = [r[b][key][0] for b in bands]
            p90 = [r[b][key][1] for b in bands]
            xx = np.arange(len(bands)) + (i - 0.5) * w
            ax.bar(xx, p50, width=w - 0.04, color=col, label=f"{lab} (median)")
            ax.scatter(xx, p90, marker="_", s=180, color=col, lw=2, label=f"{lab} (p90)")
        ax.set_xticks(range(len(bands)), [f"{b} m" for b in bands])
        ax.set_title(f"drive {DRIVE_NAME[d]}")
    axes[0].set_ylabel("disagreement with camera size ratio over 1.5 s (m)")
    axes[0].legend(fontsize=7.5, loc="upper left")
    save(fig, "range_walk_vs_integrated_vrel", "Scale-free test: the camera box-height ratio over 1.5 s needs no calibration. "
                                               "Radar range changes are 2-4x less consistent than integrating the radar's own velocity.")


# ---------------------------------------------------------------- openpilot consumer ---------------------------------
def brake_events():
    evs = [("E3", "E3: real closing in a curve"), ("E4", "E4: real closing + range walk"), ("E2", "E2: velocity excursion (control)")]
    fig, axes = plt.subplots(3, 3, figsize=(13.5, 8.6), sharex="col")
    bdir = DATA / "brake_events"
    for k, (e, title) in enumerate(evs):
        W = pd.read_csv(bdir / f"{e}_replay_window.csv")
        R = pd.read_csv(bdir / f"{e}_radar_lead_track.csv")
        Cm = pd.read_csv(bdir / f"{e}_camera_pair.csv")
        a, b, c = axes[0, k], axes[1, k], axes[2, k]
        a.plot(W.dt, W.vision_l1_dRel, color=S2, lw=1.4, label="vision lead")
        a.plot(R.dt, R.dRel, ".", ms=2.5, color=S1, label="radar lead track")
        a.set_title(title)
        b.plot(W.dt, W.vision_l1_vLead - W.v_ego, color=S2, lw=1.4, label="vision")
        b.plot(R.dt, R.vRel, ".", ms=2.5, color=S1, label="radar native")
        if "v_cam" in Cm and Cm.v_cam.notna().any():
            b.plot(Cm.dt, Cm.v_cam, color=S3, lw=1.4, label="camera box growth")
        c.plot(W.dt, W.vision_aTarget, color=S2, lw=1.4, label="vision-only plan")
        c.plot(W.dt, W.openpilot_aTarget, color=S1, lw=1.4, label="plan with radar (OPENPILOT_CONFIG)")
        c.plot(W.dt, W.a_ego, color=INK2, lw=0.9, ls=":", label="recorded a_ego")
        c.set_xlabel("s relative to driver brake onset")
        for ax in (a, b, c):
            ax.axvline(0, color=INK, lw=0.8)
        if k == 0:
            a.set_ylabel("dRel (m)")
            b.set_ylabel("vRel (m/s)")
            c.set_ylabel("aTarget (m/s²)")
            for ax in (a, b, c):
                ax.legend(fontsize=7.5, loc="lower left")
    fig.suptitle("Offline replay through unmodified radard + longitudinal planner (drive A)", y=1.0)
    save(fig, "brake_events", "Open-loop: ego motion is as recorded. E3/E4: radar saw a real closing seconds before vision. "
                              "E2: a velocity excursion produced a spurious braking request.")


def defence_tradeoff():
    pts = [("OPENPILOT_CONFIG (no defence)", 4, 4, 12, 12), ("range-slope clip", 3, 4, 10, 12), ("far vRel smoothing", 1, 4, 8, 12),
           ("state-space filter", 1, 4, 6, 12), ("inverse-variance vision blend", 0, 4, 4, 12)]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.axvspan(-0.05, 0.5, ymin=0, ymax=1, color=S3, alpha=0.0)
    ax.fill_between([-0.05, 0.5], 0.8, 1.05, color=S3, alpha=0.12, lw=0)
    ax.text(0.02, 1.02, "pass region", color=INK2, fontsize=8.5, va="top")
    for name, c, c0, k, k0 in pts:
        x, y = c / c0, k / k0
        ax.scatter(x, y, s=70, color=S1, zorder=3, edgecolor=SURFACE, lw=1.5)
        ax.annotate(name, (x, y), xytext=(8, -3), textcoords="offset points", fontsize=8.5, color=INK)
    ax.set_xlim(-0.05, 1.25)
    ax.set_ylim(0.2, 1.05)
    ax.set_xlabel("camera-contradicted braking episodes remaining (held-out, share of 4)")
    ax.set_ylabel("camera-confirmed closings still braking within 1 s (share of 12)")
    ax.set_title("Every tested defence trades false brakes for late real brakes")
    save(fig, "defence_tradeoff", "Each rule was frozen on drive A and pre-registered before scoring on B + C.")


def fault_injection():
    F = pd.read_csv(DATA / "fault_injection.csv")
    F = F[F.drive == "A_engaged"]
    groups = [g for g in ("highway_follow", "city_follow", "stop_and_go") if g in set(F.group)]
    dys = ["1", "1.8", "3.6", "6"]
    fig, axes = plt.subplots(1, len(groups), figsize=(12, 3.8), sharey=True)
    for ax, grp in zip(np.atleast_1d(axes), groups):
        q = F[F.group == grp].set_index("scenario")
        for suffix, lab, col in (("with_true", "true lead also present", S1), ("true_missing", "true lead missing", S2)):
            vals = [q.loc[f"ghost_same_d_v_dy{d}_{suffix}", "ghost_chosen_as_lead_share_of_injected"] if f"ghost_same_d_v_dy{d}_{suffix}" in q.index else np.nan for d in dys]
            ax.plot([float(d) for d in dys], vals, marker="o", ms=5, color=col, label=lab)
        ax.set_title(grp.replace("_", " "))
        ax.set_xlabel("ghost lateral offset from the vision lead (m)")
        ax.set_ylim(0, 1)
    np.atleast_1d(axes)[0].set_ylabel("share of ticks radard picks the ghost")
    np.atleast_1d(axes)[0].legend(fontsize=8)
    fig.suptitle("radard has no lateral gate: a ghost at the lead's distance and speed wins at any offset if the real lead is missing", y=1.02)
    save(fig, "radard_lateral_gate")


def braking_census():
    E = pd.read_csv(DATA / "braking_episodes.csv")
    E = E[E.drive.isin(["B", "C"])]
    order = [("camera confirms closing", S3), ("camera ~steady (native overstated)", S4), ("CAMERA OPENING (contradicted)", "#e34948"),
             ("no camera pair", "#b9b8b2"), ("vision-led (planner history)", "#86b6ef")]
    fig, ax = plt.subplots(figsize=(10, 2.8))
    for i, d in enumerate(("B", "C")):
        left = 0
        for cls, col in order:
            n = int((E[E.drive == d].cls == cls).sum())
            if n:
                ax.barh(i, n, left=left, color=col, edgecolor=SURFACE, lw=2, height=0.6, label=cls if i == 0 or d == "C" else None)
                ax.text(left + n / 2, i, str(n), ha="center", va="center", fontsize=8.5, color=INK)
                left += n
    ax.set_yticks([0, 1], ["drive B (city, 41.9 forced min)", "drive C (highway, 24 forced min)"])
    ax.set_xlabel("native-only braking episodes (plan <= -1 m/s² with radar, >= -0.3 vision-only)")
    h, l = ax.get_legend_handles_labels()
    seen = dict(zip(l, h))
    ax.legend(seen.values(), seen.keys(), fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.35))
    ax.set_title("What radar-only braking episodes turned out to be (classified with camera box growth)")
    ax.grid(axis="y", visible=False)
    save(fig, "braking_episode_census")


FIGURES = {f.__name__: f for f in (bitmap, record_raster, vground_vs_ego, standstill_codes, lateral_hist, bev_density, ground_contact,
                                   lateral_scale, lifetimes, slot_gantt, age_convergence, vrel_hexbin, vrel_mse, tch_and_stationary,
                                   error_tails, excursion_gallery, track_end_behaviour, field_correlations, range_walk, brake_events,
                                   defence_tradeoff, fault_injection, braking_census)}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or list(FIGURES)
    failed = []
    for n in names:
        try:
            FIGURES[n]()
        except Exception as e:  # keep going; report at the end
            failed.append((n, repr(e)))
    for n, e in failed:
        print("FAILED", n, e)
    raise SystemExit(1 if failed else 0)
