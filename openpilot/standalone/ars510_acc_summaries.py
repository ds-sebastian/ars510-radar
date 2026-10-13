"""Toyota / Continental ARS510 front radar (RAV4 2022+): research profile `acc_summaries` (v2, ACC-anchored).

Points published at 20 Hz:
- the radar's ACC target (0x235 / 0x237): the one car Toyota's ACC follows, as in the `acc` profile;
- while the ACC target is present, up to two more tracks from the target summaries (0x191-0x194). They hold the two
  nearest moving vehicles of the same internal function tracker that produces the ACC target: range (code - 160) / 16 m
  and lateral (code - 2048) * 0.015 m, left positive, with no speed. They add context to the radar's own selected
  target and never stand in for it. With no ACC target, radard would match the camera lead to whichever summary car fits
  best, including one in the next lane.
Identity: a summary thread is its pair code (0x191 / 0x193 byte 3 >> 2) in successive radar cycles (0x190 clock) without a
range jump > 3 m or lateral jump > 1 m. It is published as trackId 32 + code, apart from the ACC target IDs 0-31.
The ACC car appears once: a thread whose last or previous state is the ACC target's quantized state is not published
again. That state is summary range code = 160 + floor(0.4 * ACC distance code) or one below, lateral within 0.1 m. The
ACC frames of a cycle can arrive a cycle after its summaries, so the four latest ACC states are kept.
Speed: vRel is the least-squares slope of the thread's last 8 ranges on the radar clock (0.16-0.19 m/s RMS against the
ACC target's own vRel, about 0.2 s delay). A thread is published once 8 cycles exist.
"""
from collections import deque

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_BUS, ACC_SPEED_ADDR, ACC_POS_ADDR, CYCLE_ADDR = 1, 0x235, 0x237, 0x190
SUMMARIES = {0x192: 0x191, 0x194: 0x193}  # position frame -> identity frame
STALE_S = 0.5  # no ACC frame for this long: the radar is not sending
SLOPE_N, SUMMARY_ID = 8, 32


def be_bits(b: bytes, start: int, length: int) -> int:
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
    self.speed = self.pos = self.last_t = self.clock = self.cycle = None
    self.acc_codes = deque(maxlen=4)  # (distance code, lateral m) of the latest ACC states
    self.ident, self.threads, self.radar_t = {}, {}, 0.0

  def is_acc(self, th):
    return any(round(d * 16) - 2 * dc // 5 in (0, -1) and abs(y - ay) < 0.1 for d, y in th["states"] for dc, ay in self.acc_codes)

  def commit(self):  # end of a radar cycle: extend or start each summary thread
    threads = {}
    for code, d, y in self.cycle:
      th = self.threads.get(code)
      if th is None or abs(d - th["states"][-1][0]) > 3.0 or abs(y - th["states"][-1][1]) > 1.0:
        th = {"hist": deque(maxlen=SLOPE_N), "states": deque(maxlen=2)}
      th["hist"].append((self.radar_t, d))
      th["states"].append((d, y))
      threads[code] = th
    self.threads, self.cycle = threads, None

  def update(self, can_packets):
    self.frame += 1
    t = None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src != RADAR_BUS:
          continue
        if address == ACC_SPEED_ADDR and len(dat) == 8:  # target id, closing speed; status nibble 5 = target present
          self.last_t, self.speed = t, (be_bits(dat, 0, 5), (be_bits(dat, 29, 11) - 1024) * 0.125) if dat[1] & 0x0F == 5 else None
        elif address == ACC_POS_ADDR and len(dat) == 8:  # distance, lateral position (left positive); bit 10 = target present
          self.last_t, self.pos = t, (be_bits(dat, 39, 13) * 0.025, (be_bits(dat, 27, 12) - 2000) * 0.01) if be_bits(dat, 10, 1) else None
          if self.pos is None:
            self.acc_codes.clear()
          elif not self.acc_codes or self.acc_codes[-1] != (be_bits(dat, 39, 13), self.pos[1]):
            self.acc_codes.append((be_bits(dat, 39, 13), self.pos[1]))
        elif address == CYCLE_ADDR and len(dat) >= 6 and dat[0] != 0xFF and int.from_bytes(dat[2:6], "big") != self.clock:
          clock = int.from_bytes(dat[2:6], "big")  # radar cycle clock (us); a repeated clock is a repeated cycle
          self.radar_t += 0.0 if self.clock is None else ((clock - self.clock) % (1 << 32)) * 1e-6
          self.clock, self.cycle = clock, []
        elif address in SUMMARIES.values() and len(dat) == 8:
          self.ident[address] = dat
        elif address in SUMMARIES and len(dat) >= 4 and self.cycle is not None:
          ident = self.ident.get(SUMMARIES[address])
          if dat[0:4] != b"\x00\xff\x00\xff" and ident is not None and ident[0] >> 1 != 127:  # sentinel / empty slot
            self.cycle.append((ident[3] >> 2, (be_bits(dat[0:4], 16, 13) - 160) / 16, (be_bits(dat[0:4], 0, 13) - 2048) * 0.015))
          if address == 0x194:  # last frame of the cycle
            self.commit()
    if t is None or self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None
    ret = structs.RadarData()
    if self.last_t is None or t - self.last_t > STALE_S:
      ret.errors.radarUnavailableTemporary = self.last_t is not None
    elif self.speed is not None and self.pos is not None:
      pts = [point(self.speed[0], self.pos[0], self.pos[1], self.speed[1])]
      for code, th in sorted(self.threads.items()):
        if len(th["hist"]) == SLOPE_N and not self.is_acc(th):
          pts.append(point(SUMMARY_ID + code, th["states"][-1][0], th["states"][-1][1], slope(th["hist"])))
      ret.points = pts  # assigned as a list: capnp-backed forks (sunnypilot) take list assignment only
    return ret
