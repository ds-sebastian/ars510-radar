#!/usr/bin/env python3
"""Replay logged drives through openpilot's own card -> radard -> plannerd, with a stock or an ARS510-patched opendbc.

This is the end-to-end check of `openpilot/install.py`: nothing is simulated around the integration.
openpilot's process_replay runs:
  - card: real fingerprinting on the logged CAN, the patched Toyota CarInterface, RadarInterface.update() on
    can_capnp_to_list() batches;
  - radard and plannerd, as separate processes that exchange real messages.

Run it once with a stock opendbc and once with a patched copy, then compare:

  OP=/path/to/openpilot   # checkout at 10b9e73-ish, with .venv
  PY="$OP/.venv/bin/python"
  $PY process_replay_ars510.py run --openpilot $OP --opendbc $OP/opendbc_repo   --label stock  --out out seg1/rlog seg2/rlog
  $PY process_replay_ars510.py run --openpilot $OP --opendbc /tmp/patched_opendbc --label ars510 --out out seg1/rlog seg2/rlog
  $PY process_replay_ars510.py compare --out out stock ars510

- Pass consecutive segments of one drive in order. They are replayed as one stream, so track IDs and radard state
  carry across segment boundaries.
- `--mpc-shadow DIR` points at a build from build_long_mpc_shadow.py if the checkout's acados solver is not built.
- card fingerprints as on the car: FW versions come from the logged CarParams (the cached-FW path), then CAN
  fingerprinting runs on the logged frames. ARS510 detection therefore sees the radar FW, and bus 1 as it was at
  the start of the first segment.
- One logged field is changed: CarParams.openpilotLongitudinalControl is cleared. Otherwise process_replay turns
  alpha long on, and on a RADAR_ACC Toyota card's startup then runs the UDS radar-disable routine. In
  process_replay card stalls after that routine (stock opendbc too): 80 carState messages per segment instead of
  6000. radard and the planner do not depend on the toggle. Whether the radar keeps sending 0x80 after a real
  disable request can only be checked on the car (docs/07).

Open-loop: ego motion stays as recorded. It shows what openpilot would have requested, not what the car would have
done. Outputs:
- <out>/<label>.ticks.csv.gz: one row per radarState. Its radar_valid column is False throughout in accelerated
  replay (SubMaster frequency checks use wall time), stock and patched alike; the planner does not gate on it;
- <out>/<label>.tracks.csv.gz: one row per radarTracks;
- <out>/<label>.meta.json: CarParams, RadarInterface timing;
- compare: <out>/compare.json;
- with --save-logs DIR: per-segment rlogs under DIR/<label>/, for openpilot's own viewers. In each one:
  - card, radard and plannerd outputs replace the logged ones;
  - every other message is kept;
  - the cameras are symlinked;
  - the layout is `DIR/<label>/<dongle>|<route>/<seg>/rlog.zst`, which openpilot's Route(data_dir=...) reads.
  Two fields are changed:
  - radarState.valid is set from the replayed radarTracks.valid, because accelerated replay fails the frequency
    checks and the UI would otherwise draw no lead;
  - initData.params is emptied, because the recording's params (another fork, the VIN) break tools/clip;
  - modelV2 lane lines are cut to the 4 the current UI draws (FrogPilot's model publishes 6);
  - CarParams.openpilotLongitudinalControl is restored to the recorded value, because the UI draws the lead
    chevron only with openpilot longitudinal;
  - CarParams is repeated every second and initData is moved to the segment start, so tools/clip sees both in any
    window. Render the UI over the video, or plot signals:
    $OP/.venv/bin/python $OP/openpilot/tools/clip/run.py "a510a510a510a510/<route>/<start_s>/<end_s>" -d DIR/<label> -o x.mp4
    $OP/openpilot/tools/plotjuggler/juggle.py "DIR/<label>/a510a510a510a510|<route>/<seg>/rlog.zst"
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import time
from pathlib import Path

TICK_COLS = ["t", "v_ego", "lead_present", "lead_radar", "lead_track", "lead_d", "lead_v", "lead_vlead", "lead_a",
             "lead_prob", "lead2_present", "lead2_radar", "a_target", "fcw", "has_lead", "plan_source", "radar_valid"]
TRACK_COLS = ["t", "n_points", "valid", "can_error", "unavailable", "min_d"]


def setup_paths(openpilot: Path, opendbc: Path, mpc_shadow: Path | None) -> None:
  # the chosen opendbc must win over any installed copy; forked replay processes inherit sys.path and module state
  sys.path.insert(0, str(openpilot.resolve()))
  sys.path.insert(0, str(opendbc.resolve()))
  if mpc_shadow is not None:
    import openpilot.selfdrive.controls.lib as lib
    lib.__path__.insert(0, str(mpc_shadow.resolve()))


def bench_radar_interface(msgs: list, CP) -> dict:
  """Time RadarInterface.update() exactly as card.py calls it: one call per logged can message."""
  from opendbc.car.car_helpers import interfaces
  RI = interfaces[CP.carFingerprint].RadarInterface(CP)
  batches = [[(m.logMonoTime, [(c.address, c.dat, c.src) for c in m.can])] for m in msgs if m.which() == "can"]
  dts, outs = [], 0
  for b in batches:
    t0 = time.perf_counter()
    out = RI.update(b)
    dts.append(time.perf_counter() - t0)
    outs += out is not None
  dts.sort()
  n = len(dts)
  return {"calls": n, "outputs": outs, "mean_us": round(1e6 * sum(dts) / max(n, 1), 1),
          "p99_us": round(1e6 * dts[int(0.99 * (n - 1))], 1) if n else None, "max_us": round(1e6 * dts[-1], 1) if n else None,
          "cpu_fraction_at_100hz": round(sum(dts) / max(n, 1) * 100, 5), "class": type(getattr(RI, "ars510", None) or RI).__name__}


def run(args) -> int:
  setup_paths(args.openpilot, args.opendbc, args.mpc_shadow)
  import opendbc
  from openpilot.tools.lib.logreader import LogReader
  from openpilot.selfdrive.test.process_replay.process_replay import replay_process_with_name

  msgs, bounds = [], []
  for p in args.rlogs:
    seg = list(LogReader(str(p)))
    # segment start = first CAN time (initData carries an older logMonoTime)
    t0 = min((m.logMonoTime for m in seg if m.which() == "can"), default=0)
    bounds.append((Path(p), t0, len(msgs), len(msgs) + len(seg)))
    msgs.extend(seg)
  logged_long = any(m.carParams.openpilotLongitudinalControl for m in msgs if m.which() == "carParams")
  for i, m in enumerate(msgs):
    if m.which() == "carParams" and m.carParams.openpilotLongitudinalControl:
      ev = m.as_builder()
      ev.carParams.openpilotLongitudinalControl = False
      msgs[i] = ev.as_reader()
  t0 = time.time()
  out = replay_process_with_name(["card", "radard", "plannerd"], msgs, disable_progress=True)
  wall = time.time() - t0

  cp = next(m.carParams for m in out if m.which() == "carParams")
  v_ego, plan_by_model = {}, {}
  for m in out:
    if m.which() == "longitudinalPlan":
      plan_by_model[m.longitudinalPlan.modelMonoTime] = m.longitudinalPlan
  for m in msgs:
    if m.which() == "carState":
      v_ego[m.logMonoTime] = m.carState.vEgo
  ve_t = sorted(v_ego)

  def ego_at(t_ns: int) -> float:
    import bisect
    i = bisect.bisect_right(ve_t, t_ns) - 1
    return v_ego[ve_t[i]] if i >= 0 else math.nan

  args.out.mkdir(parents=True, exist_ok=True)
  with gzip.open(args.out / f"{args.label}.ticks.csv.gz", "wt", newline="") as f:
    w = csv.writer(f)
    w.writerow(TICK_COLS)
    for m in out:
      if m.which() != "radarState":
        continue
      rs = m.radarState
      l1, l2 = rs.leadOne, rs.leadTwo
      lp = plan_by_model.get(rs.mdMonoTime)
      w.writerow([m.logMonoTime / 1e9, round(ego_at(m.logMonoTime), 3), int(l1.present), int(l1.radar), l1.radarTrackId,
                  round(l1.dRel, 3), round(l1.vRel, 3), round(l1.vLead, 3), round(l1.aLeadK, 3), round(l1.modelProb, 3),
                  int(l2.present), int(l2.radar),
                  round(lp.aTarget, 4) if lp is not None else "", int(lp.fcw) if lp is not None else "",
                  int(lp.hasLead) if lp is not None else "", str(lp.longitudinalPlanSource) if lp is not None else "",
                  int(m.valid)])
  with gzip.open(args.out / f"{args.label}.tracks.csv.gz", "wt", newline="") as f:
    w = csv.writer(f)
    w.writerow(TRACK_COLS)
    for m in out:
      if m.which() != "radarTracks":
        continue
      rt = m.radarTracks
      d = [p.dRel for p in rt.points]
      w.writerow([m.logMonoTime / 1e9, len(d), int(m.valid), int(rt.errors.canError), int(rt.errors.radarUnavailableTemporary),
                  round(min(d), 2) if d else ""])

  meta = {"label": args.label, "opendbc": str(Path(opendbc.__file__).parent), "segments": [str(p) for p in args.rlogs],
          "replay_wall_s": round(wall, 1),
          "carParams": {"carFingerprint": cp.carFingerprint, "flags": int(cp.flags), "radarUnavailable": cp.radarUnavailable,
                        "openpilotLongitudinalControl": cp.openpilotLongitudinalControl, "radarDelay": cp.radarDelay},
          "radar_interface_bench": bench_radar_interface(msgs, cp)}
  (args.out / f"{args.label}.meta.json").write_text(json.dumps(meta, indent=1) + "\n")
  print(json.dumps(meta, indent=1))
  if args.save_logs is not None:
    save_logs(args.save_logs / args.label, msgs, out, bounds, logged_long)
  return 0


DONGLE = "a510a510a510a510"  # placeholder dongle id so openpilot's Route() finds local files


def save_logs(dest: Path, msgs: list, out: list, bounds: list, logged_long: bool) -> None:
  from openpilot.tools.lib.logreader import save_log
  replaced = {m.which() for m in out}
  dest.mkdir(parents=True, exist_ok=True)
  valid_tracks = sorted((m.logMonoTime, m.valid) for m in out if m.which() == "radarTracks")
  import bisect
  vt = [t for t, _ in valid_tracks]

  def fixed(m):
    if m.which() == "initData":
      # the recording's params (other fork, VIN) break tools/clip's Params.put; the UI's defaults are fine
      ev = m.as_builder()
      ev.initData.params.entries = []
      return ev.as_reader()
    if m.which() == "modelV2" and len(m.modelV2.laneLines) > 4:
      # some forks' models publish 6 lane lines; the current UI draws 4 (radard reads only leadsV3)
      ev = m.as_builder()
      for name in ("laneLines", "laneLineProbs", "laneLineStds"):
        src = getattr(m.modelV2, name)
        dst = ev.modelV2.init(name, min(4, len(src)))
        for i in range(len(dst)):
          dst[i] = src[i]
      return ev.as_reader()
    if m.which() == "carParams" and logged_long:
      # the UI draws the lead chevron only with openpilot longitudinal, which the recorded drive had
      ev = m.as_builder()
      ev.carParams.openpilotLongitudinalControl = True
      return ev.as_reader()
    if m.which() != "radarState":
      return m
    i = bisect.bisect_right(vt, m.logMonoTime) - 1
    ev = m.as_builder()
    ev.valid = bool(valid_tracks[i][1]) if i >= 0 else False
    return ev.as_reader()

  starts = [b[1] for b in bounds] + [2 ** 63]
  for k, (path, t0, i0, i1) in enumerate(bounds):
    route, _, seg_num = path.parent.name.rpartition("--")  # <route>--<seg>
    seg_dir = dest / f"{DONGLE}|{route}" / seg_num
    seg_dir.mkdir(parents=True, exist_ok=True)
    keep = [fixed(m) for m in msgs[i0:i1] if m.which() not in replaced]
    keep += [fixed(m) for m in out if starts[k] <= m.logMonoTime < starts[k + 1]]
    cps = [m for m in keep if m.which() == "carParams"]
    if cps and t0:
      # card sends carParams every 50 s; tools/clip only shows what arrives inside its window, so repeat it each second
      t_end = max(m.logMonoTime for m in keep)
      for t in range(t0, t_end, 1_000_000_000):
        ev = cps[0].as_builder()
        ev.logMonoTime = t
        keep.append(ev.as_reader())
    for i, m in enumerate(keep):
      if m.which() == "initData" and t0:  # initData carries an older clock; clip chunks frames from the first message
        ev = m.as_builder()
        ev.logMonoTime = t0
        keep[i] = ev.as_reader()
    keep.sort(key=lambda m: m.logMonoTime)
    save_log(str(seg_dir / "rlog.zst"), keep)
    for cam in ("fcamera.hevc", "ecamera.hevc", "qcamera.ts"):
      src, link = path.parent / cam, seg_dir / cam
      if src.exists() and not link.exists():
        link.symlink_to(src.resolve())
  print(f"saved {len(bounds)} segment logs to {dest}")


def read_csv(p: Path) -> list[dict]:
  with gzip.open(p, "rt") as f:
    return [{k: (float(v) if v not in ("", None) and k != "plan_source" else v) for k, v in r.items()} for r in csv.DictReader(f)]


def episodes(times: list[float], gap_s: float = 0.5) -> list[tuple[float, float]]:
  eps: list[list[float]] = []
  for t in times:
    if eps and t - eps[-1][1] <= gap_s:
      eps[-1][1] = t
    else:
      eps.append([t, t])
  return [(round(a, 2), round(b, 2)) for a, b in eps]


def side_summary(ticks: list[dict], tracks: list[dict]) -> dict:
  n = len(ticks)
  fcw_t = [r["t"] for r in ticks if r["fcw"] == 1.0]
  dt = [b["t"] - a["t"] for a, b in zip(tracks, tracks[1:], strict=False)]
  return {
    "radarState_ticks": n,
    "lead_present_share": round(sum(r["lead_present"] for r in ticks) / max(n, 1), 4),
    "lead_radar_share": round(sum(r["lead_radar"] for r in ticks) / max(n, 1), 4),
    "fcw_ticks": len(fcw_t), "fcw_events": episodes(fcw_t, 1.0),
    "radarTracks_msgs": len(tracks),
    "radarTracks_hz": round((len(tracks) - 1) / (tracks[-1]["t"] - tracks[0]["t"]), 2) if len(tracks) > 1 else None,
    "radarTracks_max_gap_s": round(max(dt), 3) if dt else None,
    "radarTracks_error_msgs": int(sum(1 for r in tracks if r["can_error"] or r["unavailable"])),
    "points_per_msg_mean": round(sum(r["n_points"] for r in tracks) / max(len(tracks), 1), 2),
  }


def compare(args) -> int:
  a, b = args.labels
  A, B = read_csv(args.out / f"{a}.ticks.csv.gz"), read_csv(args.out / f"{b}.ticks.csv.gz")
  res = {a: side_summary(A, read_csv(args.out / f"{a}.tracks.csv.gz")),
         b: side_summary(B, read_csv(args.out / f"{b}.tracks.csv.gz"))}
  # radarState is driven by modelV2 in both runs: pair ticks in order of time
  pairs = [(x, y) for x, y in zip(A, B, strict=False) if x["a_target"] != "" and y["a_target"] != "" and abs(x["t"] - y["t"]) < 0.03]
  diffs = sorted(y["a_target"] - x["a_target"] for x, y in pairs)
  q = (lambda p: round(diffs[int(p * (len(diffs) - 1))], 3)) if diffs else (lambda p: None)
  harder = [y["t"] for x, y in pairs if y["a_target"] <= -1.0 and x["a_target"] >= -0.3]
  softer = [y["t"] for x, y in pairs if x["a_target"] <= -1.0 and y["a_target"] >= -0.3]
  both = [(x, y) for x, y in pairs if x["lead_present"] and y["lead_present"] and y["lead_radar"]]
  dd = sorted(y["lead_d"] - x["lead_d"] for x, y in both)
  res["paired_ticks"] = len(pairs)
  res[f"a_target_{b}_minus_{a}"] = {"p01": q(0.01), "p05": q(0.05), "median": q(0.5), "p95": q(0.95), "p99": q(0.99),
                                    "min": diffs[0] if diffs else None, "max": diffs[-1] if diffs else None}
  res[f"braking_only_in_{b}"] = {"ticks": len(harder), "episodes": episodes(harder)}
  res[f"braking_only_in_{a}"] = {"ticks": len(softer), "episodes": episodes(softer)}
  res[f"lead_dRel_{b}_radar_minus_{a}"] = {"ticks": len(dd), "median": dd[len(dd) // 2] if dd else None,
                                            "p05": dd[int(0.05 * (len(dd) - 1))] if dd else None, "p95": dd[int(0.95 * (len(dd) - 1))] if dd else None}
  for lab in (a, b):
    mp = args.out / f"{lab}.meta.json"
    if mp.exists():
      res[lab]["meta"] = json.loads(mp.read_text())
  (args.out / "compare.json").write_text(json.dumps(res, indent=1) + "\n")
  print(json.dumps({k: v for k, v in res.items()}, indent=1, default=str)[:6000])
  return 0


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)
  r = sub.add_parser("run")
  r.add_argument("--openpilot", type=Path, required=True)
  r.add_argument("--opendbc", type=Path, required=True, help="opendbc checkout to use (stock or patched)")
  r.add_argument("--label", required=True)
  r.add_argument("--out", type=Path, required=True)
  r.add_argument("--mpc-shadow", type=Path, default=None)
  r.add_argument("--save-logs", type=Path, default=None, help="write per-segment rlogs with the replayed outputs here")
  r.add_argument("rlogs", type=Path, nargs="+")
  c = sub.add_parser("compare")
  c.add_argument("--out", type=Path, required=True)
  c.add_argument("labels", nargs=2)
  args = ap.parse_args()
  return run(args) if args.cmd == "run" else compare(args)


if __name__ == "__main__":
  raise SystemExit(main())
