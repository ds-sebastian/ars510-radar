"""Toyota / Continental ARS510 front radar (RAV4 2022+, fwdRadar 8821F0R03100): the car Toyota's ACC follows.

Besides its raw object list (0x80, one record over 106 frames), the radar sends the one target its own ACC acts on
(ACC_TARGET_1 / ACC_TARGET_2 in toyota_tss2_ars510.dbc): a converged, in-path track chosen by the radar's tracker, with
distance, lateral position, closing speed and an ID that changes when the radar switches targets. Toyota's ACC uses
nothing else. This interface publishes that target as openpilot's only radar point; radard matches it to the camera's
lead as for any radar, and every other car comes from the camera. ars510-radar docs/10 ("The ACC target alone") has
the evidence.
"""
from opendbc.can import CANParser
from opendbc.car.structs import RadarData
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_DBC = "toyota_tss2_ars510"


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args, **kwargs):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args, **kwargs)
    self.rcp = CANParser(RADAR_DBC, [("ACC_TARGET_1", 50), ("ACC_TARGET_2", 50)], 1)

  def update(self, can_strings):
    self.frame += 1
    self.rcp.update(can_strings)
    if self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None

    ret = RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True
      return ret

    target, position = self.rcp.vl["ACC_TARGET_1"], self.rcp.vl["ACC_TARGET_2"]
    if target["STATE"] == 5 and position["PRESENT"]:  # 1 = no target, with every field zero
      pt = RadarData.RadarPoint()
      pt.trackId = int(target["TARGET_ID"])
      pt.dRel = position["LONG_DIST"]
      pt.yRel = position["LAT_DIST"]
      pt.vRel = target["REL_SPEED"]
      ret.points = [pt]  # assigned as a list: forks with capnp-backed structs (sunnypilot) have no append
    return ret
