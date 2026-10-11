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
    acc += any(p.trackId >= mod.ACC_TRACK for p in out.points)
  assert reports > 300 and acc > 0.9 * reports
