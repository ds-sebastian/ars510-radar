"""The standalone profile files (openpilot/standalone/, research only) run on the bundled samples: one report per radar
record, finite points, and the ACC target among them as its own track."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import math
import sys
from pathlib import Path

import pytest

from ars510.support import ACC_CHECK
from test_upstream_candidate import _fake_opendbc

REPO = Path(__file__).resolve().parents[1]
FILES = sorted((REPO / "openpilot" / "standalone").glob("ars510_*.py"))


@pytest.fixture(params=FILES, ids=lambda p: p.stem)
def mod(request):
  saved = {k: sys.modules.get(k) for k in ("opendbc", "opendbc.car", "opendbc.car.structs", "opendbc.car.interfaces")}
  fake = _fake_opendbc()
  fake["opendbc.car.structs"] = fake["opendbc.car"].structs  # for `from opendbc.car.structs import RadarData`
  sys.modules.update(fake)
  try:
    spec = importlib.util.spec_from_file_location(request.param.stem, request.param)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    yield m
  finally:
    for k, v in saved.items():
      if v is None:
        sys.modules.pop(k, None)
      else:
        sys.modules[k] = v


def test_reports_finite_points_with_the_acc_target_as_a_track(mod):
  ri, reports, acc = mod.RadarInterface(None), 0, 0
  for row in csv.DictReader(gzip.open(REPO / "data" / "sample" / "highway_acc_anchor_24s.csv.gz", "rt")):
    out = ri.update([(int(float(row["t_s"]) * 1e9), [(int(row["address"], 0), bytes.fromhex(row["data_hex"]), int(row["bus"]))])])
    if out is None or not out.points:
      continue
    reports += 1
    assert all(math.isfinite(v) for p in out.points for v in (p.dRel, p.yRel, p.vRel))
    acc += any(_is_acc_point(mod, p) for p in out.points)
  assert reports > 300 and acc > 0.9 * reports


def _is_acc_point(mod, p):
  """shared_* give the ACC target trackId ACC_TRACK and above; acc_summaries keeps the radar's target ID (below SUMMARY_ID)."""
  return p.trackId >= mod.ACC_TRACK if hasattr(mod, "ACC_TRACK") else p.trackId < mod.SUMMARY_ID


def _with_check_byte(address, frame):
  """The frame with the radar's check byte in byte 0 (ars510.support.acc_check's table), as every recorded frame has."""
  const, _, cols = ACC_CHECK[address]
  for i, col in enumerate(cols):
    const ^= col if frame[1 + i // 8] >> (7 - i % 8) & 1 else 0
  return bytes([const]) + frame[1:]


def _cycle(k, acc_m, cars):
  """One 60 ms radar cycle as CAN frames: the 0x190 clock, the ACC target (0x235 / 0x237) at acc_m and the summaries in cars
  [(code, range m, lateral m), ...] in 0x191 / 0x192 and 0x193 / 0x194."""
  ts = 1_000_000 + 60_000 * k
  acc_code = round(acc_m / 0.025)
  f235 = ((1 << 59) | (5 << 48) | (1056 << 29) | 7).to_bytes(8, "big")  # status 5, id 7, vRel +4 m/s
  f237 = _with_check_byte(0x237, ((acc_code << 39) | (2000 << 27) | (1 << 10)).to_bytes(8, "big"))
  frames = [(0x190, bytes([0x0A, 0]) + ts.to_bytes(4, "big") + b"\x00"), (0x235, f235), (0x237, f237)]
  for (code, d, y), (ia, pa) in zip(cars, ((0x191, 0x192), (0x193, 0x194))):
    rc = 160 + (2 * acc_code) // 5 if d is None else round(d * 16 + 160)
    frames += [(ia, bytes([182, 0, 0, code << 2, 0, 0, 0, 0])), (pa, rc.to_bytes(2, "big") + round(y / 0.015 + 2048).to_bytes(2, "big"))]
  return [(int(k * 0.06e9 + i * 1e6), [(a, d, 1)]) for i, (a, d) in enumerate(frames)]


def test_acc_summaries_adds_summary_cars_once_and_within_40_m(mod):
  if not hasattr(mod, "SUMMARY_ID"):
    pytest.skip("acc_summaries only")
  for cars, n_extra in (([(3, None, 0.0), (9, 40.0, 3.6)], 1),   # summary 1 is the ACC car, summary 2 another car at 40 m
                        ([(3, None, 0.0), (9, 60.0, 3.6)], 0),   # 60 -> 49.6 m: beyond 40 m, not published
                        ([(3, None, 0.0), (9, 80.0, 3.6)], 0)):  # far beyond: not published
    ri, last = mod.RadarInterface(None), None
    for k in range(30):
      for pk in _cycle(k, 30.0 - 0.24 * k, [(c, d if d is None else d - 0.36 * k, y) for c, d, y in cars]):
        out = ri.update([pk])
        last = out if out is not None and out.points else last
    acc = [p for p in last.points if p.trackId < mod.SUMMARY_ID]
    summ = [p for p in last.points if p.trackId >= mod.SUMMARY_ID]
    assert len(acc) == 1 and len(summ) == n_extra
    if n_extra:
      assert summ[0].trackId == mod.SUMMARY_ID + 9 and abs(summ[0].vRel - (-6.0)) < 0.1  # 0.36 m per 60 ms cycle


def test_acc_summaries_ignores_a_one_cycle_all_ones_summary_word(mod):
  """The radar occasionally sends 0x192 / 0x194 as FF FF FF FF for one cycle inside a live track while the 0x191 / 0x193
  companion stays valid (4 + 3 cases on two cars). Decoded it is 501.9 m; it must not enter the slope history, or the
  next eight reports of that car carry speeds of hundreds of m/s."""
  if not hasattr(mod, "SUMMARY_ID"):
    pytest.skip("acc_summaries only")
  ri, speeds = mod.RadarInterface(None), []
  for k in range(40):
    for pk in _cycle(k, 30.0 - 0.24 * k, [(3, None, 0.0), (9, 40.0 - 0.36 * k, 3.6)]):
      t, ((a, d, b),) = pk
      if k == 20 and a == 0x194:
        pk = (t, [(a, b"\xff\xff\xff\xff", b)])
      out = ri.update([pk])
      if out is not None:
        speeds += [p.vRel for p in out.points if p.trackId >= mod.SUMMARY_ID]
  assert speeds and all(abs(v - (-6.0)) < 0.5 for v in speeds)


def test_acc_summaries_restarts_the_speed_after_a_one_cycle_range_jump(mod):
  """A valid-looking summary word can jump for one cycle (4.8 -> 49.9 -> 4.3 m seen once on each car). The slope must not run
  through it: the car drops out for a moment and comes back with its true speed."""
  if not hasattr(mod, "SUMMARY_ID"):
    pytest.skip("acc_summaries only")
  ri, speeds = mod.RadarInterface(None), []
  for k in range(50):
    d = 40.0 - 0.36 * k
    for pk in _cycle(k, 30.0 - 0.24 * k, [(3, None, 0.0), (9, d + (45.0 if k == 20 else 0.0), 3.6)]):
      out = ri.update([pk])
      if out is not None:
        speeds += [(k, p.vRel) for p in out.points if p.trackId >= mod.SUMMARY_ID]
  assert all(abs(v - (-6.0)) < 0.5 for _, v in speeds) and any(k > 32 for k, _ in speeds)


def test_acc_summaries_speed_follows_the_radar_clock_not_can_arrival(mod):
  """Summary speeds come from a filter timed by the radar's 0x190 cycle clock: CAN arrival jitter (here up to 20 ms per cycle)
  leaves them exactly unchanged. Without 0x190 the 8-range slope over CAN time still gives the speed."""
  if not hasattr(mod, "SUMMARY_ID"):
    pytest.skip("acc_summaries only")
  import random

  def speeds(jitter_ns, clock=True):
    rng, ri, out_v = random.Random(7), mod.RadarInterface(None), []
    for k in range(60):
      j = int(rng.uniform(0, jitter_ns))
      for nanos, frames in _cycle(k, 30.0 - 0.24 * k, [(3, None, 0.0), (9, 39.0 - 0.36 * k, 3.6)]):
        if frames[0][0] == 0x190 and not clock:
          continue
        out = ri.update([(nanos + (0 if frames[0][0] == 0x190 else j), frames)])
        if out is not None and k > 20:
          out_v += [p.vRel for p in out.points if p.trackId >= mod.SUMMARY_ID]
    return out_v

  steady, jittered, no_clock = speeds(0), speeds(20e6), speeds(0, clock=False)
  assert steady and jittered == steady and max(abs(v + 6.0) for v in steady) < 0.15  # true speed -6 m/s
  assert no_clock and max(abs(v + 6.0) for v in no_clock) < 0.15


def test_acc_summaries_unwraps_a_wrapped_acc_lateral_distance(mod):
  if mod.__name__ != "ars510_acc_summaries":
    pytest.skip("acc_summaries only")
  # a recorded 0x237 whose check byte carries the hidden 13th lateral bit: LAT_DIST reads -19.70 m, the target is 21.26 m left
  wrapped, present_235 = bytes.fromhex("AD026580F2E8C550"), bytes.fromhex("EA056C81CBDFAA1B")
  ri = mod.RadarInterface(None)
  outs = [ri.update([(int(i * 1e7), [(0x235, present_235, 1), (0x237, wrapped, 1)])]) for i in range(1, 6)]
  (p,) = [o for o in outs if o is not None][-1].points
  assert p.yRel == pytest.approx(-19.70 + 40.96)
