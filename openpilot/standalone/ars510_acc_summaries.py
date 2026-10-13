"""Toyota / Continental ARS510 front radar (RAV4 2022+): research profile `acc_summaries`.

`acc` (the radar's ACC target, 0x235 / 0x237) plus up to two more cars from the same internal tracker: the target summaries
0x191-0x194 report the two nearest moving vehicles as (range, lateral) at 1/16 m and 0.015 m, with a pair-local code and no
speed. A summary that is the ACC car (range code 160 + floor(0.4 * ACC distance code) or one below, lateral within 0.1 m, on
its last two states) is not published twice. Every other summary keeps its code as trackId 32 + code while it moves less than
3 m / 1 m per radar cycle; vRel is the least-squares slope of its last 8 ranges on the radar clock (0x190), published once 8
exist. Summaries beyond 60 m are left out: radard cannot tell a neighbouring lane from the camera's far lead there (the
same far rule as `fused`). Evidence and replay numbers: docs/11 ("acc_summaries").
"""
from collections import deque

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

SLOPE_N, FAR_M, STALE_S, SUMMARY_ID = 8, 60.0, 0.5, 32
SUMMARY_PAIRS = {0x192: 0x191, 0x194: 0x193}  # position frame -> identity frame


def bits(b, start, length):
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


def slope(hist):
  tm, dm = sum(t for t, _ in hist) / len(hist), sum(d for _, d in hist) / len(hist)
  den = sum((t - tm) ** 2 for t, _ in hist)
  return sum((t - tm) * (d - dm) for t, d in hist) / den if den > 0 else None


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.speed = self.pos = self.last_t = self.summary_t = self.clock = None
    self.acc_codes = deque(maxlen=4)  # recent (distance code, lateral m) of the ACC target
    self.ident, self.threads, self.pending = {}, {}, []
    self.cycle, self.radar_t, self.fresh = 0, 0.0, False

  def commit(self):  # close a radar cycle: extend or restart each summary thread, drop the ones not sent
    for code, d, y in self.pending:
      th = self.threads.get(code)
      if th is None or th["cycle"] != self.cycle - 1 or abs(d - th["d"]) > 3.0 or abs(y - th["y"]) > 1.0:
        th = self.threads[code] = {"hist": deque(maxlen=SLOPE_N), "states": deque(maxlen=2)}
      th.update(cycle=self.cycle, d=d, y=y)
      th["states"].append((d, y))
      th["hist"].append((self.radar_t, d))
    self.threads = {c: th for c, th in self.threads.items() if th["cycle"] == self.cycle}
    self.pending = []

  def is_acc(self, states):
    return any(round(d * 16 + 160) - 160 - (2 * dc) // 5 in (0, -1) and abs(y - ay) < 0.1 for d, y in states for dc, ay in self.acc_codes)

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
          if self.pos is None:
            self.acc_codes.clear()
          elif not self.acc_codes or self.acc_codes[-1] != (bits(dat, 39, 13), self.pos[1]):
            self.acc_codes.append((bits(dat, 39, 13), self.pos[1]))
        elif address == 0x190 and len(dat) >= 6 and dat[0] != 0xFF and int.from_bytes(dat[2:6], "big") != self.clock:
          if self.pending:  # a repeated clock is a repeated cycle and is skipped
            self.commit()
          ts = int.from_bytes(dat[2:6], "big")
          self.radar_t += 0.0 if self.clock is None else ((ts - self.clock) % (1 << 32)) * 1e-6
          self.clock, self.cycle, self.pending, self.fresh = ts, self.cycle + 1, [], True
        elif address in (0x191, 0x193) and len(dat) == 8:
          self.ident[address] = dat
        elif address in SUMMARY_PAIRS and len(dat) >= 4 and self.fresh:
          ident = self.ident.get(SUMMARY_PAIRS[address])
          if dat[0:4] != b"\x00\xff\x00\xff" and ident is not None and ident[0] >> 1 != 127:
            d, y = ((int.from_bytes(dat[0:2], "big") & 0x1FFF) - 160) / 16, ((int.from_bytes(dat[2:4], "big") & 0x1FFF) - 2048) * 0.015
            self.pending.append((ident[3] >> 2, d, y))
          if address == 0x194:  # last frame of the cycle's group
            self.commit()
            self.fresh, self.summary_t = False, t
    if t is None or self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None
    ret = structs.RadarData()
    if self.last_t is None or t - self.last_t > STALE_S:
      ret.errors.radarUnavailableTemporary = self.last_t is not None
      return ret
    pts = [(self.speed[0], *self.pos, self.speed[1])] if self.speed is not None and self.pos is not None else []
    if self.summary_t is not None and t - self.summary_t <= STALE_S:
      for code, th in sorted(self.threads.items()):
        v = slope(th["hist"]) if len(th["hist"]) == SLOPE_N and th["d"] <= FAR_M and not self.is_acc(th["states"]) else None
        if v is not None:
          pts.append((SUMMARY_ID + code, th["d"], th["y"], v))
    points = []
    for pt_id, d, y, v in pts:
      pt = structs.RadarData.RadarPoint()
      pt.trackId, pt.dRel, pt.yRel, pt.vRel = pt_id, d, y, v
      points.append(pt)
    if points:
      ret.points = points  # assigned as a list: forks with capnp-backed structs (sunnypilot) take list assignment only
    return ret
