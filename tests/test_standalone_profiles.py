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

from test_upstream_candidate import _fake_opendbc

REPO = Path(__file__).resolve().parents[1]
FILES = sorted((REPO / "openpilot" / "standalone").glob("ars510_*.py"))


@pytest.fixture(params=FILES, ids=lambda p: p.stem)
def mod(request):
  saved = {k: sys.modules.get(k) for k in ("opendbc", "opendbc.car", "opendbc.car.interfaces")}
  sys.modules.update(_fake_opendbc())
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


def _cycle(k, acc_m, cars):
  """One 60 ms radar cycle as CAN frames: the 0x190 clock, the ACC target (0x235 / 0x237) at acc_m and the summaries in cars
  [(code, range m, lateral m), ...] in 0x191 / 0x192 and 0x193 / 0x194."""
  ts = 1_000_000 + 60_000 * k
  acc_code = round(acc_m / 0.025)
  f235 = ((1 << 59) | (5 << 48) | (1056 << 29) | 7).to_bytes(8, "big")  # status 5, id 7, vRel +4 m/s
  f237 = ((acc_code << 39) | (2000 << 27) | (1 << 10)).to_bytes(8, "big")
  frames = [(0x190, bytes([0x0A, 0]) + ts.to_bytes(4, "big") + b"\x00"), (0x235, f235), (0x237, f237)]
  for (code, d, y), (ia, pa) in zip(cars, ((0x191, 0x192), (0x193, 0x194))):
    rc = 160 + (2 * acc_code) // 5 if d is None else round(d * 16 + 160)
    frames += [(ia, bytes([182, 0, 0, code << 2, 0, 0, 0, 0])), (pa, rc.to_bytes(2, "big") + round(y / 0.015 + 2048).to_bytes(2, "big"))]
  return [(int(k * 0.06e9 + i * 1e6), [(a, d, 1)]) for i, (a, d) in enumerate(frames)]


def test_acc_summaries_adds_summary_cars_once_and_within_60_m(mod):
  if not hasattr(mod, "SUMMARY_ID"):
    pytest.skip("acc_summaries only")
  for cars, n_extra in (([(3, None, 0.0), (9, 40.0, 3.6)], 1),   # summary 1 is the ACC car, summary 2 another car at 40 m
                        ([(3, None, 0.0), (9, 80.0, 3.6)], 0)):  # beyond 60 m: not published
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
