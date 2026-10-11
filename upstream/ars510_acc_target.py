"""Toyota / Continental ARS510 front radar (RAV4 2022+, fwdRadar 8821F0R03100): the car Toyota's ACC follows.

Besides its raw object list (0x80), the radar sends the one target its own ACC acts on (0x235 / 0x237): a converged,
in-path track chosen by the radar's tracker, with distance, lateral position and closing speed. Toyota's ACC uses
nothing else. This interface publishes that target as openpilot's only radar point; radard matches it to the camera's
lead as for any radar, and every other car comes from the camera.
Alternative single-file candidate to ars510_radar.py; ars510-radar docs/10 ("The ACC target alone") has the evidence.
"""
from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_BUS, ACC_SPEED_ADDR, ACC_POS_ADDR = 1, 0x235, 0x237
STALE_S = 0.5  # no ACC frame for this long: the radar is not sending


def be_bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.speed = self.pos = self.last_t = None

  def update(self, can_packets):
    self.frame += 1
    t = None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src != RADAR_BUS or address not in (ACC_SPEED_ADDR, ACC_POS_ADDR) or len(dat) != 8:
          continue
        self.last_t = t
        if address == ACC_SPEED_ADDR:  # target id, closing speed; status nibble 5 = target present
          self.speed = (be_bits(dat, 0, 5), (be_bits(dat, 29, 11) - 1024) * 0.125) if dat[1] & 0x0F == 5 else None
        else:  # distance, lateral position (left positive); bit 10 = target present
          self.pos = (be_bits(dat, 39, 13) * 0.025, (be_bits(dat, 27, 12) - 2000) * 0.01) if be_bits(dat, 10, 1) else None
    if t is None or self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None
    ret = structs.RadarData()
    if self.last_t is None or t - self.last_t > STALE_S:
      ret.errors.radarUnavailableTemporary = self.last_t is not None
    elif self.speed is not None and self.pos is not None:
      pt = structs.RadarData.RadarPoint()
      pt.trackId, pt.dRel, pt.yRel, pt.vRel = self.speed[0], self.pos[0], self.pos[1], self.speed[1]
      ret.points = [pt]
    return ret
