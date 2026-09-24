"""EXPERIMENTAL, NOT DRIVE-TESTED: openpilot radar tracks from the Toyota / Continental ARS510 native object list.

Installed by `openpilot/install.py` as `opendbc/car/toyota/ars510_radar_interface.py`, together with the `ars510`
decoder package as `opendbc/car/toyota/ars510/`. Toyota's RadarInterface hands over to this class when the car was
detected with an ARS510 (`ToyotaFlags.ARS510_RADAR`: a RADAR_ACC platform whose radar FW is in ARS510_FW_VERSIONS, or
with 0x80 and 0x85 on bus 1 at fingerprinting). Read docs/07 and docs/14 first:
  - vRel has unflagged excursions at 30-100 m;
  - the radar drops new stationary objects once ego is above ~2-3 m/s, so a car that was already stopped when it came
    into view is never listed;
  - radard has no lateral gate.

Why there is no CANParser: the object list is ONE 742-byte record sent as 106 ISO-TP-style frames on 0x80 every
~60 ms. CANParser keeps only the latest value per address (or a per-call list in vl_all), and a DBC cannot say which
part of the record a frame carries (the sequence nibble wraps every 16 frames). The frames are reassembled from the
raw `can_packets` card.py passes in, CRC-checked, and decoded in `ars510`. The DBCs are for cabana, not for parsing.

Output cadence: one RadarData per completed record (~16.7 Hz, inside radard's 8-24 Hz radarTracks window).
- After power-up the radar sends its first object record ~6 s after first CAN. Until the first valid record, this
  behaves like openpilot's radarless default: empty RadarData at 20 Hz, no error, vision-only leads. A warning is
  logged if no record has arrived NO_RECORD_WARN_S after start (e.g. the radar was silenced by the alpha-longitudinal
  radar disable).
- Once records have arrived, if none arrives for STALE_S, a radarUnavailableTemporary RadarData is sent at 20 Hz
  until records resume, instead of radard silently reusing the last tracks.
- A CRC-failed record is dropped. It is not flagged as a CAN error: the staleness check covers sustained loss.
"""
from dataclasses import replace

from opendbc.car import structs
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.toyota.ars510 import OPENPILOT_CONFIG, Ars510NativeRadarInterface
from opendbc.car.toyota.ars510.constants import CAR_BUS, ID80_ADDR, RADAR_BUS, TOYOTA_SPEED_ADDR

STALE_S = 0.5  # radard has no staleness check of its own on track content
NO_RECORD_WARN_S = 15.0
EMPTY_PERIOD = 5  # without records, report every 5th update (card calls update at 100 Hz -> 20 Hz)
WANTED = {(RADAR_BUS, ID80_ADDR), (CAR_BUS, TOYOTA_SPEED_ADDR)}


class Ars510RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.ars = Ars510NativeRadarInterface(replace(OPENPILOT_CONFIG, include_metadata=False))
    self.start_s: float | None = None
    self.last_record_s: float | None = None
    self.warned = False

  def update(self, can_packets):
    self.frame += 1
    latest = None
    now_s = None
    for nanos, frames in can_packets:
      now_s = nanos * 1e-9
      # card.py passes plain (address, data, src) tuples; CanData is a NamedTuple in the same order
      for address, dat, src in frames:
        if (src, address) in WANTED:
          out = self.ars.update_frame(now_s, src, address, dat)
          if out is not None:
            latest = out
    if now_s is None:
      return None
    if self.start_s is None:
      self.start_s = now_s

    if latest is None:
      if self.frame % EMPTY_PERIOD != 0:
        return None
      if self.last_record_s is None:  # radar not started yet (or silenced): radarless behaviour, no error
        if not self.warned and now_s - self.start_s > NO_RECORD_WARN_S:
          carlog.warning("ARS510: no valid 0x80 object record on bus 1 yet; radar tracks unavailable")
          self.warned = True
        return structs.RadarData()
      if now_s - self.last_record_s > STALE_S:
        ret = structs.RadarData()
        ret.errors.radarUnavailableTemporary = True
        return ret
      return None

    self.last_record_s = latest["time_s"]
    ret = structs.RadarData()
    points = []
    # RadarPoint is trackId / dRel / yRel / vRel (aRel, yvRel, measured are deprecated in current cereal).
    # OPENPILOT_CONFIG never publishes a NaN vRel, which would poison radard's per-track Kalman filter.
    for p in latest["radarData"]["points"]:
      pt = structs.RadarData.RadarPoint()
      pt.trackId = p["trackId"]
      pt.dRel = p["dRel"]
      pt.yRel = p["yRel"]
      pt.vRel = p["vRel"]
      points.append(pt)
    ret.points = points
    return ret
