#!/usr/bin/env python3
"""Tables and a summary JSON from fork_replay.py output.

  python tools/fork_lead/fork_report.py replay_out route_1 route_2 [--json fork_lead_handling.json]

Sections: A who supplies the lead; B braking demand added by radar noise (each fork on a profile against the same
fork on the radar's ACC target); C braking the radar added or removed against the same fork on vision only;
D StarPilot's two lead paths and its lead filters; E leads only FrogPilot accepts without camera confirmation;
F when braking starts in lead-braking events seen by the radar's ACC target (few events: a hint only).
"Demand" is the proxy of forksim.py at the planner's nominal spacing (what the lead's predicted speed and
acceleration ask for, independent of the gap the driver kept).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

DT = 0.05
CONFIGS = [("sunnypilot", "sunnypilot"), ("frogpilot-hf", "FrogPilot (Human Following on, default)"),
           ("frogpilot", "FrogPilot (Human Following off)"), ("starpilot", "StarPilot")]
PROB = {"sunnypilot": 0.5, "frogpilot-hf": 0.35, "frogpilot": 0.35, "starpilot": 0.35}


def load(out: Path, route: str, config: str, profile: str) -> dict:
    z = np.load(out / f"{route}__{config}__{profile}.npz")
    return {k: z["data"][:, i] for i, k in enumerate(z["cols"])}


def episodes(mask: np.ndarray, min_len: int = 1) -> list:
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    return [g for g in np.split(idx, np.where(np.diff(idx) > 1)[0] + 1) if len(g) >= min_len]


def r(x, n=2):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("routes", nargs="+")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    out, routes = args.out, args.routes
    have = [c for c, _ in CONFIGS if all((out / f"{rt}__{c}__acc.npz").exists() for rt in routes)]
    labels = dict(CONFIGS)
    res: dict = {"routes": len(routes), "configs": have}

    print("== A. lead supplier: share of lead time with a radar-sourced lead / a radar-only lead (no camera confirmation)")
    res["A_lead_source"] = {}
    for c in have:
        for prof in ("fused", "raw"):
            lead = rad = only = 0
            for rt in routes:
                d = load(out, rt, c, prof)
                m = d["status"] == 1
                lead += m.sum(); rad += (m & (d["radar"] == 1)).sum()
                only += (m & (d["radar"] == 1) & (d["vision_prob"] < PROB[c])).sum()
            print(f"  {labels[c]:42s} {prof:5s} {lead * DT / 60:5.1f} min  radar {100 * rad / lead:5.1f}%  radar-only {100 * only / lead:5.2f}%")
            res["A_lead_source"][f"{c}/{prof}"] = dict(lead_min=r(lead * DT / 60, 1), radar_pct=r(100 * rad / lead, 1),
                                                       radar_only_pct=r(100 * only / lead, 2))

    print("\n== B. braking demand added by radar noise: nominal demand minus the same fork on the radar's ACC target")
    print(f"  {'':42s} {'prof':5s} {'rms':>6s} {'p95':>5s} {'p99':>5s} {'>=0.5 /h':>9s} {'>=1.0 /h':>9s}")
    res["B_noise_vs_acc_reference"] = {}
    for c in have:
        for prof in ("fused", "raw"):
            diffs, e5, e10, hrs = [], 0, 0, 0.0
            for rt in routes:
                d, a = load(out, rt, c, prof), load(out, rt, c, "acc")
                both = (d["status"] == 1) & (d["radar"] == 1) & (a["status"] == 1) & (a["radar"] == 1)
                df = d["nominal"] - a["nominal"]
                diffs.append(df[both]); hrs += both.sum() * DT / 3600
                e5 += len(episodes(both & (df >= 0.5), 6)); e10 += len(episodes(both & (df >= 1.0), 6))
            x = np.concatenate(diffs)
            print(f"  {labels[c]:42s} {prof:5s} {np.sqrt(np.mean(x ** 2)):6.3f} {np.percentile(np.abs(x), 95):5.2f} {np.percentile(np.abs(x), 99):5.2f} {e5 / hrs:9.1f} {e10 / hrs:9.1f}")
            res["B_noise_vs_acc_reference"][f"{c}/{prof}"] = dict(
                minutes=r(hrs * 60, 1), rms=r(np.sqrt(np.mean(x ** 2)), 3), p95=r(np.percentile(np.abs(x), 95)),
                p99=r(np.percentile(np.abs(x), 99)), events_ge_0p5_per_h=r(e5 / hrs, 1), events_ge_1p0_per_h=r(e10 / hrs, 1))

    print("\n== C. braking the radar added / removed against the same fork on vision only (>=0.3 s)")
    res["C_added_removed_vs_vision"] = {}
    for c in have:
        for prof in ("fused", "raw"):
            add = rem = 0; hrs = 0.0
            for rt in routes:
                d, v = load(out, rt, c, prof), load(out, rt, c, "vision")
                hrs += (v["status"] == 1).sum() * DT / 3600
                add += len(episodes((d["nominal"] >= 1.0) & (v["nominal"] < 0.3), 6))
                rem += len(episodes((v["nominal"] >= 1.0) & (d["nominal"] < 0.3), 6))
            print(f"  {labels[c]:42s} {prof:5s} added>=1.0 {add / hrs:6.1f} /h   removed {rem / hrs:5.1f} /h")
            res["C_added_removed_vs_vision"][f"{c}/{prof}"] = dict(added_per_h=r(add / hrs, 1), removed_per_h=r(rem / hrs, 1))

    if "starpilot" in have:
        print("\n== D. StarPilot: model-trajectory path vs legacy path (lead braking > 0.5 m/s2 or closing TTC < 7 s)")
        res["D_starpilot_paths"] = {}
        for prof in ("vision", "raw", "fused", "acc"):
            lead = leg = runs = big = 0; hrs = 0.0; dur = []; extra = []
            for rt in routes:
                d, a = load(out, rt, "starpilot", prof), load(out, rt, "starpilot", "acc")
                m = d["status"] == 1; l = d["legacy"] == 1
                lead += m.sum(); leg += l.sum(); hrs += m.sum() * DT / 3600
                for e in episodes(l):
                    runs += 1; dur.append(len(e) * DT)
                    big += abs(d["filt_v"][e[0]] - d["vLead"][e[0]]) > 2.0
                    sl = slice(e[0], e[0] + 40)
                    ok = (d["radar"][sl] == 1) & (a["status"][sl] == 1)
                    if prof != "acc" and ok.any():
                        extra.append(np.nanmax((d["nominal"][sl] - a["nominal"][sl])[ok]))
            extra = np.array(extra)
            print(f"  {prof:6s} legacy path {100 * leg / lead:5.1f}% of lead time, {runs / hrs:4.0f} runs/h (median {np.median(dur):.2f} s), "
                  f"filtered lead speed >2 m/s off at entry in {100 * big / runs:.0f}% of runs"
                  + (f"; extra demand in first 2 s: median {np.median(extra):+.2f}, p90 {np.percentile(extra, 90):+.2f}, >=1.0 in {(extra >= 1.0).sum()} of {len(extra)}" if len(extra) else ""))
            res["D_starpilot_paths"][prof] = dict(
                legacy_pct=r(100 * leg / lead, 1), runs_per_h=r(runs / hrs, 0), median_run_s=r(np.median(dur), 2),
                stale_entry_pct=r(100 * big / runs, 0),
                extra_demand_median=r(np.median(extra)) if len(extra) else None,
                extra_demand_p90=r(np.percentile(extra, 90)) if len(extra) else None,
                extra_ge_1p0=f"{int((extra >= 1.0).sum())} of {len(extra)}" if len(extra) else None)

    if {"frogpilot", "sunnypilot", "starpilot"} <= set(have):
        print("\n== E. leads only FrogPilot accepts without camera confirmation (radar-only, ego >= 4 m/s)")
        res["E_frogpilot_far_lead"] = {}
        for prof in ("fused", "raw"):
            n = ge5 = ge10 = 0; hrs = 0.0; dur = []
            for rt in routes:
                f, u, s = (load(out, rt, c, prof) for c in ("frogpilot", "sunnypilot", "starpilot"))
                hrs += (f["status"] == 1).sum() * DT / 3600
                far = (f["status"] == 1) & (f["radar"] == 1) & (f["vision_prob"] < 0.35) & (f["vego"] >= 4.0)
                only = far & ~((u["status"] == 1) & (u["radar"] == 1) & (u["vision_prob"] < 0.5)) \
                    & ~((s["status"] == 1) & (s["radar"] == 1) & (s["vision_prob"] < 0.35))
                for e in episodes(only):
                    n += 1; dur.append(len(e) * DT)
                    peak = np.nanmax(f["nominal"][e]); ge5 += peak >= 0.5; ge10 += peak >= 1.0
            print(f"  {prof:5s} {n} episodes in {hrs * 60:.0f} min of lead time ({n / hrs:.1f}/h), median {np.median(dur):.2f} s, longest {max(dur):.1f} s; peak demand >=0.5 in {ge5}, >=1.0 in {ge10}")
            res["E_frogpilot_far_lead"][prof] = dict(episodes=n, lead_min=r(hrs * 60, 0), per_h=r(n / hrs, 1),
                                                     median_s=r(np.median(dur), 2), longest_s=r(max(dur), 1),
                                                     peak_ge_0p5=int(ge5), peak_ge_1p0=int(ge10))
    if "sunnypilot" in have:
        print("\n== F. lead-braking events (ACC target: lead deceleration >= 1 m/s2 for 0.5 s, ego > 12 m/s): first demand >= 0.5, fused vs vision only")
        events = []
        for rt in routes:
            a = load(out, rt, "sunnypilot", "acc")
            m = (a["status"] == 1) & (a["radar"] == 1) & (a["vego"] > 12) & (a["aLeadK"] <= -1.0)
            events += [(rt, e[0]) for e in episodes(m, 10)]

        def first(arr, i0):
            seg = arr[max(i0 - 60, 0): i0 + 160]
            k = np.where(seg >= 0.5)[0]
            return (k[0] + max(i0 - 60, 0) - i0) * DT if len(k) else np.nan
        res["F_braking_events"] = {"events": len(events)}
        for c in have:
            same = earlier = later = radar_only = 0
            for rt, i0 in events:
                v, f = first(load(out, rt, c, "vision")["nominal"], i0), first(load(out, rt, c, "fused")["nominal"], i0)
                if np.isnan(v) and not np.isnan(f): radar_only += 1
                elif np.isnan(v) or abs(f - v) < 0.06: same += 1
                elif f < v: earlier += 1
                else: later += 1
            print(f"  {labels[c]:42s} of {len(events)}: same time as vision {same}, radar earlier {earlier}, radar later {later}, radar-only response {radar_only}")
            res["F_braking_events"][c] = dict(same=same, radar_earlier=earlier, radar_later=later, radar_only=radar_only)
    if args.json:
        args.json.write_text(json.dumps(res, indent=1) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
