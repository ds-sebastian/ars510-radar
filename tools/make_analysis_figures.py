#!/usr/bin/env python3
"""Regenerate docs/img/analysis/*.png from the shipped dataset in data/analysis (needs pandas, pyarrow, matplotlib).

Every analysis chart in docs/ comes from this script, so anyone can reproduce or re-slice them.
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
    a1.text(3.8, 0.5, "age 60 = publish\n(all profiles)", fontsize=8, color=INK2)
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
        c.plot(W.dt, W.openpilot_aTarget, color=S1, lw=1.4, label="plan with radar (raw profile)")
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


def age_convergence():
    C = load("camera_pairs")
    C = C[C.vcam2.notna() & C.x.between(3, 80)]
    bins = [(11, 25), (26, 50), (51, 80), (81, 125), (126, 126)]
    labels = [f"{a}-{b}" if a != b else "126 (sat.)" for a, b in bins]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
    w = 0.26

    def cls(v, v_ego):  # direction of travel over ground: 1 same way, 0 stopped, -1 oncoming
        return np.where(v > np.maximum(2.0, 0.2 * v_ego), 1, np.where(v < -np.maximum(2.0, 0.2 * v_ego), -1, 0))

    for i, (d, g) in enumerate(C.groupby("drive")):
        med, agree = [], []
        for a, b in bins:
            q = g[g.age.between(a, b)]
            med.append(np.median(np.abs(q.vrel - q.vcam2)) if len(q) > 20 else np.nan)
            agree.append(np.mean(cls(q.v_ground, q.v_ego) == cls(q.v_ego + q.vcam2, q.v_ego)) if len(q) > 20 else np.nan)
        a1.bar(np.arange(len(bins)) + (i - 1) * w, med, width=w - 0.03, color=DRIVE_COL[d], label=f"drive {d}")
        a2.plot(range(len(bins)), agree, marker="o", ms=5, color=DRIVE_COL[d], label=f"drive {d}")
    a1.set_xticks(range(len(bins)), labels)
    a1.set_xlabel("track age (radar cycles, 60 ms)")
    a1.set_ylabel("median |vRel - camera closing speed| (m/s)")
    a1.set_title("Tracks converge over their first ~60 cycles")
    a1.legend()
    a2.set_xticks(range(len(bins)), labels)
    a2.set_xlabel("track age (radar cycles)")
    a2.set_ylabel("direction of travel agrees with camera")
    a2.set_title("Same way / stopped / oncoming")
    a2.set_ylim(0.7, 1.005)
    a2.legend()
    save(fig, "age_convergence", "Camera-paired rows (box-growth closing speed over 2 s) start at age ~11. Direction classes use ±max(2 m/s, 20% of ego speed).")


def vrel_mse():
    C = load("camera_pairs")
    C = C[C.vcam2.notna() & C.deriv1s.notna()]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.9), sharey=True)
    w = 0.27
    out = {}
    for ax, d in zip(axes, "ABC"):
        g = C[C.drive == d]
        rows = []
        for lo, hi in BANDS:
            q = g[g.x.between(lo, hi)]
            rows.append((np.mean((q.vrel - q.vcam2) ** 2), np.mean(q.vcam2 ** 2), np.mean((q.deriv1s - q.vcam2) ** 2), len(q)))
        out[d] = {f"{lo}-{hi}": dict(zip(("native", "zero", "range_derivative_1s", "n"), map(float, r))) for (lo, hi), r in zip(BANDS, rows)}
        for i, (lab, col) in enumerate((("native vRel", S1), ("constant 0", S2), ("1 s range derivative", S3))):
            ax.bar(np.arange(3) + (i - 1) * w, [r[i] for r in rows], width=w - 0.03, color=col, label=lab)
        ax.set_xticks(range(3), [f"{lo}-{hi} m" for lo, hi in BANDS])
        ax.set_yscale("log")
        ax.set_title(f"drive {DRIVE_NAME[d]}")
    axes[0].set_ylabel("MSE vs camera box growth ((m/s)², log)")
    axes[0].legend(loc="upper left")
    NUMBERS["vrel_mse"] = out
    save(fig, "vrel_mse_baselines", "All camera-paired samples with a 2 s box-growth reference (data/analysis/camera_pairs.parquet).")


def range_walk():
    """1.5 s range change vs the camera's scale-free box-height ratio, against integrating the radar's own vRel."""
    C = load("camera_pairs").sort_values(["drive", "seg", "cam_track", "track", "t_c"])
    res = []
    for (d, _, _, _), g in C.groupby(["drive", "seg", "cam_track", "track"]):
        if len(g) < 30:
            continue
        t, x, h, v = g.t_c.to_numpy(), g.x.to_numpy(), g.h.to_numpy(), g.vrel.to_numpy()
        j = np.searchsorted(t, t + 1.5)
        ok = (j < len(t))
        i = np.nonzero(ok)[0]
        j = j[ok]
        ok = np.abs(t[j] - t[i] - 1.5) < 0.1
        i, j = i[ok], j[ok]
        if not len(i):
            continue
        ct = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))])
        cam = (x[i] + 1.52) * h[i] / h[j] - 1.52
        res.append(pd.DataFrame({"drive": d, "x0": x[i], "err_range": np.abs(x[j] - cam), "err_int": np.abs(x[i] + ct[j] - ct[i] - cam)}))
    R = pd.concat(res)
    bands = [(5, 40), (40, 80), (80, 160)]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.8), sharey=True)
    w = 0.36
    out = {}
    for ax, d in zip(axes, "ABC"):
        g = R[R.drive == d]
        out[d] = {}
        for i, (key, lab, col) in enumerate((("err_range", "radar range change", S2), ("err_int", "integrated vRel", S1))):
            p50, p90, xx = [], [], []
            for k, (lo, hi) in enumerate(bands):
                q = g[g.x0.between(lo, hi)][key]
                if len(q) < 50:
                    continue
                p50.append(q.median())
                p90.append(q.quantile(0.9))
                xx.append(k + (i - 0.5) * w)
                out[d].setdefault(f"{lo}-{hi}", {})[key] = [float(q.median()), float(q.quantile(0.9)), int(len(q))]
            ax.bar(xx, p50, width=w - 0.04, color=col, label=f"{lab} (median)")
            ax.scatter(xx, p90, marker="_", s=180, color=col, lw=2, label=f"{lab} (p90)")
        ax.set_xticks(range(3), [f"{lo}-{hi} m" for lo, hi in bands])
        ax.set_title(f"drive {DRIVE_NAME[d]}")
    axes[0].set_ylabel("disagreement with camera size ratio over 1.5 s (m)")
    axes[0].legend(fontsize=7.5, loc="upper left")
    NUMBERS["range_walk"] = out
    save(fig, "range_walk_vs_integrated_vrel", "The camera box-height ratio over 1.5 s needs no calibration. "
                                               "Integrating the radar's velocity tracks it 2-4x better than the radar's own range change.")


# ---------------------------------------------------------------- slot field roles -----------------------------------
KIN, LIFE, LANE, CLS, UNC, RAW, CONST = "kinematics", "lifecycle & confidence", "lane assignment", "class & size", "uncertainty & quality", "raw, unnamed", "constant"
GROUP_COL = {KIN: S1, LIFE: S3, LANE: S2, CLS: "#8a5cd6", UNC: "#12a0b8", RAW: "#c9c8c2", CONST: SURFACE}
CONF_ALPHA = {"confirmed": 1.0, "likely": 0.62, "candidate": 0.32, "raw": 1.0, "const": 1.0}
# (start, length, label, group, confidence). Kept in sync with docs/03_slot_fields.md.
SLOT_FIELDS = [
    (0, 2, "state", LIFE, "likely"), (2, 6, "slot index", LIFE, "confirmed"), (8, 5, "startup", LIFE, "confirmed"),
    (13, 1, "", RAW, "raw"), (14, 1, "onc", LIFE, "confirmed"), (15, 1, "", RAW, "raw"), (16, 8, "score", LIFE, "likely"),
    (24, 7, "age", LIFE, "confirmed"), (31, 1, "", CONST, "const"), (32, 12, "dRel", KIN, "confirmed"),
    (44, 12, "yRel", KIN, "confirmed"), (56, 7, "length", CLS, "likely"), (63, 1, "", RAW, "raw"),
    (64, 10, "vx (ground)", KIN, "confirmed"), (74, 10, "vy (ground)", KIN, "likely"), (84, 10, "ax", KIN, "likely"),
    (94, 2, "", CONST, "const"), (96, 10, "ay", KIN, "likely"), (106, 1, "", RAW, "raw"), (107, 1, "c", LIFE, "candidate"),
    (108, 1, "", CONST, "const"), (109, 3, "motion", LIFE, "likely"), (112, 3, "", RAW, "raw"), (115, 8, "", RAW, "raw"),
    (123, 5, "", CONST, "const"), (128, 3, "lane", LANE, "confirmed"), (131, 4, "", RAW, "raw"), (135, 1, "", CONST, "const"),
    (136, 4, "cls conf", CLS, "candidate"), (140, 3, "cls alt", CLS, "likely"), (143, 5, "", CONST, "const"),
    (148, 4, "w R", LANE, "likely"), (152, 4, "w L", LANE, "likely"), (156, 4, "w ego", LANE, "likely"),
    (160, 3, "", CONST, "const"), (163, 3, "class", CLS, "likely"), (166, 2, "", RAW, "raw"), (168, 10, "flags", RAW, "raw"),
    (178, 3, "", CONST, "const"), (181, 1, "", RAW, "raw"), (182, 1, "", RAW, "raw"), (183, 1, "", RAW, "raw"),
    (184, 8, "score 2", UNC, "candidate"), (192, 8, "", RAW, "raw"), (200, 7, "σ head", UNC, "candidate"),
    (207, 1, "", CONST, "const"), (208, 6, "heading", KIN, "likely"), (214, 2, "", CONST, "const"),
    (216, 6, "width", CLS, "likely"), (222, 2, "", CONST, "const"), (224, 7, "σ dRel", UNC, "likely"),
    (231, 1, "", CONST, "const"), (232, 7, "σ yRel", UNC, "likely"), (239, 1, "", RAW, "raw"), (240, 7, "σ vx", UNC, "likely"),
    (247, 1, "", CONST, "const"), (248, 7, "σ vy", UNC, "likely"), (255, 1, "", CONST, "const"),
    (256, 8, "existence", UNC, "candidate"), (264, 8, "meas. state", UNC, "candidate"), (272, 5, "height?", CLS, "candidate"),
    (277, 11, "", RAW, "raw"),
]


def field_map():
    cover = np.zeros(288, int)
    for st, ln, *_ in SLOT_FIELDS:
        cover[st:st + ln] += 1
    assert (cover == 1).all(), "SLOT_FIELDS must tile the 288 slot bits exactly"
    from matplotlib.patches import Patch, Rectangle
    fig, ax = plt.subplots(figsize=(14, 6.6))
    ax.set_xlim(-0.5, 32.5)
    ax.set_ylim(9.35, -1.2)
    ax.axis("off")
    for st, ln, lab, grp, conf in SLOT_FIELDS:
        col, alpha = GROUP_COL[grp], CONF_ALPHA[conf]
        b = st
        while b < st + ln:
            row, c0 = divmod(b, 32)
            seg = min(st + ln, (row + 1) * 32) - b
            ax.add_patch(Rectangle((c0, row), seg, 0.86, facecolor=col, alpha=alpha, edgecolor="#8f8e89" if grp == CONST else "none", lw=0.6))
            if grp not in (RAW, CONST) and conf != "confirmed":
                ax.add_patch(Rectangle((c0, row), seg, 0.86, facecolor="none", edgecolor=col, lw=1.4))
            if lab and (seg >= 3 or (seg == ln and ln <= 2)):
                ax.text(c0 + seg / 2, row + 0.45, lab if seg >= len(lab) * 0.42 or seg == ln else lab[:3], ha="center", va="center",
                        fontsize=8.2 if seg >= 3 else 6.8, color=INK, fontweight="bold" if conf == "confirmed" else "normal")
            b += seg
    for row in range(9):
        ax.text(-0.7, row + 0.43, f"{32 * row:>3}", ha="right", va="center", fontsize=8, color=INK2)
        for k in range(1, 4):
            ax.plot([8 * k, 8 * k], [row - 0.04, row + 0.9], color="#8f8e89", lw=0.8)
    for c in range(0, 32, 4):
        ax.text(c + 0.5, -0.35, str(c), ha="center", fontsize=7.5, color=INK2)
    ax.text(-0.7, -0.35, "bit", ha="right", fontsize=7.5, color=INK2)
    handles = [Patch(facecolor=GROUP_COL[g], edgecolor="#8f8e89" if g == CONST else "none", label=g) for g in (KIN, LIFE, LANE, CLS, UNC, RAW, CONST)]
    handles += [Patch(facecolor="#9b9a95", edgecolor="none", label="confirmed (solid, bold label)"),
                Patch(facecolor=(0.61, 0.60, 0.58, 0.62), edgecolor="#6f6e6a", lw=1.4, label="likely (lighter, outlined)"),
                Patch(facecolor=(0.61, 0.60, 0.58, 0.32), edgecolor="#6f6e6a", lw=1.4, label="candidate (pale, outlined)")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=5, fontsize=8.5)
    ax.set_title("The 0x80 object slot: 36 bytes = 288 bits, read as one little-endian integer (bit 0 = LSB of slot byte 0; one row = 4 bytes)",
                 fontsize=11, pad=4)
    save(fig, "field_map")


def _weights(S):
    w = S.UNK_148_8.to_numpy().astype(int)
    return np.stack([w & 15, S.UNK_156_4.to_numpy().astype(int), w >> 4], 1)  # right, ego, left


def lane_weights():
    S = settled()
    S = S[S.x.between(5, 120)]
    W = _weights(S)
    nz = W.sum(1) > 0
    S, W = S[nz], W[nz]
    dom = W.argmax(1)
    names, cols = ("right lane (148|4)", "ego lane (156|4)", "left lane (152|4)"), (S2, S1, S3)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.3), gridspec_kw={"width_ratios": [1.25, 1]})
    bins = np.arange(-8, 8.01, 0.1)
    for k in range(3):
        a1.hist(S.y[dom == k], bins=bins, color=cols[k], alpha=0.75, label=names[k])
    a1.set_xlabel("yRel (m, left positive)")
    a1.set_ylabel("settled samples")
    a1.set_title("Which weight dominates, by lateral position")
    a1.legend(fontsize=8)
    yb = np.arange(-7, 7.01, 0.25)
    idx = np.digitize(S.y, yb)
    frac = W / W.sum(1, keepdims=True)
    for k in range(3):
        m = [frac[idx == i, k].mean() if (idx == i).sum() > 30 else np.nan for i in range(1, len(yb))]
        a2.plot(0.5 * (yb[1:] + yb[:-1]), m, color=cols[k], lw=2.2, label=names[k].split(" (")[0])
    a2.set_xlabel("yRel (m, left positive)")
    a2.set_ylabel("mean weight share (weights / their sum)")
    a2.set_title("Soft hand-over at the lane edges")
    a2.legend(fontsize=8)
    NUMBERS["lane_weights"] = {names[k]: {"median_y": float(np.median(S.y[dom == k])), "n": int((dom == k).sum())} for k in range(3)}
    NUMBERS["lane_weights"]["sum_15_or_16_share"] = float(np.isin(W.sum(1), (15, 16)).mean())
    save(fig, "lane_weights", "Settled tracks, 5-120 m, all drives, rows with a nonzero triplet. The three nibbles sum to 15 or 16.")


CLASS_RECODE_140 = {0: 1, 5: 2, 7: 3, 1: 4, 3: 5, 4: 6}  # 140|3 -> 163|3


def object_size():
    S = settled()
    c140 = pd.Series((S.UNK_136_6.to_numpy().astype(int) >> 4) | (S.UNK_142_1.to_numpy().astype(int) << 2), index=S.index)
    S = S.assign(cls=c140.map(CLASS_RECODE_140), width=(S.UNK_216_6 + 1) * 0.1, length=S.UNK_56_7 * 0.1, speed=np.abs(S.v_ground))
    T = S.groupby(["drive", "seg", "track"]).agg(cls=("cls", lambda c: c.mode().iat[0]), width=("width", "median"),
                                                 length=("length", "median"), n=("age", "size")).reset_index()
    T = T[T.n >= 20]
    meta = {2: ("2: car", S1), 3: ("3: large vehicle", S2), 4: ("4: pedestrian", S3), 6: ("6: two-wheeler", "#8a5cd6")}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.6), gridspec_kw={"width_ratios": [1.2, 1]})
    rng = np.random.default_rng(0)
    for c, (lab, col) in meta.items():
        q = T[T.cls == c]
        if len(q):
            a1.scatter(q.length + rng.uniform(-0.04, 0.04, len(q)), q.width + rng.uniform(-0.04, 0.04, len(q)), s=10, alpha=0.5,
                       color=col, lw=0, label=f"{lab} ({len(q)} tracks)")
    a1.set_xlabel("56|7 x 0.1 m (length-like), per-track median")
    a1.set_ylabel("(216|6 + 1) x 0.1 m (width-like), per-track median")
    a1.set_title("Each class code has its own footprint")
    leg = a1.legend(fontsize=8, markerscale=2.5)
    for lh in leg.legend_handles:
        lh.set_alpha(1)
    out = {}
    for c, (lab, col) in meta.items():
        q = S[S.cls == c]
        if len(q) > 50:
            out[lab] = {"rows": int(len(q)), "median_width_m": float(q.width.median()), "median_length_m": float(q.length.median()),
                        "median_speed_mps": float(q.speed.median())}
    share = S.cls.value_counts(normalize=True).sort_index()
    a2.bar([str(int(k)) for k in share.index], share.values, color=[meta.get(int(k), ("", "#b9b8b2"))[1] for k in share.index])
    a2.set_yscale("log")
    a2.set_xlabel("class code 163|3 (1 = not yet classified)")
    a2.set_ylabel("share of settled samples (log)")
    a2.set_title("How often each class occurs")
    NUMBERS["object_size"] = out
    save(fig, "object_size", "Settled tracks on drives A-C. 140|3 is a fixed recoding of 163|3 and is used here because the bundled table predates the 163|3 view.")


def track_lifecycle():
    S = load("slots").sort_values("t")
    best = None
    for (d, seg, tr), g in S.groupby(["drive", "seg", "track"]):
        if g.age.min() == 1 and g.age.max() == 126 and (g.UNK_0_2.tail(15) == 2).any() and 20 < g.t.max() - g.t.min() < 40:
            best = g
            break
    g = best
    t = g.t - g.t.min()
    score = g.UNK_16_1 + 2 * g.UNK_17_1 + 4 * g.UNK_18_2 + 16 * g.UNK_20_3
    motion = g.UNK_109_2.to_numpy().astype(int) | ((g.UNK_111_4.to_numpy().astype(int) & 1) << 2)
    fig, axes = plt.subplots(4, 1, figsize=(12, 7.6), sharex=True, gridspec_kw={"height_ratios": [1.2, 1.2, 0.8, 1]})
    axes[0].plot(t, g.age, color=S1, label="age 24|7 (saturates at 126)")
    axes[0].plot(t, g.UNK_8_6.to_numpy().astype(int) & 31, color=S2, label="startup code 8|5 (decays 30, 20, 13 ... while initializing)")
    axes[0].axvline(t[g.age >= 60].min(), color=INK2, ls=":", lw=1)
    axes[0].text(t[g.age >= 60].min() + 0.2, 100, "age 60: published\n(all profiles)", fontsize=8, color=INK2)
    axes[0].legend(fontsize=8, loc="center right")
    axes[1].plot(t, score, color=S3, label="score 16|8 (existence-like raw code)")
    axes[1].set_ylim(0, 105)
    axes[1].legend(fontsize=8, loc="lower left")
    axes[2].step(t, g.UNK_0_2, where="post", color=INK, label="state 0|2 (1 active, 2 coasting-like)")
    axes[2].set_yticks([1, 2])
    axes[2].legend(fontsize=8, loc="upper left")
    axes[3].plot(t, g.x, color=S1, label="dRel (m)")
    a3 = axes[3].twinx()
    a3.step(t, motion, where="post", color=S2, lw=1.2)
    a3.set_ylabel("motion code 109|3", color=S2)
    a3.set_yticks([0, 1, 5, 7])
    a3.grid(False)
    axes[3].legend(fontsize=8, loc="upper left")
    axes[3].set_xlabel("time since the track was born (s)")
    axes[0].set_title(f"One object's life in the slot: birth, settling, coasting and deletion (drive {g.drive.iat[0]})")
    save(fig, "track_lifecycle", "Motion code 5 = initializing, 0 = moving forward, 1 = slow, 7 = stopped after moving. "
                                 "In this example, state 2 accompanies score drops of 20 per cycle before retirement.")


def heading_field():
    S = settled()
    vx = (S.VLONG_OVER_GROUND - 510.5) * 0.15
    vy = (S.VLAT_OVER_GROUND_PROV - 510.5) * 0.15
    m = np.hypot(vx, vy) > 5
    pred = np.clip(np.floor(np.maximum(np.arctan2(vy, vx), 0) * 64 / np.pi), 0, 63)[m]
    code = S.UNK_208_6[m]
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    h = ax.hist2d(pred, code, bins=[np.arange(-0.5, 64), np.arange(-0.5, 64)], cmap=BLUES, norm=LogNorm(), cmin=1)
    fig.colorbar(h[3], ax=ax, label="settled samples")
    ax.plot([0, 63], [0, 63], color=S2, lw=1, ls="--")
    ax.set_xlabel("floor(max(atan2(vy, vx), 0) x 64 / π) from 64|10 and 74|10")
    ax.set_ylabel("208|6 code")
    ax.set_title("208|6 closely follows the clipped velocity angle\n(empirical comparison; approximately π/64 per code)")
    NUMBERS["heading"] = {"exact": float((pred == code).mean()), "within_one": float((np.abs(pred - code) <= 1).mean()), "n": int(m.sum())}
    save(fig, "heading_field", "Settled tracks moving faster than 5 m/s under nominal velocity scaling.\n"
         "Exact inputs, state updates and angular calibration remain provisional.")


def event_code_context():
    info = summary("event_pair_carries")
    g = pd.DataFrame(info["exception"]["context"]["samples"])
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 5.7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    axes[0].step(g.time_s, g.q10, where="post", color=S1)
    axes[0].scatter(g.time_s, g.q10, color=S1, s=13, zorder=3)
    axes[0].axhline(info["raw_idle_code"], color=INK2, ls="--", lw=1,
                   label="code in the exact idle payload")
    axes[0].axvline(0, color=S2, lw=1)
    axes[0].annotate("436 → 510\nsame high prefix", xy=(0, 510), xytext=(0.13, 463),
                     arrowprops={"arrowstyle": "->", "color": S2}, color=S2)
    axes[0].set_ylabel("0x195 10-bit raw code")
    axes[0].set_title("The raw code can reach 510 while the whole event payload remains non-idle")
    axes[0].legend(loc="lower left")
    axes[1].step(g.time_s, g.exact_idle_payload.astype(int), where="post", color=S3)
    axes[1].set_yticks([0, 1], ["other", "exact idle"])
    axes[1].set_ylim(-.15, 1.15)
    axes[1].axvline(0, color=S2, lw=1)
    axes[1].set_xlabel("CAN log time relative to the code jump (s)")
    axes[1].set_ylabel("whole payload")
    fig.tight_layout()
    save(fig, "event_code_context", "Original CAN verifies the complete window. Both jump endpoints have non-idle "
         "0x195 / 0x196 payloads; physical units, target identity and acquisition timing remain uncalibrated.")


def initial_attribute_zeros():
    info = summary("initial_attribute_zeros")
    g = pd.DataFrame(info["example"]["samples"])
    fig, axes = plt.subplots(2, 3, figsize=(10.2, 5.4), sharex=True)
    fields = [("confidence_like", "Confidence-like 136|4", S1),
              ("length_code", "Length 56|7", S2),
              ("width_code", "Width 216|6", S3),
              ("height_full_code", "Full height-like byte 272|8", S4),
              ("range_code", "Forward position 32|12", S1),
              ("lateral_code", "Lateral position 44|12", S2)]
    for ax, (field, title, color) in zip(axes.flat, fields):
        ax.axvspan(.8, 1.2, color=GRID, alpha=.8)
        ax.step(g.age, g[field], where="post", color=color)
        ax.scatter(g.age, g[field], color=color, s=26, zorder=3)
        for age, value in zip(g.age, g[field]):
            ax.annotate(str(int(value)), (age, value), xytext=(0, 7), textcoords="offset points",
                        ha="center", fontsize=8, color=INK2)
        ax.set_title(title)
        ax.set_ylabel("raw code")
        ax.set_xticks(g.age)
        ax.margins(x=.14, y=.22)
    for ax in axes[1]:
        ax.set_xlabel("native age code")
    fig.suptitle("A joint initial output precedes populated attributes and position", fontsize=12)
    fig.tight_layout()
    save(fig, "initial_attribute_zeros", "Example A, original-CAN checked. The initial tuple occurs on 5,774 "
         "of 22,501 age-1 rows; it is not a measured object box or a physical zero calibration. "
         "Full byte272 is a structural view, not a calibrated height measurement.")


def id85_direction_code_structure():
    info = summary("id85_direction_code_structure")
    g = pd.DataFrame(info["example"]["samples"])
    fig, axes = plt.subplots(3, 1, figsize=(8.5, 6.4), sharex=True)
    fields = [("signed_view_code", "Two's-complement view\n(raw code)", S1),
              ("lower15_code", "Lower 15 bits\n(raw code)", S2),
              ("future_ego_heading_delta_mrad", "Future ego-path H(16 m)\nchange (mrad)", S3)]
    for ax, (field, label, color) in zip(axes, fields):
        ax.plot(g.time_s, g[field], color=color, marker="o", markersize=3)
        ax.axvline(0, color=INK2, ls=":", lw=1)
        ax.set_ylabel(label)
    axes[0].set_title("Cell 2: a high-bit transition beside a smoothly changing ego path")
    axes[-1].set_xlabel("CAN log time relative to the transition (s)")
    fig.tight_layout()
    save(fig, "id85_direction_code_structure", "Example A; transition endpoints checked in original CRC-valid records. "
         "Lower bits are structural only; the ego path does not identify the selected boundary.")


def lane_curve_cells():
    """The 12-byte 0x85 cell as a lane / road-curve polynomial: layout strip plus heading and curvature against references."""
    L = load("lane_cells")
    info = summary("id85_lane_curve_cells")
    fig = plt.figure(figsize=(10.5, 7.6))
    gs = fig.add_gridspec(2, 3, height_ratios=[0.5, 2.2], hspace=0.42, wspace=0.32)
    ax = fig.add_subplot(gs[0, :])
    fields = [(0, 30, "0|9 …(raw, unresolved)", "#d9d8d3"), (30, 1, "30", S3), (32, 12, "32|12  c0 offset", S1), (48, 16, "48|16  c1 heading", S2),
              (64, 15, "64|15  c2 curvature", S4), (79, 1, "79", S5), (80, 16, "80|6 …", "#d9d8d3")]
    for start, ln, label, col in fields:
        ax.barh(0, ln, left=start, color=col, edgecolor=SURFACE, height=0.7)
        if ln >= 12:
            ax.text(start + ln / 2, 0, label, ha="center", va="center", fontsize=8.5, color=INK)
    ax.text(30.5, 0.62, "30: parameters present", ha="center", fontsize=7.5, color=INK2)
    ax.text(79.5, 0.62, "79: flag", ha="center", fontsize=7.5, color=INK2)
    ax.set_xlim(0, 96); ax.set_ylim(-0.6, 0.9); ax.set_yticks([]); ax.grid(False)
    ax.set_xticks(range(0, 97, 8)); ax.set_xlabel("bit within the 12-byte cell payload (little endian)")
    ax.set_title("A populated 0x85 cell is one lane / road-boundary curve: y(x) = c0 + c1·x + c2·x²/2")

    def binned(x, y, n=24):
        d = pd.DataFrame({"x": x, "y": y}).dropna()
        d["b"] = pd.qcut(d.x, n, duplicates="drop")
        g = d.groupby("b", observed=True).agg(x=("x", "median"), y=("y", "mean"), lo=("y", lambda v: v.quantile(.25)), hi=("y", lambda v: v.quantile(.75)))
        return g

    cols = {2: S1, 3: S2, 8: S3, 9: S4}
    ax1 = fig.add_subplot(gs[1, 0])
    for c, col in cols.items():
        q = L[L.cell == c]
        g = binned(q.heading_code, q.cam_slope)
        ax1.plot(g.x, g.y, color=col, marker="o", markersize=3, label=f"cell {c}")
    x = np.linspace(30000, 32600, 50)
    ax1.plot(x, -1.8e-5 * (x - 31200), color=INK, ls="--", lw=1, label="−1.8e-5 · (code − 31200)")
    ax1.set_xlabel("heading code (48|16)"); ax1.set_ylabel("camera lane slope, left positive (rad)")
    ax1.set_title("Heading vs camera lane slope"); ax1.legend(fontsize=7.5, loc="upper right")

    ax2 = fig.add_subplot(gs[1, 1])
    for c, col in cols.items():
        q = L[(L.cell == c) & (L.motion_slope.abs() < 0.2)]
        g = binned(q.heading_code, q.motion_slope, 20)
        ax2.plot(g.x, g.y, color=col, marker="o", markersize=3, label=f"cell {c}")
    ax2.plot(x, -1.8e-5 * (x - 31230), color=INK, ls="--", lw=1)
    ax2.set_xlabel("heading code (48|16)"); ax2.set_ylabel("d(offset)/d(distance driven) (m/m)")
    ax2.set_title("Heading vs the cell's own offset rate")

    ax3 = fig.add_subplot(gs[1, 2])
    for c, col in cols.items():
        for fl, mk in ((0, "s"), (1, "o")):
            q = L[(L.cell == c) & (L.flag79 == fl)]
            if len(q) < 500:
                continue
            g = binned(q.curv_code, q.cam_curv, 16)
            ax3.plot(g.x, g.y, color=col, marker=mk, markersize=3, lw=1.2, label=f"cell {c}, bit 79 = {fl}")
    x2 = np.linspace(14400, 17600, 50)
    ax3.plot(x2, 2.5e-6 * (x2 - 16020), color=INK, ls="--", lw=1, label="+2.5e-6 · (code − 16020)")
    ax3.set_xlabel("curvature code (64|15)"); ax3.set_ylabel("camera lane curvature, left positive (1/m)")
    ax3.set_title("Curvature vs camera lane curvature"); ax3.legend(fontsize=6.5, ncol=2, loc="upper left")
    ch = info["camera_reference"]["heading"]; cc = info["camera_reference"]["curvature"]
    save(fig, "lane_curve_cells", f"{len(L):,} camera-matched cell rows from three drives. Camera reference: quadratic fit of the matched lane line over 0–40 m. Units are "
         f"bounded, not pinned (heading 1.6–2.2e-5 rad/code, curvature 2.0–2.7e-6 1/m per code). The camera lane slope has about half the gain of the ego-motion offset rate; dashed lines are the nominal conversions. Correlations with the camera: heading "
         f"{min(v['corr'] for v in ch.values()):.2f}…{max(v['corr'] for v in ch.values()):.2f}, curvature {min(v['corr'] for v in cc.values()):.2f}…{max(v['corr'] for v in cc.values()):.2f}.")


def excursion_sigma_scale():
    """Native-minus-ACC velocity error against the reported 240|7 code, and observed vs Gaussian-predicted excursion incidence."""
    info = summary("excursion_sigma_scale")
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 4.3))
    for key, col, lab in (("corpus_700_segments", S1, "development + held-out drives"), ("fresh_114_segments", S2, "fresh drives")):
        r = info[key]["rms_by_code"]
        x = [v["code"] for v in r.values() if v["n"] >= 70]; y = [v["rms"] for v in r.values() if v["n"] >= 70]
        a.plot(x, y, marker="o", color=col, label=lab)
    xx = np.linspace(5, 100, 50); a.plot(xx, 0.045 * xx, color=INK, ls="--", lw=1, label="0.045 m/s × code")
    a.set_xlabel("240|7 code (mean in bin)"); a.set_ylabel("RMS of native vRel − ACC speed (m/s)"); a.set_title("Velocity error follows the reported uncertainty"); a.legend()
    cells = info["corpus_700_segments"]["incidence_cells"]
    for (k, v), c in zip(cells.items(), [S1, S1, S1, S1, S2, S2, S2, S2, S3, S3, S3, S3, S4, S4, S4, S4]):
        b.scatter(v["pred"] * 100, v["obs"] * 100, color=c, s=28)
    b.plot([0, 25], [0, 25], color=INK, ls=":", lw=1)
    for lab, c in (("40–55 m", S1), ("55–70 m", S2), ("70–85 m", S3), ("85–110 m", S4)): b.scatter([], [], color=c, label=lab)
    b.set_xlabel("predicted excursion rate (%), Gaussian σ = 0.045 × code"); b.set_ylabel("observed rate (%)"); b.set_title("Excursion incidence per range band and code quartile"); b.legend(loc="upper left")
    fig.tight_layout()
    save(fig, "excursion_sigma_scale", "Matched to the radar's own ACC target (227 k development/held-out records, 13 k fresh). Excursion = 9-record median of native − ACC below −2.5 m/s. "
         "ACC reference error (about 0.6 m/s) is included in the RMS; kurtosis beyond 2.5σ exceeds Gaussian.")


def video_truth_excursions():
    rows = summary("video_truth")["object_list_vs_optical_2s_windows"]
    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    ax.bar(x - .18, [r["closing_disagreement_pct"] for r in rows], .36,
           label="Native more closing than ECC by >2.5 m/s", color=S2)
    ax.bar(x + .18, [r["opening_disagreement_pct"] for r in rows], .36,
           label="Native more opening than ECC by >2.5 m/s", color=S1)
    ax.set_xticks(x, [f"{r['range_m'][0]}–{r['range_m'][1]}" for r in rows])
    ax.set_xlabel("Native range (m)")
    ax.set_ylabel("Share of two-second windows (%)")
    ax.set_title("Object-list velocity disagreement with the optical reference")
    ax.legend(loc="upper left")
    fig.tight_layout()
    save(fig, "video_truth_excursions", "2,657 selected windows; ECC metric scale uses native range. Conditional disagreement, not physical error.")


NUMBERS: dict = {}
FIGURES = {f.__name__: f for f in (record_raster, field_map, vground_vs_ego, standstill_codes, lateral_hist, bev_density, ground_contact,
                                   lateral_scale, lifetimes, slot_gantt, track_lifecycle, lane_weights, object_size, heading_field,
                                   age_convergence, vrel_hexbin, vrel_mse, range_walk, brake_events, fault_injection,
                                   event_code_context, initial_attribute_zeros, id85_direction_code_structure, lane_curve_cells, excursion_sigma_scale, video_truth_excursions)}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or list(FIGURES)
    failed = []
    for n in names:
        try:
            FIGURES[n]()
        except Exception as e:  # keep going; report at the end
            failed.append((n, repr(e)))
    if NUMBERS:
        (DATA / "summaries" / "figure_numbers.json").write_text(json.dumps(NUMBERS, indent=1) + "\n")
    for n, e in failed:
        print("FAILED", n, e)
    raise SystemExit(1 if failed else 0)
