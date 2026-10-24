"""Toyota / Continental ARS510 front radar (RAV4 2022+): profile `acc_summaries`, `acc` plus the radar's target summaries.

The radar's ACC target (0x235 / 0x237) is published as in `acc`. The target summaries add up to two more moving cars from
the same tracker: range and lateral in 0x192 / 0x194, a pair code in 0x191 / 0x193 (trackId 64 + code). A summary within
1 m / 0.5 m of the ACC point is that car and is skipped. A car is published once its code has 8 ranges within 0.6 s.
Summaries beyond 40 m are left out: radard cannot tell a neighbouring lane from the camera's farther lead there (at 47-58 m
it took such a car as the lead before the radar's ACC picked the real one).
Speed (vRel): a summary range is the radar tracker's range rounded down to 1/16 m, so each car gets a constant-velocity
Kalman filter, timed by the radar's own cycle clock (0x190) and fed the middle of each 1/16 m step; it restarts with the car
(a new code or a 5 m range jump). Evidence and replay numbers: docs/11 ("acc_summaries").
Forks whose RadarPoint still has aRel / yvRel / measured get them filled: the ACC point's aRel is the target's own relative
acceleration (0x235 REL_ACCEL) and its yvRel its lateral speed (0x235 LAT_SPEED, d(LAT_DIST)/dt in the car's frame, left
positive, unwrapped by its check byte); a summary car's yvRel is the slope of its last 8 laterals and its aRel NaN (not sent
by the radar); measured is True (docs/05, docs/11).
While the radar's fault flag (0x196 byte 1 bit 0) is set on 2+ consecutive cycles, as it is while the radar declares itself
blocked, the report is radarUnavailableTemporary with no points (docs/05, docs/08).
"""
from collections import deque

from opendbc.car.structs import RadarData
from opendbc.car.interfaces import RadarInterfaceBase

# no ACC frame (or no new summary) for this long: not sending (s); summary trackIds: 64 + pair code; summary cars farther out
# are left out (m); a summary car is published once its code has 8 ranges within 0.6 s
STALE_S, SUMMARY_ID, FAR_M, SLOPE_N, SLOPE_SPAN_S = 0.5, 64, 40.0, 8, 0.6
# a summary this close to the ACC point is the ACC car itself (m, m); a range step this large between cycles is a glitch, a
# new car, or two cars sharing a pair code (m)
SAME_D_M, SAME_Y_M, JUMP_M = 1.0, 0.5, 5.0

# summary speed filter: range step (m), acceleration noise density (m^2/s^3), initial speed variance (m^2/s^2)
STEP_M, KF_Q, KF_P0_V = 1 / 16, 0.05, 25.0
KF_R = STEP_M ** 2 / 12  # variance of the range inside one step

# 0x235 LAT_SPEED and 0x237 LAT_DIST are the low 11 / 12 bits of one-bit-wider values: beyond +12.8 m/s / +20.95 m they wrap
# by 25.6 m/s / 40.96 m. The check byte (CRC-8 over the signals, linear: constant ^ one column per payload bit from byte 1
# bit 7; docs/05) then leaves the remainder 0x9C / 0x14 instead of 0. Per address: (constant, wrap remainder, columns).
COLS_235 = "68341a0d18dcafd96ce43c1e0f89ca6561be5fa1de6fb9d269ba5d8c46239fc1ee77b5d46a4e279dc06030180c06038fcfe975b45a2d984c"
COLS_237 = "0f89ca6599c261be5fa1de6fb9d269ba5d0a058c46239fc1ee77b5d46a35944a259c4e279dc06030180c06038f272c2eefef9898771d3a74"
CHECK = {0x235: (0xDF, 0x9C, bytes.fromhex(COLS_235)), 0x237: (0xFE, 0x14, bytes.fromhex(COLS_237))}

# optional point fields of forks that still carry them; the installed wrapper keeps the values this file sets
LEGACY = tuple(f for f in ("aRel", "yvRel", "measured") if hasattr(RadarData.RadarPoint(), f))


def bits(b, start, length):
  return (int.from_bytes(b, "big") >> start) & ((1 << length) - 1)


def wrapped(address, dat):
  constant, remainder, columns = CHECK[address]
  crc = constant ^ dat[0]
  for i, column in enumerate(columns):
    crc ^= column * bits(dat, 55 - i, 1)
  return crc == remainder


def decode_summary(ident, dat):  # 0x191 / 0x193 + 0x192 / 0x194: (pair code, range, lateral), or None when there is no car
  sentinel = dat[0:4] == b"\x00\xff\x00\xff"
  corrupt = (dat[0] | dat[2]) & 0xE0  # top 3 bits of each word are 0 unless corrupt (e.g. FF FF FF FF)
  no_car = ident[0] >> 1 == 127  # byte 0 >> 1: score, 127 = no car
  if sentinel or corrupt or no_car:
    return None
  return ident[3] >> 2, (bits(dat[0:2], 0, 13) - 160) / 16, (bits(dat[2:4], 0, 13) - 2048) * 0.015


def slope(hist, k):  # least-squares slope of column k (1 range, 2 lateral) over time
  tm, xm = sum(h[0] for h in hist) / len(hist), sum(h[k] for h in hist) / len(hist)
  return sum((h[0] - tm) * (h[k] - xm) for h in hist) / sum((h[0] - tm) ** 2 for h in hist)


def kf_step(s, tr, d):
  """One constant-velocity Kalman filter step for a summary car's range d (m) at radar time tr (s).
  s = (range, speed, P00, P01, P11, radar time), or None to start."""
  z = d + STEP_M / 2  # the tracker's range lies in [d, d + 1/16): measure the middle
  if s is None:  # first range: start at rest with a wide speed variance
    return (z, 0.0, KF_R, 0.0, KF_P0_V, tr)
  x, v, p00, p01, p11, t0 = s
  dt = tr - t0
  x += v * dt  # predict
  p00, p01, p11 = p00 + 2 * dt * p01 + dt * dt * p11 + KF_Q * dt ** 3 / 3, p01 + dt * p11 + KF_Q * dt * dt / 2, p11 + KF_Q * dt
  k0, k1, e = p00 / (p00 + KF_R), p01 / (p00 + KF_R), z - x  # update with the range
  return (x + k0 * e, v + k1 * e, (1 - k0) * p00, (1 - k0) * p01, p11 - k1 * p01, tr)


def point(track_id, d, y, v, a=float("nan"), yv=float("nan")):
  optional = {"aRel": a, "yvRel": yv, "measured": True}
  return RadarData.RadarPoint(trackId=track_id, dRel=d, yRel=y, vRel=v, **{k: optional[k] for k in LEGACY})


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args):  # forks pass more (sunnypilot: CP_SP)
    super().__init__(CP, *args)
    # clock: last 0x190 (CAN time, radar time in s, radar µs counter); fault: consecutive cycles with the fault flag set
    self.acc = self.pos = self.last_t = self.clock = None
    self.fault = 0
    # ident: latest 0x191 / 0x193 frame; summaries: per 0x192 / 0x194 (pair code, range, lateral, CAN time) or None;
    # hist / kf: per pair code, the last 8 (CAN time, range, lateral) and the speed filter state
    self.ident, self.summaries, self.hist, self.kf = {}, {}, {}, {}

  def update(self, can_packets):
    self.frame += 1
    t = None
    for nanos, frames in can_packets:
      t = nanos * 1e-9
      for address, dat, src in frames:
        if src != 1:
          continue
        if address == 0x235 and len(dat) == 8:  # id, closing speed, rel. accel, lateral speed; status nibble 5 = target present
          self.last_t, self.acc = t, (bits(dat, 0, 6), (bits(dat, 29, 11) - 1024) * 0.125, (dat[2] - 100) * 0.125,
                                      (bits(dat, 8, 11) - 1024) * 0.0125 + 25.6 * wrapped(0x235, dat)) if dat[1] & 0x0F == 5 else None
        elif address == 0x237 and len(dat) == 8:  # distance, lateral (left positive); bit 10 = target present
          self.last_t, self.pos = t, ((bits(dat, 39, 13) * 0.025, (bits(dat, 27, 12) - 2000) * 0.01 + 40.96 * wrapped(0x237, dat))
                                      if bits(dat, 10, 1) else None)
        elif address == 0x190 and len(dat) >= 6 and dat[0] != 0xFF:  # cycle header: radar µs counter in bytes 2-5
          us = int.from_bytes(dat[2:6], "big")
          radar_t = us * 1e-6 if self.clock is None else self.clock[1] + ((us - self.clock[2]) % (1 << 32)) * 1e-6  # counter wraps
          self.clock = (t, radar_t, us)
        elif address == 0x196 and len(dat) >= 2:  # fault flag: every cycle while blocked; one cycle at power-up
          self.fault = self.fault + 1 if dat[1] & 1 else 0
        elif address in (0x191, 0x193) and len(dat) == 8:
          self.ident[address] = dat
        elif address in (0x192, 0x194) and len(dat) >= 4 and address - 1 in self.ident:
          car = decode_summary(self.ident[address - 1], dat)
          self.summaries[address] = None
          if car is not None:
            code, d, y = car
            hist = self.hist.setdefault(code, deque(maxlen=SLOPE_N))
            if hist and abs(d - hist[-1][1]) > JUMP_M:  # no car moves 5 m in one 60 ms cycle: restart rather than slope through it
              hist.clear()
            if self.clock is not None:  # a cleared history restarts the filter too
              self.kf[code] = kf_step(self.kf.get(code) if hist else None, self.clock[1], d)
            hist.append((t, d, y))
            self.summaries[address] = (code, d, y, t)
    if t is None or self.frame % 5 != 0:  # card calls update at 100 Hz: report at 20 Hz
      return None
    ret = RadarData()
    if self.last_t is None or t - self.last_t > STALE_S or self.fault >= 2:
      ret.errors.radarUnavailableTemporary = self.last_t is not None or self.fault >= 2
      return ret
    points = []
    if self.acc is not None and self.pos is not None:
      points.append(point(self.acc[0], *self.pos, *self.acc[1:]))
    for code, d, y, ts in filter(None, self.summaries.values()):
      hist = self.hist[code]
      is_acc = self.pos is not None and abs(d - self.pos[0]) < SAME_D_M and abs(y - self.pos[1]) < SAME_Y_M
      settled = len(hist) == SLOPE_N and hist[-1][0] - hist[0][0] < SLOPE_SPAN_S and code in self.kf
      if t - ts < STALE_S and d <= FAR_M and not is_acc and settled:
        points.append(point(SUMMARY_ID + code, d, y, self.kf[code][1], yv=slope(hist, 2)))
    ret.points = points  # assigned as a list: forks with capnp-backed structs (sunnypilot) take list assignment only
    return ret
