"""upstream/ars510_acc_target.py (the ACC target alone, docs/10) must publish exactly the decoded ACC target."""
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
IDLE_235, IDLE_237 = bytes.fromhex("0061648000000000"), bytes.fromhex("00000000003E8000")  # no target: status 1, bit 10 clear


@pytest.fixture(scope="module")
def mod():
  saved = {k: sys.modules.get(k) for k in ("opendbc", "opendbc.car", "opendbc.car.interfaces")}
  sys.modules.update(_fake_opendbc())
  try:
    spec = importlib.util.spec_from_file_location("ars510_acc_target", REPO / "upstream" / "ars510_acc_target.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    yield m
  finally:
    for k, v in saved.items():
      if v is None:
        sys.modules.pop(k, None)
      else:
        sys.modules[k] = v


def test_publishes_the_decoded_acc_target_at_20_hz(mod):
  ri, last, reports, points = mod.RadarInterface(None), {}, 0, 0
  for row in csv.DictReader(gzip.open(SAMPLE, "rt")):
    t, bus, addr, dat = float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])
    if bus == 1 and addr in (0x235, 0x237):
      last[addr] = dat
    out = ri.update([(int(t * 1e9), [(addr, dat, bus)])])
    if out is None:
      continue
    reports += 1
    want = parse_acc_target(last[0x235], last[0x237]) if len(last) == 2 else None
    assert (want is None) == (not out.points)
    if want is not None:
      (p,) = out.points
      points += 1
      assert (p.trackId, p.dRel, p.yRel, p.vRel) == (want.target_id, want.d_rel, want.y_rel, want.v_rel)
  assert ri.frame // 5 == reports and points > 0.99 * reports  # one report per 5 updates (card calls at 100 Hz)


def test_no_target_no_point_and_a_silent_radar_is_an_error(mod):
  ri = mod.RadarInterface(None)
  out = [ri.update([(int(i * 1e7), [(0x235, IDLE_235, 1), (0x237, IDLE_237, 1)])]) for i in range(1, 6)][-1]
  assert out.points == [] and not out.errors.radarUnavailableTemporary
  out = [ri.update([(int(1e9 + i * 1e7), [(0x100, bytes(8), 0)])]) for i in range(1, 6)][-1]
  assert out.points == [] and out.errors.radarUnavailableTemporary
