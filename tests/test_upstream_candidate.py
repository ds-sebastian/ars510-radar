"""The single-file upstream candidate (upstream/ars510_radar.py) must publish exactly what FUSED_CONFIG publishes."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from ars510 import FUSED_CONFIG, BASE_CONFIG, Ars510NativeRadarInterface

REPO = Path(__file__).resolve().parents[1]
SAMPLES = sorted((REPO / "data" / "sample").glob("*.csv.gz"))


def _fake_opendbc() -> dict:
  """Just enough of opendbc.car for the candidate to import: structs.RadarData and RadarInterfaceBase."""
  class Point:
    trackId, dRel, yRel, vRel = 0, 0.0, 0.0, 0.0

  class Errors:
    radarUnavailableTemporary = False

  class RadarData:
    RadarPoint = Point

    def __init__(self):
      self.points, self.errors = [], Errors()

  class RadarInterfaceBase:
    def __init__(self, CP):
      self.CP, self.frame = CP, 0

  car = types.ModuleType("opendbc.car")
  car.structs = types.SimpleNamespace(RadarData=RadarData)
  interfaces = types.ModuleType("opendbc.car.interfaces")
  interfaces.RadarInterfaceBase = RadarInterfaceBase
  return {"opendbc": types.ModuleType("opendbc"), "opendbc.car": car, "opendbc.car.interfaces": interfaces}


@pytest.fixture(scope="module")
def candidate():
  saved = {k: sys.modules.get(k) for k in ("opendbc", "opendbc.car", "opendbc.car.interfaces")}
  sys.modules.update(_fake_opendbc())
  try:
    spec = importlib.util.spec_from_file_location("ars510_radar_candidate", REPO / "upstream" / "ars510_radar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
  finally:
    for k, v in saved.items():
      if v is None:
        sys.modules.pop(k, None)
      else:
        sys.modules[k] = v


def _frames(path: Path):
  with gzip.open(path, "rt") as fh:
    for row in csv.DictReader(fh):
      yield float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.name)
def test_candidate_equals_fused_on_real_samples(candidate, sample):
  ref, cand = Ars510NativeRadarInterface(FUSED_CONFIG), candidate.Ars510Radar()
  records = 0
  for frame in _frames(sample):
    a, b = ref.update_frame(*frame), cand.update(*frame)
    assert (a is None) == (b is None)
    if a is not None:
      records += 1
      assert b == [(p["trackId"], p["dRel"], p["yRel"], p["vRel"]) for p in a["radarData"]["points"]]
  assert records > 300


def _lead_vrel(points) -> list[float]:
  """vRel of the nearest in-lane point of each record."""
  return [min(((d, v) for _, d, y, v in pts if abs(y) < 1.8), default=(0.0, 0.0))[1] for pts in points if pts]


def test_the_filter_removes_the_sample_excursion(candidate):
  """Fails without the speed filter: the unfiltered decode dives to about -6 m/s on this lead (docs/07, drive A)."""
  sample = REPO / "data" / "sample" / "highway_vrel_excursion_25s.csv.gz"
  raw_iface, cand = Ars510NativeRadarInterface(BASE_CONFIG), candidate.Ars510Radar()
  raw, filtered = [], []
  for frame in _frames(sample):
    r, c = raw_iface.update_frame(*frame), cand.update(*frame)
    if r is not None:
      raw.append([(p["trackId"], p["dRel"], p["yRel"], p["vRel"]) for p in r["radarData"]["points"]])
    if c is not None:
      filtered.append(c)
  assert min(_lead_vrel(raw)) < -5.0
  assert min(_lead_vrel(filtered)) > -2.0


def test_radar_interface_publishes_points_and_reports_a_silent_radar(candidate):
  ri = candidate.RadarInterface(CP=None)
  frames = list(_frames(SAMPLES[0]))
  out = []
  for t, bus, addr, dat in frames:
    out.append(ri.update([(int(t * 1e9), [(addr, dat, bus)])]))
  published = [r for r in out if r is not None and r.points]
  assert published and all(isinstance(p.vRel, float) for p in published[-1].points)
  t_end = frames[-1][0]
  silent = [ri.update([(int((t_end + 0.1 * k) * 1e9), [])]) for k in range(1, 20)]
  assert any(r is not None and r.errors.radarUnavailableTemporary for r in silent)
