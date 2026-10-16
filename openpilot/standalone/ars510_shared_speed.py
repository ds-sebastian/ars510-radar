"""Toyota / Continental ARS510 front radar: every object plus the radar's ACC target, one shared speed model (research profile `shared_speed`).

Protocol (decoding only): the object list (0x80, one 742-byte record over 106 frames, CRC32) gives up to 20 slots whose
age counts up while the radar keeps an object, which gives track IDs; the ACC target (0x235 / 0x237) is published as
one more track. Estimation: every track's over-ground speed is one Kalman state with the same model for all of them:
a prior from traffic (relative speed 0 +- PRIOR_SIGMA), a random-acceleration process, and each reading weighted by
its own uncertainty (object list: SIGMA_PER_CODE x its 240|7 code; ACC target: ACC_SIGMA).
Research only: the object list's slow, correlated errors reach the planner (docs/17, "The ACC target alone").
"""
import zlib

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_BUS, CAR_BUS, SPEED_ADDR, OBJECTS_ADDR, ACC_SPEED_ADDR, ACC_POS_ADDR = 1, 0, 0xB4, 0x80, 0x235, 0x237
RECORD_FRAMES, RECORD_LEN, SLOT_START, SLOT_LEN, SLOTS = 106, 742, 17, 36, 20
IDLE_SLOT = bytes.fromhex("FCE00000A0F07F00FFFDF71FFFA100F807000F0008000000000000000000000000000000")
STALE_S = 0.5  # protocol: ego speed or radar data older than this is stale
ACC_TRACK = 1 << 20  # protocol: ACC target ids live above the object ids

PRIOR_SIGMA = 2.0  # m/s: spread of a followed car's speed relative to ego (1.95 on every drive set)
LEAD_ACCEL = 1.5  # m/s^2: random acceleration of a car between readings
SIGMA_PER_CODE = 0.045  # m/s per 240|7 count: object-list speed error (fit against the ACC target)
ACC_SIGMA = 0.13  # m/s: ACC target speed noise


def bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "little") >> start) & ((1 << length) - 1)


def be_bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.chunks, self.slots, self.next_tid = [], {}, 1
    self.v_ego = self.acc_speed = self.acc_pos = self.last_t = None
    self.kf = {}  # track id -> (time, ground speed, variance)

  def update(self, can_packets):
    self.frame += 1
    t, record = None, None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src == CAR_BUS and address == SPEED_ADDR and len(dat) >= 7:
          self.v_ego = (t, int.from_bytes(dat[5:7], "big") * 0.01 / 3.6 / 0.9865)  # 0xB4 reads 1.35 % below carState.vEgo
        elif src == RADAR_BUS and address == ACC_SPEED_ADDR and len(dat) == 8:
          self.acc_speed = (be_bits(dat, 0, 6), (be_bits(dat, 29, 11) - 1024) * 0.125) if dat[1] & 0x0F == 5 else None
        elif src == RADAR_BUS and address == ACC_POS_ADDR and len(dat) == 8:
          self.acc_pos = (be_bits(dat, 39, 13) * 0.025, (be_bits(dat, 27, 12) - 2000) * 0.01) if be_bits(dat, 10, 1) else None
        elif src == RADAR_BUS and address == OBJECTS_ADDR and len(dat) == 8:
          record = self.reassemble(dat) or record
    if record is None:  # protocol: one report per radar cycle; between records, report stale data at 20 Hz
      if t is None or self.frame % 5 != 0 or (self.last_t is not None and t - self.last_t <= STALE_S):
        return None
      ret = structs.RadarData()
      ret.errors.radarUnavailableTemporary = self.last_t is not None
      return ret
    self.last_t, ret = t, structs.RadarData()
    if self.v_ego is None or t - self.v_ego[0] > STALE_S:
      return ret  # protocol: a stale ego speed yields an empty point list
    readings = self.objects(t, record)
    if self.acc_speed is not None and self.acc_pos is not None:
      readings.append((ACC_TRACK + self.acc_speed[0], self.acc_pos[0], self.acc_pos[1], self.acc_speed[1] + self.v_ego[1], ACC_SIGMA))
    pts = []
    for tid, d, y, vg, sigma in readings:
      pt = structs.RadarData.RadarPoint()
      pt.trackId, pt.dRel, pt.yRel, pt.vRel = tid, d, y, self.filter(tid, t, vg, sigma) - self.v_ego[1]
      pts.append(pt)
    ret.points = pts  # assigned as a list: forks with capnp-backed structs (sunnypilot) take list assignment only
    self.kf = {k: v for k, v in self.kf.items() if t - v[0] <= STALE_S}
    return ret

  def reassemble(self, dat):
    """The 106 frames of one record joined (bytes 1-7 of each); restarts on a first frame (0x12 0xE4); CRC32 checked."""
    if dat[0] == 0x12 and dat[1] == 0xE4:
      self.chunks = []
    elif not self.chunks:
      return None
    self.chunks.append(bytes(dat[1:8]))
    if len(self.chunks) < RECORD_FRAMES:
      return None
    record, self.chunks = b"".join(self.chunks), []
    return record if int.from_bytes(record[737:741], "little") == zlib.crc32(record[1:737]) else None

  def objects(self, t, record):
    """(track id, dRel, yRel, ground speed, its sigma) for every valid slot; a slot whose age stops counting up is a new track."""
    out = []
    for slot in range(SLOTS):
      s = record[SLOT_START + SLOT_LEN * slot:SLOT_START + SLOT_LEN * (slot + 1)]
      age, lat = bits(s, 24, 7), bits(s, 44, 12) - 2048
      if s == IDLE_SLOT or age < 1 or abs(lat) >= 2000 or (age == 1 and bits(s, 56, 7) == 0 and bits(s, 216, 6) == 0):
        continue  # protocol: idle slot, invalid lateral code or the radar's initialisation template
      prev = self.slots.get(slot)
      if prev is None or t - prev[2] > STALE_S or not (age > prev[1] or age == prev[1] == 126):
        prev, self.next_tid = (self.next_tid, age, t), self.next_tid + 1
      self.slots[slot] = (prev[0], age, t)
      out.append((prev[0], (bits(s, 32, 12) - 160) / 16, lat * 0.015, (bits(s, 64, 10) - 510.5) * 0.15,
                  SIGMA_PER_CODE * max(bits(s, 240, 7), 1)))
    return out

  def filter(self, tid, t, z, sigma):
    """One Kalman state per track (over-ground speed): traffic prior, random acceleration, inverse-variance update."""
    _, v, p = self.kf.get(tid, (t, self.v_ego[1], PRIOR_SIGMA ** 2))
    p += (LEAD_ACCEL * (t - self.kf.get(tid, (t,))[0])) ** 2
    k = p / (p + sigma * sigma)
    self.kf[tid] = (t, v + k * (z - v), p * (1.0 - k))
    return self.kf[tid][1]
