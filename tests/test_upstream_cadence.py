"""The direct upstream interface must not publish missing tracks between fresh object scans."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def candidate(monkeypatch):
  class Point:
    trackId, dRel, yRel, vRel = 0, 0.0, 0.0, 0.0

  class RadarData:
    RadarPoint = Point

    def __init__(self):
      self.points = []
      self.errors = types.SimpleNamespace(radarUnavailableTemporary=False)

  class RadarInterfaceBase:
    def __init__(self, CP):
      self.CP, self.frame = CP, 0

  car = types.ModuleType("opendbc.car")
  car.structs = types.SimpleNamespace(RadarData=RadarData)
  interfaces = types.ModuleType("opendbc.car.interfaces")
  interfaces.RadarInterfaceBase = RadarInterfaceBase
  for name, mod in {"opendbc": types.ModuleType("opendbc"), "opendbc.car": car,
                    "opendbc.car.interfaces": interfaces}.items():
    monkeypatch.setitem(sys.modules, name, mod)
  path = Path(__file__).resolve().parents[1] / "upstream" / "ars510_radar.py"
  spec = importlib.util.spec_from_file_location("ars510_cadence_candidate", path)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def test_fresh_scans_do_not_publish_empty_interstitial_tracks(candidate, monkeypatch):
  ri = candidate.RadarInterface(None)
  # One complete object scan every sixth 100-Hz card call, i.e. the radar's ~60 ms cadence.
  monkeypatch.setattr(ri.radar, "update", lambda t, *_: [(1, 60.0, 0.0, -1.0)] if round(t * 100) % 6 == 0 else None)
  records = 0
  for i in range(1, 101):
    out = ri.update([(i * 10_000_000, [(0x80, bytes(8), 1)])])
    if i % 6 == 0:
      assert out is not None and [p.trackId for p in out.points] == [1]
      records += 1
    elif i > 6:
      assert out is None  # an empty list here would delete the healthy track in radard
  assert records == 16

  # An actual completed scan with no objects must still clear the previous tracks.
  monkeypatch.setattr(ri.radar, "update", lambda *_: [])
  out = ri.update([(1_010_000_000, [(0x80, bytes(8), 1)])])
  assert out is not None and out.points == [] and not out.errors.radarUnavailableTemporary


def test_startup_and_stale_scan_fallback_are_preserved(candidate):
  ri = candidate.RadarInterface(None)
  for i in range(1, 6):
    out = ri.update([(i * 10_000_000, [])])
    assert (out is not None) == (i % 5 == 0)
  assert out.points == [] and not out.errors.radarUnavailableTemporary
  ri.last_record_t = 0.05
  for i in range(6, 11):
    assert ri.update([(i * 10_000_000, [])]) is None
  for i in range(11, 16):
    out = ri.update([(600_000_000 + (i - 11) * 10_000_000, [])])
    assert (out is not None) == (i % 5 == 0)
  assert out.points == [] and out.errors.radarUnavailableTemporary
