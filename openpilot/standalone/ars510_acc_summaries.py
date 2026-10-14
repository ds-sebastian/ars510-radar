"""Toyota / Continental ARS510 front radar (RAV4 2022+): profile `acc_summaries`, `acc` plus the radar's target summaries.

The radar's ACC target (0x235 / 0x237) is published as in `acc`. The target summaries add up to two more moving cars from
the same tracker: range and lateral in 0x192 / 0x194, a pair code in 0x191 / 0x193 (trackId 32 + code). A summary within
1 m / 0.5 m of the ACC point is that car and is skipped. vRel is the least-squares slope of the code's last 8 ranges
over CAN time (the 8 must span less than 0.6 s). Summaries beyond 60 m are left out: radard cannot tell a neighbouring
lane from the camera's far lead there. Evidence and replay numbers: docs/11 ("acc_summaries").
"""
from collections import deque

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

STALE_S, FAR_M, SLOPE_N, SLOPE_SPAN_S, SUMMARY_ID = 0.5, 60.0, 8, 0.6, 32  # summary trackIds: 32 + pair code
JUMP_M = 5.0  # a range step this large between cycles is a glitch (2 in about 756 k summary frames) or a new car


def bits(b, start, length):
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


def slope(hist):
  tm, dm = sum(t for t, _ in hist) / len(hist), sum(d for _, d in hist) / len(hist)
  return sum((t - tm) * (d - dm) for t, d in hist) / sum((t - tm) ** 2 for t, _ in hist)


def point(track_id, d, y, v):
  pt = structs.RadarData.RadarPoint()
  pt.trackId, pt.dRel, pt.yRel, pt.vRel = track_id, d, y, v
  return pt


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.speed = self.pos = self.last_t = None
    self.ident, self.summaries, self.ranges = {}, {}, {}

  def update(self, can_packets):
    self.frame += 1
    t = None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src != 1:
          continue
        if address == 0x235 and len(dat) == 8:  # target id, closing speed; status nibble 5 = target present
          self.last_t, self.speed = t, (bits(dat, 0, 5), (bits(dat, 29, 11) - 1024) * 0.125) if dat[1] & 0x0F == 5 else None
        elif address == 0x237 and len(dat) == 8:  # distance, lateral (left positive); bit 10 = target present
          self.last_t, self.pos = t, (bits(dat, 39, 13) * 0.025, (bits(dat, 27, 12) - 2000) * 0.01) if bits(dat, 10, 1) else None
        elif address in (0x191, 0x193) and len(dat) == 8:  # byte 0 >> 1: score (127 = no car), byte 3 >> 2: pair code
          self.ident[address] = dat
        elif address in (0x192, 0x194) and len(dat) >= 4 and address - 1 in self.ident:  # range, lateral (left positive)
          ident, self.summaries[address] = self.ident[address - 1], None
          if dat[0:4] not in (b"\x00\xff\x00\xff", b"\xff\xff\xff\xff") and ident[0] >> 1 != 127:  # FF.. = one-cycle glitch
            code, d = ident[3] >> 2, ((int.from_bytes(dat[0:2], "big") & 0x1FFF) - 160) / 16
            hist = self.ranges.setdefault(code, deque(maxlen=SLOPE_N))
            if hist and abs(d - hist[-1][1]) > JUMP_M:  # no car moves 5 m in one 60 ms cycle: restart rather than slope through it
              hist.clear()
            hist.append((t, d))
            self.summaries[address] = (code, d, ((int.from_bytes(dat[2:4], "big") & 0x1FFF) - 2048) * 0.015, t)
    if t is None or self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None
    ret = structs.RadarData()
    if self.last_t is None or t - self.last_t > STALE_S:
      ret.errors.radarUnavailableTemporary = self.last_t is not None
      return ret
    points = [point(self.speed[0], *self.pos, self.speed[1])] if self.speed is not None and self.pos is not None else []
    for code, d, y, ts in filter(None, self.summaries.values()):
      hist = self.ranges[code]
      is_acc = self.pos is not None and abs(d - self.pos[0]) < 1.0 and abs(y - self.pos[1]) < 0.5
      if t - ts < STALE_S and d <= FAR_M and not is_acc and len(hist) == SLOPE_N and hist[-1][0] - hist[0][0] < SLOPE_SPAN_S:
        points.append(point(SUMMARY_ID + code, d, y, slope(hist)))
    if points:
      ret.points = points  # assigned as a list: forks with capnp-backed structs (sunnypilot) take list assignment only
    return ret
