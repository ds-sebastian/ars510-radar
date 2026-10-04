#!/usr/bin/env python3
"""Figures for the fused speed filter and the profile comparison against vision only.

    python tools/make_fused_figures.py      # writes docs/img/analysis/fused_*.png and profiles_vs_vision.png

fused_how_it_works.png is computed from ars510 itself (FUSED_CONFIG on synthetic leads). fused_scenarios_*.png plot
data/analysis/fused_scenarios.csv.gz: six real-drive moments replayed through the unchanged openpilot / sunnypilot
planner (times relative to the moment, no route identifiers). profiles_vs_vision.png plots
data/analysis/summaries/profiles_vs_vision.json; kalman_variants.png plots data/analysis/summaries/kalman_variants.json.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from ars510 import FUSED_CONFIG, Ars510NativeRadarInterface  # noqa: E402
from ars510.objects import encode_slot  # noqa: E402
from make_profile_figures import INK, INK2, GRAY, S1, S2, S3, S4  # noqa: E402
from ars510.constants import ID80_IDLE_SLOT  # noqa: E402
import zlib  # noqa: E402


def speed(t: float, v_mps: float):
    """Toyota 0xB4 ego speed frame."""
    return t, 0, 0xB4, bytes(5) + round(v_mps * 3.6 / 0.01).to_bytes(2, "big") + b"\x00"


def frames_for_slot(slot: bytes, t: float) -> list:
    """One 0x80 record holding a single object in slot 0, split into its 106 CAN frames."""
    rec = bytearray(742); rec[0] = 0xE4
    for i in range(20):
        rec[17 + 36 * i:17 + 36 * (i + 1)] = slot if i == 0 else ID80_IDLE_SLOT
    rec[737:741] = (zlib.crc32(bytes(rec[1:737])) & 0xFFFFFFFF).to_bytes(4, "little")
    out = [(t, 1, 0x80, bytes([0x12]) + bytes(rec[0:7]))]
    out += [(t + 0.0001 * j, 1, 0x80, bytes([0x20]) + bytes(rec[7 * j:7 * j + 7])) for j in range(1, 106)]
    return out

OUT = REPO / "docs" / "img" / "analysis"
VIS, ANC, FUS, ACC, SUM = "#7a5fb0", S2, S3, INK, S4
SCENARIOS = {
    "S1": ("False closing rejected", "object list −4.8 m/s at 41 m; ACC target and summary −0.6"),
    "S2": ("Slowing lead seen early", "the ACC target shows the slowdown before the object list"),
    "S3": ("Over-estimated closing", "object list closing too fast; ACC target range ≈ −1.8 m/s"),
    "S4": ("Fast real closing", "a car closing at ~10 m/s from 60 m"),
    "S5": ("Far slot slide, no ACC target", "object list jumps to −13..−38 m/s at 80-110 m"),
    "S6": ("Stopping behind a car", "stop-and-go at under 15 m"),
}


def how_it_works() -> None:
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(13, 3.8))
    rng = np.arange(5, 121, 1.0)
    code = np.clip(0.7 * rng, 1, 126)  # 240|7 ≈ 0.7 per metre of range (docs/07)
    sig = FUSED_CONFIG.speed_sigma_per_code * code
    a1.plot(rng, sig, color=GRAY, label="object-list speed (0.045 × 240|7)")
    a1.plot(rng, sig * FUSED_CONFIG.young_sigma_scale, color=GRAY, ls=":", label="… young track (× 1.8)")
    a1.axhline(FUSED_CONFIG.acc_sigma_mps, color=ACC, ls="--", lw=1.2, label="ACC target speed")
    a1.plot([5, 80], [FUSED_CONFIG.summary_sigma_mps + 0.03] * 2, color=SUM, lw=1.2, label="summary speed (≤ 80 m)")
    a1.set_xlabel("range (m)"); a1.set_ylabel("reading std (m/s)"); a1.set_title("How much each reading is trusted")
    a1.legend(loc="upper left")
    # share of the estimate that comes from the radar's own trackers when they are present
    q = (FUSED_CONFIG.lead_accel_std_mps2 * 0.06) ** 2
    w_obj = 1 / sig ** 2; w_trk = 1 / FUSED_CONFIG.acc_sigma_mps ** 2
    a2.plot(rng, w_trk / (w_trk + w_obj), color=ACC, label="ACC target present")
    w2 = np.where(rng <= 80, 2 * w_trk, w_trk)
    a2.plot(rng, w2 / (w2 + w_obj), color=SUM, label="ACC target + summary")
    a2.set_ylim(0, 1.02); a2.set_xlabel("range (m)"); a2.set_ylabel("weight of the radar's trackers")
    a2.set_title("Near: object list. Far: the radar's trackers"); a2.legend(loc="lower right")
    # speed std vs age for a constant lead at three ranges (the publication gate)
    for d, color in ((20, S1), (60, S4), (90, S2)):
        cfg = replace(FUSED_CONFIG, min_publish_age=1, publish_speed_std_mps=99.0)
        radar = Ars510NativeRadarInterface(cfg)
        stds = []
        for k in range(120):
            t = 0.06 * k
            slot = encode_slot(long_dist=round(160 + d * 16), lat_dist_left=2048, long_vel_over_ground=round(510.5 + 20 / 0.15),
                               age_cycles=k + 1, vel_uncertainty_candidate=int(round(0.7 * d)))
            for fr in [speed(t, 20.0)] + frames_for_slot(slot, t + 0.002):
                radar.update_frame(*fr)
            st = radar._fused.get(next(iter(radar._fused), None))
            stds.append(st[2] ** 0.5 if st else np.nan)
        a3.plot(np.arange(1, 121), stds, color=color, label=f"{d} m")
    a3.axhline(FUSED_CONFIG.publish_speed_std_mps, color=INK, ls="--", lw=1.0)
    a3.axvline(60, color=GRAY, ls=":", lw=1.0)
    a3.text(62, FUSED_CONFIG.publish_speed_std_mps + 0.05, "publish below 0.75 m/s (and age ≥ 60)", fontsize=8, color=INK2)
    a3.set_ylim(0, 3); a3.set_xlabel("track age (frames, 60 ms)"); a3.set_ylabel("speed std (m/s)")
    a3.set_title("When a new track is published"); a3.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(OUT / "fused_how_it_works.png", dpi=130); plt.close(fig)


def scenarios() -> None:
    D = pd.read_csv(REPO / "data" / "analysis" / "fused_scenarios.csv.gz")
    for part, ids in (("a", ("S1", "S2", "S3")), ("b", ("S4", "S5", "S6"))):
        fig, axes = plt.subplots(2, 3, figsize=(13.5, 6.4), sharex="col", gridspec_kw={"height_ratios": [1.4, 1]})
        for col, sid in enumerate(ids):
            g = D[D.scenario == sid]; s = lambda name: g[g.series == name]
            av, aa = axes[0, col], axes[1, col]
            r = s("raw_vrel"); av.scatter(r.t, r.value, s=5, color=GRAY, label="object list (radar lead)", zorder=1)
            sm = s("summary_vrel")
            if len(sm) and len(r):
                near = np.interp(sm.t, r.t, r.value)
                sm = sm[np.abs(sm.value.to_numpy() - near) < 1.5]  # the parser's summary match (1.5 m/s)
            if len(sm):
                av.plot(sm.t, sm.value, color=SUM, lw=1.1, ls=":", label="radar summary (1 s slope)")
            for name, color, lab, kw in (("acc_vrel", ACC, "radar ACC target", dict(lw=1.1, ls="--")),
                                          ("vision_vrel", VIS, "vision lead", dict(lw=1.2)),
                                          ("fused_vrel", FUS, "fused", dict(lw=1.8))):
                x = s(name)
                if len(x): av.plot(x.t, x.value, color=color, label=lab, **kw)
            for name, color, lab in (("vision_a", VIS, "vision only"), ("fused_a", FUS, "fused")):
                x = s(name); aa.plot(x.t, x.value, color=color, label=lab, lw=1.6)
            title, sub = SCENARIOS[sid]
            av.set_title(f"{title}\n{sub}", fontsize=9.5)
            av.axvline(0, color=GRAY, lw=0.8); aa.axvline(0, color=GRAY, lw=0.8)
            aa.set_xlabel("time (s)")
            if col == 0:
                av.set_ylabel("lead vRel (m/s)"); aa.set_ylabel("planner request (m/s²)")
        axes[0, 0].legend(loc="lower left", fontsize=7.5); axes[1, 0].legend(loc="lower left", fontsize=7.5)
        fig.tight_layout(); fig.savefig(OUT / f"fused_scenarios_{part}.png", dpi=130); plt.close(fig)


def layers() -> None:
    """Which processing each profile applies (rows) and how many code lines each part takes (counted from ars510)."""
    import inspect
    from ars510.interface import Ars510NativeRadarInterface as I
    n = lambda *fs: sum(len(inspect.getsource(f).splitlines()) for f in fs)
    rows = [("validity, track IDs, ego subtraction", n(I._relink, I._fresh_ego_speed), (1, 1)),
            ("saturation guard", n(I._guard), (1, 0)),
            ("range fusion (gain 0.1)", n(I._fused_range), (0, 1)),
            ("ACC target: association", n(I._acc_target_match), (0, 1)),
            ("summary: association", n(I._summary_update, I._summary_speed, I._summary_match), (0, 1)),
            ("Kalman speed filter (σ from the radar)", n(I._fused_speed), (0, 1))]
    prof = ["raw", "fused (default)"]; colors = [GRAY, FUS]
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    for i, (name, lines, on) in enumerate(rows):
        y = len(rows) - 1 - i
        for j, flag in enumerate(on):
            ax.add_patch(plt.Rectangle((j + 0.08, y + 0.12), 0.84, 0.76, color=colors[j] if flag else "#efeee9", lw=0))
        ax.text(-0.1, y + 0.5, name, ha="right", va="center", fontsize=8.8)
        ax.text(2.1, y + 0.5, f"{lines} lines", ha="left", va="center", fontsize=8.3, color=INK2)
    ax.set_xlim(-0.05, 2.8); ax.set_ylim(0, len(rows)); ax.set_xticks([0.5, 1.5], prof); ax.xaxis.tick_top()
    ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.set_title("What each profile does to a track (after the shared 0x80 decode)", pad=26)
    fig.tight_layout(); fig.savefig(OUT / "profile_layers.png", dpi=130); plt.close(fig)


def vs_vision() -> None:
    S = json.loads((REPO / "data" / "analysis" / "summaries" / "profiles_vs_vision.json").read_text())
    ev, req = S["heldout_events"], S["heldout_one_system_requests_and_overrides"]
    prof = ["raw", "fused_no_trackers", "fused"]; colors = [GRAY, "#8fd9bb", FUS]
    names = ["raw", "fused,\nno ACC/summary", "fused\n(default)"]
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(13.5, 4.0))
    m = [ev[p]["onset_diff_mean_s"] for p in prof]; ci = np.array([ev[p]["onset_diff_ci"] for p in prof]).T
    a1.bar(names, m, color=colors, yerr=[np.array(m) - ci[0], ci[1] - np.array(m)], capsize=4)
    a1.axhline(0, color=INK, lw=0.8); a1.set_ylabel("onset vs vision only (s, < 0 = earlier)")
    a1.set_title(f"First braking request at {ev['fused']['events']} driver brakes")
    x = np.arange(len(prof))
    a2.bar(x - 0.2, [ev[p]["radar_ant05"] * 100 for p in prof], 0.4, color=colors, label="≤ −0.5 m/s²")
    a2.bar(x + 0.2, [ev[p]["radar_ant10"] * 100 for p in prof], 0.4, color=colors, alpha=0.55, label="≤ −1.0 m/s²")
    a2.axhline(ev["fused"]["vision_ant05"] * 100, color=VIS, ls="--", lw=1.1)
    a2.axhline(ev["fused"]["vision_ant10"] * 100, color=VIS, ls=":", lw=1.1)
    a2.set_xticks(x, names); a2.set_ylabel("% of driver brakes"); a2.set_ylim(0, 100)
    a2.set_title("Already asking within 3 s before (purple: vision only)")
    a2.text(1.0, 93, "solid ≤ −0.5, light ≤ −1.0 m/s²", fontsize=7.5, color=INK2, ha="center")
    slowed = [req[p]["radar_only_driver"].get("slowed", 0) for p in prof]
    gas = [req[p]["radar_only_driver"].get("on_gas", 0) for p in prof]
    a3.bar(names, slowed, color=colors, label="driver also slowed")
    a3.bar(names, gas, bottom=slowed, color=colors, alpha=0.4, hatch="//", label="driver on the gas")
    a3.set_ylabel("per hour of driving"); a3.set_title("Braking only the radar asked for (vision: 0)")
    a3.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(OUT / "profiles_vs_vision.png", dpi=130); plt.close(fig)


def kalman_variants() -> None:
    S = json.loads((REPO / "data" / "analysis" / "summaries" / "kalman_variants.json").read_text())
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.0, 4.0), gridspec_kw=dict(width_ratios=[1, 1.25]))
    names = list(S["bench_false_closing_pct"]); groups = ["heldout", "fresh", "owner"]
    y = np.arange(len(names))
    for k, (g, c) in enumerate(zip(groups, [FUS, S1, ANC])):
        a1.barh(y + (k - 1) * 0.26, [S["bench_false_closing_pct"][n][g] for n in names], 0.26, color=c, label=g.replace("heldout", "held-out"))
    a1.set_yticks(y, names); a1.invert_yaxis(); a1.set_xlabel("false closings (% of cycles, error < −2 m/s)")
    a1.set_xlim(0, 8.6); a1.set_title("Offline bench: object list only, vs the hidden ACC target"); a1.legend(loc="lower right", fontsize=8)
    T = S["trace"]; t = np.array(T["t"])
    a2.plot(t, T["raw_vrel"], color=GRAY, lw=1, label="object-list vRel")
    a2.plot(t, T["fused_vrel"], color=FUS, lw=2, label="fused (one speed state)")
    a2.plot(t, T["colored_vrel"], color=S4, lw=2, ls="--", label="colored noise (speed + bias state)")
    a2.set_xlabel("s"); a2.set_ylabel("vRel (m/s)")
    ax = a2.twinx(); ax.plot(t, T["d"], color=INK2, lw=0.8, ls=":"); ax.set_ylabel("range (m, dotted)", color=INK2)
    a2.set_title("Why the bias state was not promoted: a far false closing that recovers")
    a2.legend(loc="lower right", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "kalman_variants.png", dpi=130); plt.close(fig)


def kalman_trace() -> None:
    """The filter at work on bundled drive E: readings, estimate with its 1-sigma band, and how much each update moves it."""
    class Traced(Ars510NativeRadarInterface):
        log: dict = {}

        def _fused_speed(self, tid, time_s, obj, extra):
            cfg = self.config
            sig = cfg.speed_sigma_per_code * max(obj.vel_unc_code, 1)
            if obj.age < cfg.young_age:
                w = min(max((cfg.young_age - obj.age) / max(cfg.young_age - 60, 1), 0.0), 1.0)
                sig *= 1.0 + (cfg.young_sigma_scale - 1.0) * w
            st = self._fused.get(tid)
            gains = []
            if st is not None and 0.0 < time_s - st[0] <= 0.5:
                p = st[2] + (cfg.lead_accel_std_mps2 * (time_s - st[0])) ** 2
                for _, r in [(None, sig)] + list(extra):
                    k = p / (p + r * r); gains.append(k); p *= 1.0 - k
            v, std = super()._fused_speed(tid, time_s, obj, extra)
            ego = self._fresh_ego_speed(time_s) or 0.0
            self.log.setdefault(tid, []).append(dict(t=time_s, raw=obj.v_long_ground * cfg.vground_scale - ego, v=v - ego,
                                                     std=std, sig=sig, n_extra=len(extra), gains=gains, d=obj.d_rel))
            return v, std

    path = REPO / "data" / "sample" / "highway_acc_anchor_24s.csv.gz"
    import csv, gzip
    it = Traced(FUSED_CONFIG); Traced.log = {}
    acc = []
    with gzip.open(path, "rt") as fh:
        for row in csv.DictReader(fh):
            t, bus, addr, dat = float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])
            it.update_frame(t, bus, addr, dat)
            if bus == 1 and addr == 0x235 and it._acc_vrel is not None:
                acc.append((t, it._acc_vrel[1]))
    tid = max(Traced.log, key=lambda k: sum(r["n_extra"] > 0 for r in Traced.log[k]))
    L = Traced.log[tid]; t0 = L[0]["t"]
    t = np.array([r["t"] - t0 for r in L]); v = np.array([r["v"] for r in L]); sd = np.array([r["std"] for r in L])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
    a1.scatter(t, [r["raw"] for r in L], s=6, color=GRAY, label="object-list vRel (reading)", zorder=1)
    ta = np.array([a[0] - t0 for a in acc]); a1.plot(ta[(ta >= t[0]) & (ta <= t[-1])], np.array([a[1] for a in acc])[(ta >= t[0]) & (ta <= t[-1])],
                                                     color=ACC, lw=1.0, ls="--", label="radar ACC target (reading)")
    a1.fill_between(t, v - sd, v + sd, color=FUS, alpha=0.2, lw=0, label="estimate ± 1 std")
    a1.plot(t, v, color=FUS, lw=2, label="Kalman estimate (fused)")
    a1.set_ylabel("lead vRel (m/s)"); a1.legend(loc="lower left", fontsize=8)
    a1.set_title("One track through an excursion: the filter weighs each reading by its uncertainty")
    k_obj = [r["gains"][0] if r["gains"] else np.nan for r in L]
    k_acc = [r["gains"][1] if len(r["gains"]) > 1 else np.nan for r in L]
    a2.plot(t, k_obj, color=GRAY, lw=1.6, label="gain on the object-list reading")
    a2.plot(t, k_acc, color=ACC, lw=1.6, ls="--", label="gain on the ACC target reading")
    ax = a2.twinx(); ax.plot(t, [r["sig"] for r in L], color=S4, lw=1.0, ls=":"); ax.set_ylabel("object-list σ (m/s, dotted)", color=S4)
    a2.set_ylabel("Kalman gain K"); a2.set_xlabel("time (s)"); a2.set_ylim(0, 1); a2.legend(loc="upper left", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "kalman_trace.png", dpi=130); plt.close(fig)


def kalman_ablation() -> None:
    """Hard radar-only braking ticks with each part of fused removed (34 replay drives)."""
    S = json.loads((REPO / "data" / "analysis" / "summaries" / "fused_filter.json").read_text())["part_removed_34_drives"]
    rows = [("fused (all parts)", "none"), ("− ACC target + summaries", "acc_target_and_summaries"),
            ("− young-track factor", "young_track_factor"), ("− speed-std gate", "speed_std_publication_gate"),
            ("− age-60 gate", "age_60_publication_gate"), ("− range fusion", "range_fusion"),
            ("− ego-speed alignment", "ego_speed_alignment")]
    rows += [(f"− {lab}", key) for key, lab in S.get("combinations_labels", {}).items()]
    rows = [(lab, S[key]) for lab, key in rows if isinstance(S.get(key), dict)]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(10, 0.45 * len(rows) + 1.4))
    ax.barh(y - 0.2, [r["heldout"] for _, r in rows], 0.4, color=FUS, label="20 held-out routes")
    ax.barh(y + 0.2, [r["further"] for _, r in rows], 0.4, color=S4, label="4 further drives")
    ax.axvline(S["none"]["heldout"], color=FUS, lw=0.8, ls=":"); ax.axvline(S["none"]["further"], color=S4, lw=0.8, ls=":")
    ax.set_yticks(y, [lab for lab, _ in rows]); ax.invert_yaxis()
    ax.set_xlabel("hard radar-only braking ticks (planner ≤ −2 m/s² while vision-only ≥ −0.5)")
    ax.set_title("What each part of the Kalman filter is worth (34 replay drives)"); ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(OUT / "kalman_ablation.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    how_it_works(); scenarios(); layers(); vs_vision(); kalman_variants(); kalman_trace(); kalman_ablation()
    print("wrote", *(OUT / n for n in ("fused_how_it_works.png", "fused_scenarios_a.png", "fused_scenarios_b.png", "profile_layers.png", "profiles_vs_vision.png", "kalman_variants.png", "kalman_trace.png", "kalman_ablation.png")))
