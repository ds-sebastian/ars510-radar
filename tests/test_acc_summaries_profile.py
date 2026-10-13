"""openpilot/standalone/ars510_acc_summaries.py (research profile `acc_summaries`, docs/11): the radar's ACC target as in
`acc`, plus the target-summary cars (0x191-0x194) while the ACC target is present, the ACC car once, other summaries as
trackId 32 + code with a range-slope speed, and nothing from a silent radar."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import sys
from pathlib import Path

import pytest

from ars510.support import parse_acc_target
from test_upstream_candidate import _fake_opendbc

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "data" / "sample" / "highway_acc_anchor_24s.csv.gz"


@pytest.fixture(scope="module")
def mod():
  saved = {k: sys.modules.get(k) for k in ("opendbc", "opendbc.car", "opendbc.car.interfaces")}
  sys.modules.update(_fake_opendbc())
  try:
    spec = importlib.util.spec_from_file_location("ars510_acc_summaries", REPO / "openpilot" / "standalone" / "ars510_acc_summaries.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    yield m
  finally:
    for k, v in saved.items():
      if v is None:
        sys.modules.pop(k, None)
      else:
        sys.modules[k] = v


def _cycle(k, acc_m, cars, acc=True, clock_us=None):
  """One 60 ms radar cycle as (address, data) frames in bus order: the 0x190 clock, the ACC target (0x235 / 0x237) at
  acc_m with id 7 and vRel +4 m/s (absent if not acc), and up to two summaries [(code, range m or None for the ACC car's
  fingerprint, lateral m), ...] in 0x191 / 0x192 and 0x193 / 0x194."""
  ts = 1_000_000 + 60_000 * k if clock_us is None else clock_us
  acc_code = round(acc_m / 0.025)
  f235 = ((1 << 59) | ((5 if acc else 1) << 48) | (1056 << 29) | 7).to_bytes(8, "big")
  f237 = ((acc_code << 39) | (2000 << 27) | (int(acc) << 10)).to_bytes(8, "big")
  frames = [(0x190, bytes([0x0A, 0]) + ts.to_bytes(4, "big") + b"\x00"), (0x235, f235), (0x237, f237)]
  slots = list(cars) + [None] * (2 - len(cars))
  for car, (ia, pa) in zip(slots, ((0x191, 0x192), (0x193, 0x194)), strict=True):
    if car is None:  # empty slot: identity 127, sentinel position
      frames += [(ia, bytes([254, 0, 0, 0, 0, 0, 0, 0])), (pa, b"\x00\xff\x00\xff")]
      continue
    code, d, y = car
    rc = 160 + (2 * acc_code) // 5 if d is None else round(d * 16 + 160)
    frames += [(ia, bytes([182, 0, 0, code << 2, 0, 0, 0, 0])), (pa, rc.to_bytes(2, "big") + round(y / 0.015 + 2048).to_bytes(2, "big"))]
  return frames


def _run(mod, cycles, ri=None, t0=0.0):
  """Feed cycles at card.py's 100 Hz, one radar cycle per six update calls; return (ri, reports with their time)."""
  ri, outs = ri or mod.RadarInterface(None), []
  for i, frames in enumerate(cycles):
    for j in range(6):
      t = t0 + (6 * i + j) * 0.01
      out = ri.update([(int(t * 1e9), [(a, d, 1) for a, d in frames] if j == 0 else [])])
      if out is not None:
        outs.append((t, out))
  return ri, outs


def test_publishes_the_decoded_acc_target_like_acc(mod):
  """The bundled sample (ACC frames, 0x192 only, no 0x190 clock): exactly the ACC target, decoded as ars510.support does."""
  ri, last, reports, points = mod.RadarInterface(None), {}, 0, 0
  for row in csv.DictReader(gzip.open(SAMPLE, "rt")):
    bus, addr, dat = int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])
    if bus == 1 and addr in (0x235, 0x237):
      last[addr] = dat
    out = ri.update([(int(float(row["t_s"]) * 1e9), [(addr, dat, bus)])])
    if out is None:
      continue
    reports += 1
    want = parse_acc_target(last[0x235], last[0x237]) if len(last) == 2 else None
    assert (want is None) == (not out.points)
    if want is not None:
      (p,) = out.points
      points += 1
      assert p.trackId == want.target_id < mod.SUMMARY_ID
      assert (p.dRel, p.yRel, p.vRel) == pytest.approx((want.d_rel, want.y_rel, want.v_rel), abs=1e-9)
  assert reports > 300 and points > 0.9 * reports


def test_acc_target_alone_when_no_summary_car(mod):
  _, outs = _run(mod, [_cycle(k, 30.0, []) for k in range(20)])
  assert outs and all([(p.trackId, p.dRel, p.yRel, p.vRel) for p in o.points] == [(7, 30.0, 0.0, 4.0)] for _, o in outs)


def test_acc_car_once_and_other_summary_as_32_plus_code_with_slope_speed(mod):
  # summary 1 carries the ACC car's quantization fingerprint, summary 2 is a car at 40 m closing 0.36 m per 60 ms cycle
  cycles = [_cycle(k, 30.0 - 0.24 * k, [(3, None, 0.0), (9, 40.0 - 0.36 * k, 3.6)]) for k in range(30)]
  _, outs = _run(mod, cycles)
  ids = [sorted(p.trackId for p in o.points) for _, o in outs]
  assert all(i == [7] for i in ids[:6])  # a summary is published once 8 cycles exist
  assert ids[-1] == [7, mod.SUMMARY_ID + 9] and all(i in ([7], [7, 41]) for i in ids)
  (s,) = [p for p in outs[-1][1].points if p.trackId == 41]
  assert s.vRel == pytest.approx(-6.0, abs=0.05) and s.yRel == pytest.approx(3.6, abs=0.01)
  assert s.dRel == pytest.approx(round((40.0 - 0.36 * 29) * 16) / 16, abs=1e-9)


def test_summary_that_is_not_the_acc_car_is_kept(mod):
  # same range code as the ACC car but 0.5 m to the side: not the fingerprint, so it is its own point
  cycles = [_cycle(k, 30.0, [(3, None, 0.5)]) for k in range(12)]
  _, outs = _run(mod, cycles)
  assert sorted(p.trackId for p in outs[-1][1].points) == [7, 35]
  assert next(p for p in outs[-1][1].points if p.trackId == 35).vRel == pytest.approx(0.0, abs=1e-9)


def test_summaries_only_while_the_acc_target_is_present(mod):
  cars = lambda k: [(9, 40.0 - 0.36 * k, 3.6)]  # noqa: E731
  ri, outs = _run(mod, [_cycle(k, 30.0, cars(k)) for k in range(20)])
  assert sorted(p.trackId for p in outs[-1][1].points) == [7, 41]
  ri, outs = _run(mod, [_cycle(k, 30.0, cars(k), acc=False) for k in range(20, 40)], ri, t0=1.2)
  assert outs and all(o.points == [] and not o.errors.radarUnavailableTemporary for _, o in outs)
  ri, outs = _run(mod, [_cycle(k, 30.0, cars(k)) for k in range(40, 42)], ri, t0=2.4)
  assert sorted(p.trackId for p in outs[-1][1].points) == [7, 41]  # the thread kept running while the target was absent


def test_range_jump_restarts_the_thread(mod):
  cycles = [_cycle(k, 30.0, [(9, 40.0 if k < 12 else 50.0, 3.6)]) for k in range(18)]
  _, outs = _run(mod, cycles)
  after = [sorted(p.trackId for p in o.points) for t, o in outs if t > 12 * 0.06 + 0.01]
  assert after[0] == [7] and after[-1] == [7]  # 6 cycles after the jump: not yet 8 in the new thread
  _, outs = _run(mod, cycles + [_cycle(k, 30.0, [(9, 50.0, 3.6)]) for k in range(18, 22)])
  assert sorted(p.trackId for p in outs[-1][1].points) == [7, 41]


def test_silent_radar_reports_unavailable_and_recovers(mod):
  ri, outs = _run(mod, [_cycle(k, 30.0, [(9, 40.0, 3.6)]) for k in range(12)])
  t_end = outs[-1][0]
  silent = [o for o in (ri.update([(int((t_end + 0.01 * i) * 1e9), [])]) for i in range(1, 101)) if o is not None]
  assert silent[-1].errors.radarUnavailableTemporary and silent[-1].points == []
  _, outs = _run(mod, [_cycle(k, 30.0, [(9, 40.0, 3.6)]) for k in range(40, 42)], ri, t0=t_end + 1.1)
  assert not outs[-1][1].errors.radarUnavailableTemporary and [p.trackId for p in outs[-1][1].points][0] == 7
  never = mod.RadarInterface(None)
  assert all(o is None or (o.points == [] and not o.errors.radarUnavailableTemporary)
             for o in (never.update([(int(i * 1e7), [(0x100, bytes(8), 0)])]) for i in range(20)))
