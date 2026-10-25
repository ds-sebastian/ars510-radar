#!/usr/bin/env python3
"""Self-check of an installed ARS510 integration on synthetic records and the bundled ACC-target sample. Run it with the opendbc checkout you
installed into, using a Python that has pycapnp (for example openpilot's .venv):

    $OP/.venv/bin/python openpilot/check_integration.py --opendbc $OP/opendbc_repo

It checks:
- detection: the RAV4 2022 / 2023 radar-ACC platforms get radarUnavailable=False from the car model and the radar's early
  bus-1 frames (either radar firmware, also at a cold start, before the object list starts), and stay radarless without
  them; C-HR and Yaris likewise; every other Toyota keeps the fork's own RadarInterface;
- for the `acc` profile: the bundled ACC-target sample (data/sample/highway_acc_anchor_24s.csv.gz) is fed at
  card.py's 100 Hz with the radar's cycle clock (0x239) added, and it checks one output per radar cycle (~16.6 Hz),
  the one point against ars510.support.parse_acc_target (id, units, sign), no output when the target frames stop,
  recovery, and radarUnavailableTemporary while the radar's 0x196 fault flag is held (a single power-up cycle ignored).
- every profile: the radar's PCS alarm (0x100) sets carState.stockFcw, not on the power-up frame.
- for the `acc_summaries` profile: synthetic radar cycles (0x190 clock, ACC target, two summaries) checking the ACC car
  published once, a summary car with its range-slope speed, nothing beyond 40 m, staleness and recovery; on trees whose
  RadarPoint has aRel / yvRel / measured, the ACC point's REL_ACCEL / LAT_SPEED, a recorded wrapped LAT_SPEED, and the
  summary car's lateral slope.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def check_acc_profile(RI, check) -> None:
  """The `acc` profile publishes the radar's ACC target (0x235 / 0x237) as its one point, once per radar cycle (0x239):
  replay the bundled sample, which has no 0x239, with the cycle clock added every third 0x237 (60 ms) as on the car."""
  import csv
  import gzip
  from opendbc.car.toyota.ars510.support import parse_acc_target
  sample = Path(__file__).resolve().parents[1] / "data" / "sample" / "highway_acc_anchor_24s.csv.gz"
  steps: dict[int, list] = {}
  n237 = 0
  with gzip.open(sample, "rt") as f:
    for r in csv.DictReader(f):
      if r["address"] in ("0x235", "0x237"):
        step = steps.setdefault(int(float(r["t_s"]) * 100), [])
        step.append((int(r["address"], 16), bytes.fromhex(r["data_hex"]), int(r["bus"])))
        if r["address"] == "0x237":
          step.append((0x239, ((n237 % 16) << 52 | (1 + n237 // 3) * 60000 << 3).to_bytes(8, "big"), 1))  # counter, clock
          n237 += 1
  t_ns, last, outs = 1_000_000_000, {}, []
  for k in range(max(steps) + 1):
    t_ns += 10_000_000
    batch = steps.get(k, [])
    for addr, dat, _ in batch:
      last[addr] = dat
    out = RI.update([(t_ns, batch)])
    if out is not None and k >= 50:  # skip the parser's first 0.5 s
      outs.append((out, parse_acc_target(last.get(0x235, b""), last.get(0x237, b""))))
  rate = len(outs) / ((max(steps) - 50) / 100)
  check(14 <= rate <= 19, f"acc: RadarData once per radar cycle, ~16.6 Hz (got {rate:.1f} Hz)")
  check(all(not any(o.errors.to_dict().values()) for o, _ in outs), "acc: no error flags while the target frames arrive")
  match = [len(o.points) == (want is not None) and (want is None or (o.points[0].trackId == want.target_id and
           abs(o.points[0].dRel - want.d_rel) < 0.03 and abs(o.points[0].yRel - want.y_rel) < 0.011 and
           abs(o.points[0].vRel - want.v_rel) < 0.13)) for o, want in outs]
  n_pts = sum(len(o.points) for o, _ in outs)
  check(all(match) and n_pts > 100, f"acc: the one point equals the decoded ACC target (id, dRel, yRel left-positive, vRel) "
        f"on every output ({sum(match)}/{len(match)}, {n_pts} points)")
  silent = [RI.update([(t_ns + i * 10_000_000, [])]) for i in range(1, 101)]  # 1 s after the target frames stop
  t_ns += 100 * 10_000_000
  check(all(o is None for o in silent), "acc: no output (and no stale point) when the target frames stop, as Toyota's other radars")
  rec = []
  for k in sorted(steps)[:60]:  # frames resume, with the cycle clock continuing
    t_ns += 10_000_000
    batch = [(a, ((n237 % 16) << 52 | (5000 + n237) * 60000 << 3).to_bytes(8, "big") if a == 0x239 else d, s)
             for a, d, s in steps[k]]
    n237 += sum(1 for a, _, _ in batch if a == 0x239)
    out = RI.update([(t_ns, batch)])
    if out is not None:
      rec.append(out)
  check(bool(rec) and not rec[-1].errors.canError and len(rec[-1].points) == 1, "acc: recovers when the target frames resume")

  def run(keys, fault_bits):  # the radar's 0x196 event frame once per radar cycle, byte 1 bit 0 = its fault flag
    nonlocal t_ns, n237
    got = []
    for i, k in enumerate(keys):
      t_ns += 10_000_000
      batch = [(a, ((n237 % 16) << 52 | (5000 + n237) * 60000 << 3).to_bytes(8, "big") if a == 0x239 else d, s) for a, d, s in steps[k]]
      batch += [(0x196, bytes([0xFF, fault_bits(i), 0, 0, 0, 0, 0, 0]), 1) for a, _, _ in steps[k] if a == 0x239]
      n237 += sum(1 for a, _, _ in batch if a == 0x239)
      out = RI.update([(t_ns, batch)])
      if out is not None:
        got.append(out)
    return got
  keys = sorted(steps)[60:160]
  one = run(keys[:50], lambda i: 1 if i == 0 else 0)  # a single set cycle, as at power-up
  check(bool(one) and not any(o.errors.radarUnavailableTemporary for o in one), "acc: a single fault cycle (power-up) is ignored")
  held = run(keys[50:], lambda i: 1)
  rate = len(held) / (len(keys[50:]) / 100)
  check(len(held) > 5 and all(o.errors.radarUnavailableTemporary and not o.points for o in held[2:]) and 15 <= rate <= 24,
        f"acc: radarUnavailableTemporary and no points while the radar's 0x196 fault flag is held, at {rate:.1f} Hz (radard: 8-24 Hz)")
  clear = run(sorted(steps)[160:220], lambda i: 0)
  check(bool(clear) and not clear[-1].errors.radarUnavailableTemporary and len(clear[-1].points) == 1, "acc: clears with the fault flag")


def check_acc_summaries_profile(RI, check) -> None:
  """`acc_summaries`: the ACC target plus the target-summary cars within 40 m. Synthetic radar cycles (0x190 clock, ACC
  target at 30 m, summary 1 on the ACC car, summary 2 a car at 40 m closing at 6 m/s, then one at 80 m) are fed at
  card.py's 100 Hz: the ACC car once, the 40 m car with its slope speed, nothing beyond 40 m, staleness and recovery."""
  from opendbc.car.toyota.ars510.support import ACC_CHECK

  def checked(address, frame):  # byte 0 = the radar's check byte, as on every recorded frame (the profile reads it)
    crc = ACC_CHECK[address][0]
    for i, col in enumerate(ACC_CHECK[address][2]):
      crc ^= col if frame[1 + i // 8] >> (7 - i % 8) & 1 else 0
    return bytes([crc]) + frame[1:]

  def cycle(n, k, far):  # n: radar cycle number (clock), k: cycle within the run (geometry)
    ts, acc_code = 1_000_000 + 60_000 * n, round((30.0 - 0.24 * k) / 0.025)
    other = (80.0 if far else 40.0) - 0.36 * k
    return [(0x190, bytes([0x0A, 0]) + ts.to_bytes(4, "big") + b"\x00", 1),
            (0x235, checked(0x235, ((1 << 59) | (5 << 48) | (108 << 40) | (1056 << 29) | (1064 << 8) | 7).to_bytes(8, "big")), 1),  # aRel +1, LAT_SPEED +0.5
            (0x237, checked(0x237, ((acc_code << 39) | (2000 << 27) | (1 << 10)).to_bytes(8, "big")), 1),
            (0x191, bytes([182, 0, 0, 3 << 2, 0, 0, 0, 0]), 1), (0x192, (160 + (2 * acc_code) // 5).to_bytes(2, "big") + (2048).to_bytes(2, "big"), 1),
            (0x193, bytes([182, 0, 0, 9 << 2, 0, 0, 0, 0]), 1), (0x194, round(other * 16 + 160).to_bytes(2, "big") + (2288 + 2 * k).to_bytes(2, "big"), 1)]  # moving left 0.5 m/s
  t_ns, outs = 1_000_000_000, {False: [], True: []}
  for far in (False, True):
    for k in range(40):
      for j in range(6):  # one radar cycle per six card steps
        t_ns += 10_000_000
        out = RI.update([(t_ns, cycle(k + (100 if far else 0), k, far) if j == 0 else [])])
        if out is not None and k >= 10:
          outs[far].append(out)
  near = outs[False]
  check(all(not any(o.errors.to_dict().values()) for o in near), "acc_summaries: no error flags while the frames arrive")
  # the summary range is quantized to 1/16 m per 60 ms cycle; the Kalman speed (PR 216) wanders up to ~0.1 m/s on it
  ok = [sorted(p.trackId for p in o.points) == [7, 73] and abs(next(p for p in o.points if p.trackId == 73).vRel + 6.0) < 0.15 for o in near]
  check(bool(near) and all(ok), f"acc_summaries: the ACC target once plus the 40 m summary car with its slope speed ({sum(ok)}/{len(ok)})")
  check(all([p.trackId for p in o.points] == [7] for o in outs[True]), "acc_summaries: summary cars beyond 40 m are not published")
  if all(hasattr(near[-1].points[0], f) for f in ("aRel", "yvRel", "measured")):  # forks that still carry the optional fields
    acc_pt, car = next(p for p in near[-1].points if p.trackId == 7), next(p for p in near[-1].points if p.trackId == 73)
    check(abs(acc_pt.aRel - 1.0) < 1e-6 and abs(acc_pt.yvRel - 0.5) < 1e-6 and acc_pt.measured,
          "acc_summaries: ACC point carries the radar's REL_ACCEL (aRel) and LAT_SPEED (yvRel), measured")
    check(math.isnan(car.aRel) and abs(car.yvRel - 0.5) < 0.02 and car.measured,
          f"acc_summaries: summary car carries its lateral slope as yvRel ({car.yvRel:.3f} m/s) and aRel NaN")
    from opendbc.car.toyota.ars510.support import acc_check
    wrapped = bytes.fromhex("fd65 6783 abd8 8f12")  # recorded 0x235 of a crossing car beyond 12.8 m/s: LAT_SPEED wrapped
    want = ((int.from_bytes(wrapped, "big") >> 8 & 0x7FF) - 1024) * 0.0125 + 25.6
    base = cycle(200, 0, False)
    got = None
    for j in range(12):
      t_ns += 10_000_000
      frames = [(a, wrapped if a == 0x235 else d, s) for a, d, s in base] if j == 0 else []
      out = RI.update([(t_ns, frames)])
      if out is not None and out.points:
        got = next((p for p in out.points if p.trackId == wrapped[7] & 0x3F), None) or got
    check(acc_check(0x235, wrapped) == "wrapped" and got is not None and abs(got.yvRel - want) < 1e-6,
          f"acc_summaries: a wrapped LAT_SPEED is unwrapped by the check byte ({want:.2f} m/s)")
  else:
    print("skip acc_summaries optional fields: this tree's RadarPoint has no aRel / yvRel / measured")
  silent = [o for o in (RI.update([(t_ns + i * 10_000_000, [])]) for i in range(1, 101)) if o is not None]
  t_ns += 100 * 10_000_000
  check(bool(silent) and silent[-1].errors.radarUnavailableTemporary and len(silent[-1].points) == 0,
        "acc_summaries: silent radar -> radarUnavailableTemporary with no points")
  rec = []
  for k in range(12):
    for j in range(6):
      t_ns += 10_000_000
      out = RI.update([(t_ns, cycle(300 + k, k, False) if j == 0 else [])])
      rec += [out] if out is not None else []
  check(bool(rec) and not rec[-1].errors.radarUnavailableTemporary and len(rec[-1].points) >= 1, "acc_summaries: recovers when the frames resume")


def check_pcs_alarm(CarInterface, CP, extra, check) -> None:
  """The radar's PCS alarm (bus-1 0x100) sets carState.stockFcw; the power-up FF FF frame does not."""
  try:
    CI = CarInterface(CP, *extra)
    fcw = []
    for i, byte0 in enumerate([0xFF, 0, 2, 2, 0]):
      cs = CI.update([(int(i * 1e8), [(0x100, bytes([byte0, byte0 if byte0 == 0xFF else 0, 0, 0, 0, 0, 0]), 1)])])
      fcw.append(bool((cs[0] if isinstance(cs, tuple) else cs).stockFcw))
  except TypeError as e:  # a fork whose update takes more arguments (StarPilot toggles)
    print(f"skip PCS alarm check: {e}")
    return
  check(fcw == [False, False, True, True, False], f"PCS alarm: stockFcw follows 0x100, power-up frame ignored (got {fcw})")


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--opendbc", type=Path, default=None, help="opendbc checkout to import (default: whatever is importable)")
  ap.add_argument("--flavor", help=argparse.SUPPRESS)  # accepted for old instructions; the fork is detected
  args = ap.parse_args()
  if args.opendbc is not None:
    sys.path.insert(0, str(args.opendbc.resolve()))

  from opendbc.car import structs
  from opendbc.car.toyota.interface import CarInterface  # Toyota only: other brands may need fork-only packages
  from opendbc.car.toyota.values import CAR
  from opendbc.car.toyota.ars510_radar_interface import PROFILE, Ars510RadarInterface, is_ars510

  failures: list[str] = []

  def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
      failures.append(what)

  def params(car, bus1: dict[int, int], radar_fw: bytes | None = None):
    fp = {i: {} for i in range(8)}
    fp[0] = {0xB4: 8}
    fp[1] = dict(bus1)
    car_fw = [] if radar_fw is None else [structs.CarParams.CarFw(ecu="fwdRadar", fwVersion=radar_fw, address=0x750, subAddress=0xf)]
    return CarInterface.get_params(car, fp, car_fw, alpha_long=False, is_release=False, docs=False)

  ars_bus1 = {0x80: 8, 0x85: 8, 0x81: 8, 0x86: 8, 0x190: 7, 0x191: 8, 0x235: 8, 0x237: 8, 0x239: 8}  # a running radar
  cold_bus1 = {0x191: 8, 0x192: 4, 0x180: 5}  # first ~1 s after power-up: target summaries, no 0x80 / 0x85 yet
  for car in (CAR.TOYOTA_RAV4_TSS2_2022, CAR.TOYOTA_RAV4_TSS2_2023):
    for fw in (b'\x018821F0R01100\x00\x00\x00\x00', b'\x018821F0R03100\x00\x00\x00\x00'):
      CP = params(car, cold_bus1, fw)
      check(is_ars510(CP), f"{car}: ARS510 from the car model (radar FW {fw[1:13].decode()}, cold start)")
    CP = params(car, {})
    check(not is_ars510(CP), f"{car}: no radar frames on bus 1 at fingerprinting -> radarless (vision leads), not a silent radar")
  extra = (structs.CarParamsSP(),) if hasattr(structs, "CarParamsSP") else ()  # sunnypilot passes CP_SP
  for name in ("TOYOTA_CHR_TSS2", "TOYOTA_YARIS"):
    car = getattr(CAR, name, None)
    if car is None:
      print(f"skip {name}: not in this fork")
      continue
    CP = params(car, cold_bus1)
    RIc = CarInterface.RadarInterface(CP, *extra)
    check(is_ars510(CP) and isinstance(RIc, Ars510RadarInterface), f"{name}: ARS510 from the car model (testing)")
    if name == "TOYOTA_YARIS":
      check(RIc.standalone is not None, "TOYOTA_YARIS runs the acc parser whatever the profile (no 0xB4 wheel speed)")
  CP = params(CAR.TOYOTA_RAV4_TSS2, ars_bus1)
  RI0 = CarInterface.RadarInterface(CP, *extra)
  check(not is_ars510(CP) and not isinstance(RI0, Ars510RadarInterface),
        "non-RADAR_ACC RAV4 TSS2 ignores 0x80 on bus 1 and keeps the fork's RadarInterface")

  # ---- RadarInterface on synthetic records ----
  CP = params(CAR.TOYOTA_RAV4_TSS2_2022, ars_bus1)
  check_pcs_alarm(CarInterface, CP, extra, check)
  RI = CarInterface.RadarInterface(CP, *extra)
  check(isinstance(RI, Ars510RadarInterface), "Toyota RadarInterface builds Ars510RadarInterface for an ARS510 car")
  (check_acc_profile if PROFILE == "acc" else check_acc_summaries_profile)(RI, check)
  print("\nALL OK" if not failures else f"\n{len(failures)} FAILED")
  return 0 if not failures else 1


if __name__ == "__main__":
  raise SystemExit(main())
