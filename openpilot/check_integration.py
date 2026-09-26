#!/usr/bin/env python3
"""Self-check of an installed ARS510 integration, without a car or a log. Run it with the opendbc checkout you
installed into, using a Python that has pycapnp (for example openpilot's .venv):

    $OP/.venv/bin/python openpilot/check_integration.py --opendbc $OP/opendbc_repo

It checks:
- detection: RAV4 2022 / 2023 radar-ACC platforms get ToyotaFlags.ARS510_RADAR and radarUnavailable=False when the
  radar FW is a known ARS510 (a cold start, before 0x80 exists) or 0x80 and 0x85 were seen on bus 1; stock
  behaviour otherwise;
- the RadarInterface path card.py uses: synthetic 0x80 records are fed as card.py's (address, data, src) tuples and
  as CanData, and it checks
  - the RadarData points (units, sign, ego-speed subtraction, age gate);
  - radarless behaviour (empty tracks, no error) before the first record;
  - that no output is produced between records;
  - the radarUnavailableTemporary report at 20 Hz when records stop;
  - recovery when they resume.
"""
from __future__ import annotations

import argparse
import sys
import zlib
from pathlib import Path


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--opendbc", type=Path, default=None, help="opendbc checkout to import (default: whatever is importable)")
  args = ap.parse_args()
  if args.opendbc is not None:
    sys.path.insert(0, str(args.opendbc.resolve()))

  from opendbc.car import structs
  from opendbc.car.can_definitions import CanData
  from opendbc.car.car_helpers import interfaces
  from opendbc.car.toyota.values import CAR, ToyotaFlags
  from opendbc.car.toyota.ars510.constants import ID80_IDLE_SLOT, ID80_RECORD_LEN
  from opendbc.car.toyota.ars510.objects import encode_slot
  from opendbc.car.toyota.ars510_radar_interface import PROFILE, Ars510RadarInterface

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
    return interfaces[car].get_params(car, fp, car_fw, alpha_long=False, is_release=False, docs=False)

  ars_bus1 = {0x80: 8, 0x85: 8, 0x81: 8, 0x86: 8}
  ars_fw = b'\x018821F0R03100\x00\x00\x00\x00'
  cold_bus1 = {0x191: 8, 0x192: 4, 0x180: 5}  # first ~1 s after power-up: target summaries, no 0x80 / 0x85 yet
  for car in (CAR.TOYOTA_RAV4_TSS2_2022, CAR.TOYOTA_RAV4_TSS2_2023):
    CP = params(car, cold_bus1, ars_fw)
    check(bool(CP.flags & ToyotaFlags.ARS510_RADAR) and not CP.radarUnavailable, f"{car}: ARS510 detected from radar FW at a cold start")
    CP = params(car, ars_bus1)
    check(bool(CP.flags & ToyotaFlags.ARS510_RADAR) and not CP.radarUnavailable, f"{car}: ARS510 detected from 0x80/0x85 on bus 1")
    CP = params(car, cold_bus1, b'\x018821F0R99999\x00\x00\x00\x00')
    check(not CP.flags & ToyotaFlags.ARS510_RADAR and CP.radarUnavailable, f"{car}: other radar FW, no 0x80/0x85 -> stock (radar unavailable)")
  CP = params(CAR.TOYOTA_RAV4_TSS2, ars_bus1)
  check(not CP.flags & ToyotaFlags.ARS510_RADAR, "non-RADAR_ACC RAV4 TSS2 ignores 0x80 on bus 1")

  # ---- RadarInterface on synthetic records ----
  CP = params(CAR.TOYOTA_RAV4_TSS2_2022, ars_bus1)
  RI = interfaces[CP.carFingerprint].RadarInterface(CP)
  check(isinstance(getattr(RI, "ars510", None), Ars510RadarInterface), "Toyota RadarInterface hands over to Ars510RadarInterface")

  def record(age: int) -> bytes:
    # a car 40.0 m ahead, 1.5 m to the LEFT, moving at 20.0 m/s over ground
    slot = encode_slot(long_dist=160 + 40 * 16, lat_dist_left=2048 + 96, long_vel_over_ground=round(510.5 + 20.0 / 0.15 + 0.5), age_cycles=age)
    rec = bytearray(ID80_RECORD_LEN)
    rec[0] = 0xE4
    for s in range(20):
      rec[17 + 36 * s:17 + 36 * (s + 1)] = slot if s == 3 else ID80_IDLE_SLOT
    rec[737:741] = (zlib.crc32(bytes(rec[1:737])) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(rec)

  def frames(rec: bytes) -> list[bytes]:
    return [bytes([0x12]) + rec[0:7]] + [bytes([0x20 | (k & 0xF)]) + rec[7 * k:7 * k + 7] for k in range(1, len(rec) // 7)]

  speed = bytes([0, 0, 0, 0, 0]) + int(18.0 * 3.6 / 0.01).to_bytes(2, "big") + b"\x00"  # 0xB4, 18.0 m/s
  t_ns = 1_000_000_000
  outputs = []

  def step(frs: list[bytes], use_candata: bool) -> None:
    nonlocal t_ns
    t_ns += 10_000_000  # card.py runs at 100 Hz
    batch = [(0xB4, speed, 0)] + [(0x80, f, 1) for f in frs]
    if use_candata:
      batch = [CanData(a, d, s) for a, d, s in batch]
    outputs.append((t_ns, RI.update([(t_ns, batch)])))

  # power-up: ego speed but no object records for 6 s -> radarless behaviour (empty tracks at 20 Hz, no error)
  for _ in range(600):
    step([], use_candata=False)
  boot = [o for _, o in outputs if o is not None]
  check(100 <= len(boot) <= 130 and all(len(o.points) == 0 and not any(o.errors.to_dict().values()) for o in boot),
        f"before the first record: empty RadarData at 20 Hz, no error ({len(boot)} in 6 s)")
  outputs.clear()

  # 100 records at the radar's 60 ms cycle (106 frames spread over 6 card steps), ages 55..
  age = 55
  for k in range(100):
    fr = frames(record(min(age, 126)))
    for j in range(6):
      step(fr[j * 18:(j + 1) * 18], use_candata=bool(k % 2))
    age += 1
  completions = {6 * k + 5 for k in range(100)}
  idx = [i for i, (_, o) in enumerate(outputs) if o is not None]
  extra = [i for i in idx if i not in completions]
  check(completions <= set(idx) and all(i < 5 and len(outputs[i][1].points) == 0 for i in extra),
        f"one RadarData per completed record, none in between (extra outputs {extra}: radarless ticks before the first record)")
  outs = [outputs[i][1] for i in sorted(completions)]
  young = [o for o in outs[:5]]
  check(all(len(o.points) == 0 for o in young), "tracks younger than 60 cycles are held back")
  pts = [o.points[0] for o in outs if len(o.points)]
  check(len(pts) == 95, f"settled track published on every later record (got {len(pts)})")
  p = pts[-1]
  # The synthetic object keeps a fixed range while its vRel is non-zero; the steady profile's velocity-aided range
  # (range_fusion_gain) then settles a little away from the raw range, so only the default profile is exact.
  d_tol = 1e-3 if PROFILE.range_fusion_gain == 0 else 2.5
  check(abs(p.dRel - 40.0) < d_tol and abs(p.yRel - 1.5) < 1e-3,
        f"dRel/yRel units and left-positive sign (got {p.dRel:.3f}, {p.yRel:.3f}; profile fusion gain {PROFILE.range_fusion_gain})")
  # vRel = v_ground * 0.149/0.15 - v_ego (0xB4 reference correction)
  exp = (round(510.5 + 20.0 / 0.15 + 0.5) - 510.5) * 0.15 * 0.149 / 0.15 - 18.0
  check(abs(p.vRel - exp) < 1e-3, f"vRel = over-ground velocity - ego speed (got {p.vRel:.3f}, want {exp:.3f})")
  check(len({q.trackId for q in pts}) == 1, "trackId stable across records")
  check(all(not any(o.errors.to_dict().values()) for o in outs), "no error flags while records arrive")

  # silence: only ego speed, no 0x80 for 1 s
  n0 = len(outputs)
  for _ in range(100):
    step([], use_candata=False)
  silent = outputs[n0:]
  errs = [(t, o) for t, o in silent if o is not None]
  first_err_s = (errs[0][0] - silent[0][0]) / 1e9 + 0.01 if errs else None
  check(bool(errs) and all(o.errors.radarUnavailableTemporary and len(o.points) == 0 for _, o in errs),
        "silent radar -> radarUnavailableTemporary with no points")
  check(first_err_s is not None and 0.35 <= first_err_s <= 0.6, f"first error ~0.5 s after the last record (got {first_err_s})")
  rate = len(errs) / (silent[-1][0] - errs[0][0]) * 1e9 if len(errs) > 1 else 0
  check(15 <= rate <= 25, f"errors repeat at ~20 Hz while silent (got {rate:.1f} Hz)")
  for _ in range(3):
    fr = frames(record(126))
    for j in range(6):
      step(fr[j * 18:(j + 1) * 18], use_candata=False)
  last = [o for _, o in outputs[-18:] if o is not None]
  check(bool(last) and not last[-1].errors.radarUnavailableTemporary and len(last[-1].points) == 1, "recovers when records resume")

  # a corrupted record is dropped, not published and not flagged as a CAN error
  bad = bytearray(record(126))
  bad[100] ^= 0xFF
  n0 = len(outputs)
  fr = frames(bytes(bad))
  for j in range(6):
    step(fr[j * 18:(j + 1) * 18], use_candata=False)
  check(all(o is None for _, o in outputs[n0:]), "CRC-failed record dropped silently")

  print("\nALL OK" if not failures else f"\n{len(failures)} FAILED")
  return 0 if not failures else 1


if __name__ == "__main__":
  raise SystemExit(main())
