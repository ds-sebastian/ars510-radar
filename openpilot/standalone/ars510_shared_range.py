"""Toyota / Continental ARS510 front radar: every object plus the radar's ACC target, one shared range model (research profile `shared_range`).

Protocol (decoding only): the object list (0x80, one 742-byte record over 106 frames, CRC32) gives up to 20 slots whose
age counts up while the radar keeps an object, which gives track IDs; the ACC target (0x235 / 0x237) is published as
one more track. Estimation: every track is the same two-state Kalman filter (range, range rate) with a random-
acceleration process and a traffic prior on its range rate (0 +- PRIOR_SIGMA). Its readings are weighted by their own
uncertainty: object-list range RANGE_FRAC x range (the slot speed stays out: its errors are slow and correlated, while a filter
assumes white noise, docs/07); ACC target range ACC_RANGE_SIGMA and closing speed ACC_SIGMA.
Research only: the object list's slow, correlated errors reach the planner (docs/17, "The ACC target alone").
"""
import zlib

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_BUS, OBJECTS_ADDR, ACC_SPEED_ADDR, ACC_POS_ADDR = 1, 0x80, 0x235, 0x237
RECORD_FRAMES, RECORD_LEN, SLOT_START, SLOT_LEN, SLOTS = 106, 742, 17, 36, 20
IDLE_SLOT = bytes.fromhex("FCE00000A0F07F00FFFDF71FFFA100F807000F0008000000000000000000000000000000")
STALE_S = 0.5  # protocol: ego speed or radar data older than this is stale
ACC_TRACK = 1 << 20  # protocol: ACC target ids live above the object ids

PRIOR_SIGMA = 2.0  # m/s: spread of a followed car's speed relative to ego (1.95 on every drive set)
LEAD_ACCEL = 1.5  # m/s^2: random relative acceleration between readings
RANGE_FRAC = 0.03  # object-list range noise per metre of range (0.020-0.034 from 4 to 96 m)
ACC_RANGE_SIGMA, ACC_SIGMA = 0.025, 0.13  # m, m/s: ACC target distance resolution, closing speed noise


def bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "little") >> start) & ((1 << length) - 1)


def be_bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.chunks, self.slots, self.next_tid = [], {}, 1
    self.acc_speed = self.acc_pos = self.last_t = None
    self.kf = {}  # track id -> (time, [range, range rate], 2x2 covariance)

  def update(self, can_packets):
    self.frame += 1
    t, record = None, None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src == RADAR_BUS and address == ACC_SPEED_ADDR and len(dat) == 8:
          self.acc_speed = (be_bits(dat, 0, 5), (be_bits(dat, 29, 11) - 1024) * 0.125) if dat[1] & 0x0F == 5 else None
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
    readings = [(tid, y, [(0, d, RANGE_FRAC * d)]) for tid, d, y in self.objects(t, record)]
    if self.acc_speed is not None and self.acc_pos is not None:
      readings.append((ACC_TRACK + self.acc_speed[0], self.acc_pos[1], [(0, self.acc_pos[0], ACC_RANGE_SIGMA), (1, self.acc_speed[1], ACC_SIGMA)]))
    pts = []
    for tid, y, z in readings:
      pt = structs.RadarData.RadarPoint()
      pt.trackId, pt.yRel = tid, y
      pt.dRel, pt.vRel = self.filter(tid, t, z)
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
    """(track id, dRel, yRel) for every valid slot; a slot whose age stops counting up is a new track."""
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
      out.append((prev[0], (bits(s, 32, 12) - 160) / 16, lat * 0.015))
    return out

  def filter(self, tid, t, readings):
    """Two-state Kalman filter (range, range rate): random acceleration, traffic prior, each reading by its own sigma."""
    t0, x, P = self.kf.get(tid, (t, [readings[0][1], 0.0], [[1e6, 0.0], [0.0, PRIOR_SIGMA ** 2]]))
    dt, q = t - t0, LEAD_ACCEL ** 2
    x = [x[0] + dt * x[1], x[1]]
    P = [[P[0][0] + dt * (P[0][1] + P[1][0]) + dt * dt * P[1][1] + q * dt ** 4 / 4, P[0][1] + dt * P[1][1] + q * dt ** 3 / 2],
         [P[1][0] + dt * P[1][1] + q * dt ** 3 / 2, P[1][1] + q * dt * dt]]
    for i, z, sigma in readings:  # a reading of state i: gain = P[:, i] / (P[i][i] + sigma^2)
      s = P[i][i] + sigma * sigma
      k = [P[0][i] / s, P[1][i] / s]
      x = [x[0] + k[0] * (z - x[i]), x[1] + k[1] * (z - x[i])]
      P = [[P[r][c] - k[r] * P[i][c] for c in range(2)] for r in range(2)]
    self.kf[tid] = (t, x, P)
    return x[0], x[1]
