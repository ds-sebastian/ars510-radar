"""Toyota / Continental ARS510 front radar (RAV4 2022+, fwdRadar 8821F0R03100): object list to RadarData.

The radar sends its object list on bus 1 as one 742-byte record split over 106 frames on 0x80 (consecutive-frame
numbers wrap every 16 frames, so a DBC cannot describe it and it is reassembled here). Each of its 20 slots holds one
object; the radar keeps an object in its slot while the slot's age counts up, which gives the track IDs.

The slot speed has slow, correlated errors at range (false closings of 1-10 s beyond ~40 m). The radar reports their
size in 240|7. One Kalman filter per track fuses the slot speed, weighted by that code, with the radar's own ACC target
(0x235 / 0x237) for the track it describes. radard then filters as for any radar. radard pairs the vision lead with
the nearest track by range and has no lateral gate, so tracks a lane away from the ACC target, or from the yaw-predicted
path at range, are not published.
Single-file candidate for upstream; ars510-radar docs/12 has the evidence for every constant and every omitted part.
"""
import zlib
from math import isfinite, nan, pi

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase

RADAR_BUS, CAR_BUS = 1, 0
SPEED_ADDR, YAW_ADDR, OBJECTS_ADDR, ACC_SPEED_ADDR, ACC_POS_ADDR = 0xB4, 0x24, 0x80, 0x235, 0x237
RECORD_FRAMES, RECORD_LEN, SLOT_START, SLOT_LEN, SLOTS = 106, 742, 17, 36, 20
IDLE_SLOT = bytes.fromhex("FCE00000A0F07F00FFFDF71FFFA100F807000F0008000000000000000000000000000000")

VGROUND_SCALE = 0.149 / 0.15  # slot over-ground speed aligned to 0xB4 ego speed
EGO_MAX_AGE_S = 0.5
PUBLISH_AGE = 60  # ~3.6 s: young tracks have unconverged range and speed
RANGE_GAIN = 0.1  # velocity-aided range: halves the far-range walk
# Kalman speed filter (one state: the lead's over-ground speed)
SIGMA_PER_CODE = 0.045  # m/s per 240|7 count, against the radar's ACC target
YOUNG_SCALE, YOUNG_AGE = 1.8, 100  # young tracks err more than 240|7 says
ACC_SIGMA = 0.5  # m/s, the radar's ACC target speed
LEAD_ACCEL = 1.5  # m/s^2, process noise
GATE_SIGMA = 3.0  # innovations beyond 3 sigma count as 3 sigma
PUBLISH_STD = 0.75  # m/s: a new track is published once its speed is this certain
YOUNG_MATCH, YOUNG_MATCH_MPS = 0.4, 5.0  # young tracks can read 15-20 m short: wider ACC match if the speed agrees
LANE_OFFSET = 2.5  # m: lateral distance from the ACC target / the yaw-predicted path that marks another lane
PATH_RANGE = 60.0  # m: beyond this, tracks off the yaw-predicted path are not published


def bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "little") >> start) & ((1 << length) - 1)


def be_bits(b: bytes, start: int, length: int) -> int:
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


class Ars510Radar:
  """Raw CAN frames in, points (trackId, dRel, yRel, vRel) out once per 0x80 record."""
  def __init__(self):
    self.chunks, self.record_t, self.last_frame_t = [], 0.0, None
    self.v_ego = self.yaw = None  # (time, m/s), (time, rad/s left positive)
    self.slots = {}  # slot -> (radar track id, age, time)
    self.next_tid = 1
    self.acc_speed = self.acc_pos = self.acc_assoc = self.acc_tid = None
    self.kf = {}  # tid -> (time, speed, variance)
    self.rng = {}  # tid -> (time, dRel, vRel)
    self.published = set()

  def update(self, t: float, bus: int, addr: int, dat: bytes):
    if bus == CAR_BUS and addr == SPEED_ADDR and len(dat) >= 7:
      self.v_ego = (t, int.from_bytes(dat[5:7], "big") * 0.01 / 3.6)
    elif bus == CAR_BUS and addr == YAW_ADDR and len(dat) >= 2:
      self.yaw = (t, (((dat[0] & 0x03) << 8 | dat[1]) * 0.244 - 125.0) * pi / 180.0)
    elif bus == RADAR_BUS and addr in (ACC_SPEED_ADDR, ACC_POS_ADDR):
      if len(dat) != 8 or (not dat[1] & 4 if addr == ACC_SPEED_ADDR else dat[2:] == bytes.fromhex("003E80000000")):
        self.acc_speed = self.acc_pos = None  # no target
      elif addr == ACC_SPEED_ADDR:
        self.acc_speed = (t, (be_bits(dat, 29, 11) - 1024) * 0.125)
      else:
        self.acc_pos = (t, be_bits(dat, 39, 13) * 0.025, (be_bits(dat, 27, 12) - 2000) * 0.01)
    elif bus == RADAR_BUS and addr == OBJECTS_ADDR:
      record = self.reassemble(t, dat)
      if record is not None and int.from_bytes(record[737:741], "little") == zlib.crc32(record[1:737]):
        return self.points(self.record_t, record)
    return None

  def reassemble(self, t, dat):
    """The 106 frames of one record joined (bytes 1-7 of each); restarts on a first frame (0x12 0xE4)."""
    if len(dat) != 8 or (self.chunks and t < self.last_frame_t):
      self.chunks = []
    if len(dat) != 8:
      return None
    if dat[0] == 0x12 and dat[1] == 0xE4:
      self.chunks, self.record_t = [bytes(dat[1:8])], t
    elif self.chunks:
      self.chunks.append(bytes(dat[1:8]))
    else:
      return None
    self.last_frame_t = t
    if len(self.chunks) != RECORD_FRAMES:
      return None
    record, self.chunks = b"".join(self.chunks), []
    return record if len(record) == RECORD_LEN else None

  def track_id(self, t, slot, age):
    prev = self.slots.get(slot)
    if prev is not None and t == prev[2]:
      return prev[0]
    if prev is None or t - prev[2] > 0.3 or not (age > prev[1] or age == prev[1] == 126):
      prev = (self.next_tid, age, t)
      self.next_tid += 1
    self.slots[slot] = (prev[0], age, t)
    return prev[0]

  def points(self, t, record):
    v_ego = self.v_ego[1] if self.v_ego is not None and abs(t - self.v_ego[0]) <= EGO_MAX_AGE_S else None
    objs = []
    for slot in range(SLOTS):
      s = record[SLOT_START + SLOT_LEN * slot:SLOT_START + SLOT_LEN * (slot + 1)]
      if s == IDLE_SLOT:
        continue
      age, lat = bits(s, 24, 7), bits(s, 44, 12) - 2048
      init_template = age == 1 and bits(s, 56, 7) == 0 and bits(s, 216, 6) == 0
      objs.append(dict(tid=self.track_id(t, slot, age), age=age, d=(bits(s, 32, 12) - 160) / 16, y=lat * 0.015,
                       vg=(bits(s, 64, 10) - 510.5) * 0.15 * VGROUND_SCALE, unc=bits(s, 240, 7),
                       valid=age >= 1 and not init_template and abs(lat) < 2000))
    tracks = {o["tid"]: o for o in objs if o["valid"]}
    acc_tid = self.acc_match(t, tracks, v_ego)
    if acc_tid is not None and acc_tid != self.acc_tid and acc_tid not in self.published:
      self.rng.pop(acc_tid, None)  # a new ACC track starts its range at the ACC distance
    self.acc_tid = acc_tid
    yaw = self.yaw[1] if self.yaw is not None and abs(t - self.yaw[0]) <= EGO_MAX_AGE_S else None
    acc_now = self.acc_pos if self.acc_pos is not None and abs(t - self.acc_pos[0]) <= 0.1 else None
    out = []
    for o in objs:
      if not o["valid"]:
        continue
      tid, vrel, std = o["tid"], nan, 0.0
      if v_ego is not None:
        readings = [(self.acc_speed[1] + v_ego, ACC_SIGMA)] if tid == acc_tid else []
        speed, std = self.speed_filter(tid, t, o, readings)
        vrel = speed - v_ego
      d_rel = self.fused_range(tid, t, self.acc_pos[1] if tid == acc_tid else o["d"], vrel)  # ACC distance for its track
      if o["age"] < PUBLISH_AGE or (tid not in self.published and std > PUBLISH_STD) or not isfinite(vrel):
        continue  # no point without a fresh ego speed: one NaN would poison radard's filter
      if tid != acc_tid and acc_now is not None and abs(d_rel - acc_now[1]) < max(5.0, 0.1 * acc_now[1]) \
          and abs(o["y"] - acc_now[2]) > LANE_OFFSET:
        continue  # a car in the next lane at the ACC target's range
      if tid != acc_tid and d_rel > PATH_RANGE and yaw is not None and abs(o["y"] - yaw / max(v_ego, 5.0) * d_rel * d_rel / 2) > LANE_OFFSET:
        continue  # a car a lane over on a curve
      self.published.add(tid)
      out.append((tid, d_rel, o["y"], vrel))
    self.prune(t)
    return out

  def speed_filter(self, tid, t, o, readings):
    """One-state Kalman filter on the over-ground speed; every reading weighted by its own sigma."""
    sig = SIGMA_PER_CODE * max(o["unc"], 1)
    if o["age"] < YOUNG_AGE:
      sig *= 1.0 + (YOUNG_SCALE - 1.0) * min(max((YOUNG_AGE - o["age"]) / (YOUNG_AGE - PUBLISH_AGE), 0.0), 1.0)
    prev = self.kf.get(tid)
    if prev is None or not 0.0 < t - prev[0] <= 0.5:
      self.kf[tid] = (t, o["vg"], sig * sig)
      return o["vg"], sig
    _, v, p = prev
    p += (LEAD_ACCEL * (t - prev[0])) ** 2
    for z, r in [(o["vg"], sig)] + readings:
      s = p + r * r
      innov = max(min(z - v, GATE_SIGMA * s ** 0.5), -GATE_SIGMA * s ** 0.5)
      v, p = v + p / s * innov, p * (1.0 - p / s)
    self.kf[tid] = (t, v, p)
    return v, p ** 0.5

  def fused_range(self, tid, t, d, vrel):
    prev = self.rng.get(tid)
    if prev is not None and isfinite(vrel) and isfinite(prev[2]) and 0.0 < t - prev[0] <= 0.5:
      pred = prev[1] + 0.5 * (prev[2] + vrel) * (t - prev[0])
      d = pred + RANGE_GAIN * (d - pred)
    self.rng[tid] = (t, d, vrel)
    return d

  def acc_match(self, t, tracks, v_ego):
    """The track the radar's ACC target describes: matched by position, kept while both persist."""
    if self.acc_speed is None or self.acc_pos is None or max(abs(t - self.acc_speed[0]), abs(t - self.acc_pos[0])) > 0.1:
      self.acc_assoc = None
      return None
    _, ax, ay = self.acc_pos
    rs = max(12.0, 0.25 * ax)  # the object list reads far cars short of the ACC distance: the range scale grows with range
    young = max(rs, YOUNG_MATCH * ax)
    scale = {tid: young if o["age"] < YOUNG_AGE and v_ego is not None and abs(o["vg"] - v_ego - self.acc_speed[1]) < YOUNG_MATCH_MPS
             else rs for tid, o in tracks.items()}
    costs = sorted((abs(o["d"] - ax) / scale[tid] + abs(o["y"] - ay) / 0.5, tid, o["age"]) for tid, o in tracks.items())
    if self.acc_assoc is not None:
      tid0, ax0, ay0 = self.acc_assoc
      own = next((c for c, tid, _ in costs if tid == tid0), None)
      if own is not None and own < 4.0 and abs(ax - ax0) <= 8.0 and abs(ay - ay0) <= 1.0:
        self.acc_assoc = (tid0, ax, ay)
        return tid0
      self.acc_assoc = None
    if not costs or costs[0][0] >= 1.0 or costs[0][2] < 20 or (len(costs) > 1 and costs[1][0] - costs[0][0] <= 1.0):
      return None
    self.acc_assoc = (costs[0][1], ax, ay)
    return costs[0][1]

  def prune(self, t):
    for store in (self.kf, self.rng):
      if len(store) > 400:
        for k in [k for k, v in store.items() if v[0] < t - 5.0]:
          store.pop(k)
    if len(self.published) > 400:
      # Invalid geometry may leave a live allocation without a recent speed-filter entry.
      self.published &= set(self.kf) | {state[0] for state in self.slots.values()}


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    self.radar = Ars510Radar()
    self.last_record_t = None

  def update(self, can_packets):
    self.frame += 1
    points, t = None, None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        out = self.radar.update(t, src, address, dat)
        if out is not None:
          points, self.last_record_t = out, t
    if points is None:  # between scans: report only at 20 Hz, and only before the first scan or once the radar is stale
      if t is None or self.frame % 5 != 0 or (self.last_record_t is not None and t - self.last_record_t <= 0.5):
        return None
      ret = structs.RadarData()
      ret.errors.radarUnavailableTemporary = self.last_record_t is not None
      return ret
    ret = structs.RadarData()
    for track_id, d_rel, y_rel, v_rel in points:
      pt = structs.RadarData.RadarPoint()
      pt.trackId, pt.dRel, pt.yRel, pt.vRel = track_id, d_rel, y_rel, v_rel
      ret.points.append(pt)
    return ret
