"""Toyota / Continental ARS510 front radar (RAV4 2022+, fwdRadar 8821F0R03100): the car Toyota's ACC follows.

Besides its raw object list (0x80, one record over 106 frames), the radar sends the one target its own ACC acts on
(ACC_TARGET_1 / ACC_TARGET_2 in toyota_tss2_ars510.dbc, the cycle clock in ACC_TARGET_3): a converged, in-path track chosen by the radar's tracker, with
distance, lateral position, closing speed and an ID that changes when the radar switches targets. Toyota's ACC acts on
this target alone. This interface publishes that target as openpilot's only radar point; radard matches it to the
camera's lead as for any radar, and every other car comes from the camera. The frames repeat at 50 Hz; a report goes out
once per 60 ms radar cycle, when the radar's cycle clock (ACC_TARGET_3) advances, with or without a target. Standalone
form of the radar_interface.py change in ars510-radar's upstream/opendbc_ars510.patch; docs/17 ("The ACC target alone")
has the evidence.
"""
from opendbc.can import CANParser
from opendbc.car.structs import RadarData
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_DBC = "toyota_tss2_ars510"


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args, **kwargs):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args, **kwargs)
    self.rcp = CANParser(RADAR_DBC, [("ACC_TARGET_1", 50), ("ACC_TARGET_2", 50), ("ACC_TARGET_3", 50)], 1)
    self.trigger_msg = 0x237
    self.updated_messages = set()
    self.cycle = 0

  def update(self, can_strings):
    self.updated_messages.update(self.rcp.update(can_strings))
    if self.trigger_msg not in self.updated_messages:
      return None
    cycle = self.rcp.vl["ACC_TARGET_3"]["TIMESTAMP"]
    if cycle == self.cycle:  # the frames repeat at 50 Hz: one report per 60 ms radar cycle
      return None
    self.cycle = cycle
    self.updated_messages.clear()

    ret = RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True
      return ret

    target, position = self.rcp.vl["ACC_TARGET_1"], self.rcp.vl["ACC_TARGET_2"]
    if target["STATE"] == 5 and position["PRESENT"]:  # 1 = idle, with every field zero
      pt = RadarData.RadarPoint()
      pt.trackId = int(target["TARGET_ID"])
      pt.dRel = position["LONG_DIST"]
      pt.yRel = position["LAT_DIST"]
      pt.vRel = target["REL_SPEED"]
      ret.points = [pt]  # assigned as a list: forks with capnp-backed structs (sunnypilot) take list assignment only
    return ret
