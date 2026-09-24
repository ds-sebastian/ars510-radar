"""SKETCH, NOT DRIVE-TESTED: an opendbc-style RadarInterface for the ARS510.

This shows the shape of an integration; it is not a pull request. Read docs/07_openpilot_integration.md first:
vRel has unflagged excursions, radard has no lateral gate, and one NaN vRel poisons radard's Kalman filter.

Where it would go: opendbc/car/toyota/radar_interface.py currently parses TSS2 radar tracks at 0x180-0x19F,
which on the ARS510 are unrelated messages (0x180 is a constant; 0x191-0x194 are target summaries). The
RAV4 TSS2 platforms set radarUnavailable because they have no radar DBC. A real integration would select
this class for ARS510 cars (e.g. by radar firmware 8821F0R03100 or by the presence of 0x80 on bus 1).

`can_packets` is what card.py passes: list[(nanos, list[CanData(address, dat, src)])], all buses.
"""
from __future__ import annotations

import math

from opendbc.car.interfaces import RadarInterfaceBase  # type: ignore
from opendbc.car.structs import RadarData  # type: ignore

from ars510 import OPENPILOT_CONFIG, Ars510NativeRadarInterface
from dataclasses import replace

STALE_S = 0.5  # radard has no staleness check: report unavailable ourselves if records stop


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.ars = Ars510NativeRadarInterface(replace(OPENPILOT_CONFIG, include_metadata=False))
    self.last_record_s: float | None = None
    self.last_crc_failures = 0

  def update(self, can_packets):
    latest = None
    now_s = None
    for nanos, frames in can_packets:
      now_s = nanos * 1e-9
      for f in frames:
        out = self.ars.update_frame(now_s, f.src, f.address, bytes(f.dat))
        if out is not None:
          latest = out
    if latest is None:
      # nothing new; flag a silent radar instead of letting radard reuse old tracks
      if now_s is not None and self.last_record_s is not None and now_s - self.last_record_s > STALE_S:
        ret = RadarData()
        ret.errors.radarUnavailableTemporary = True
        self.last_record_s = None
        return ret
      return None

    self.last_record_s = latest["time_s"]
    ret = RadarData()
    if self.ars.crc_failures != self.last_crc_failures:
      ret.errors.canError = True
      self.last_crc_failures = self.ars.crc_failures
    points = []
    for p in latest["radarData"]["points"]:
      if not math.isfinite(p["vRel"]):  # OPENPILOT_CONFIG already drops these; belt and braces
        continue
      pt = RadarData.RadarPoint()
      pt.trackId = p["trackId"]
      pt.dRel = p["dRel"]
      pt.yRel = p["yRel"]
      pt.vRel = p["vRel"]
      points.append(pt)
    ret.points = points
    return ret
