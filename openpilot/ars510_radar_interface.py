"""openpilot radar tracks from the Toyota / Continental ARS510 native object list.

Installed by `openpilot/install.py` as `opendbc/car/toyota/ars510_radar_interface.py`, together with the `ars510`
decoder package as `opendbc/car/toyota/ars510/`. The installer appends a marked block to the end of
`opendbc/car/toyota/interface.py` that calls `hook_car_interface(CarInterface)`; nothing else in the fork is edited,
so the same install works on openpilot and its forks (sunnypilot, StarPilot, FrogPilot-style trees):
  - detection: a RADAR_ACC Toyota whose radar FW is in ARS510_FW_VERSIONS, or with 0x80 and 0x85 on bus 1 at
    fingerprinting, gets radarUnavailable = False (stock leaves radar-ACC Toyotas radar-unavailable);
  - tracks: `CarInterface.RadarInterface` becomes a thin dispatcher that builds `Ars510RadarInterface` for such a car
    and the fork's own RadarInterface otherwise. No ToyotaFlags bit is added, so fork flag bits cannot collide.
Worth knowing (docs/07, docs/08):
  - vRel has occasional 1-10 s excursions (mostly false closings beyond 40 m); the "steady" profile halves their effect;
  - the radar drops new stationary objects once ego is above ~2-3 m/s, so a car that was already stopped when it came
    into view comes from vision;
  - radard has no lateral gate.

Why there is no CANParser: the object list is ONE 742-byte record sent as 106 ISO-TP-style frames on 0x80 every
~60 ms. CANParser keeps only the latest value per address (or a per-call list in vl_all), and a DBC cannot say which
part of the record a frame carries (the sequence nibble wraps every 16 frames). The frames are reassembled from the
raw `can_packets` card.py passes in, CRC-checked, and decoded in `ars510`. The DBCs are for cabana, not for parsing.

Output cadence: one RadarData per completed record (~16.7 Hz, inside radard's 8-24 Hz radarTracks window).
- After power-up the radar sends its first object record ~6 s after first CAN. Until the first valid record, this
  behaves like openpilot's radarless default: empty RadarData at 20 Hz, no error, vision-only leads. A warning is
  logged if no record has arrived NO_RECORD_WARN_S after start (e.g. the radar was silenced by the alpha-longitudinal
  radar disable).
- Once records have arrived, if none arrives for STALE_S, a radarUnavailableTemporary RadarData is sent at 20 Hz
  until records resume, instead of radard silently reusing the last tracks.
- A CRC-failed record is dropped. It is not flagged as a CAN error: the staleness check covers sustained loss.
"""
from dataclasses import replace

from opendbc.car import structs
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.toyota.ars510 import FUSED_CONFIG, OPENPILOT_CONFIG, Ars510NativeRadarInterface
from opendbc.car.toyota.ars510.constants import (ACC_TARGET_POS_ADDR, ACC_TARGET_VREL_ADDR, CAR_BUS, ID80_ADDR, RADAR_BUS, SUMMARY_ADDRS,
                                                 TOYOTA_KINEMATICS_ADDR, TOYOTA_SPEED_ADDR)

# Decoder profile (docs/08): "fused" (FUSED_CONFIG, default: one Kalman speed filter fusing the object list, the ACC
# target and the summaries by the radar's own uncertainty, docs/07) or "raw" (OPENPILOT_CONFIG: the unfiltered radar
# decode, research only). `install.py --profile` rewrites this one line in the installed copy.
PROFILES = {"fused": FUSED_CONFIG, "raw": OPENPILOT_CONFIG}
PROFILE = PROFILES["fused"]

# Radar firmware confirmed to be a Continental ARS510 that sends the native object list (0x80) on bus 1.
# 8821F0R01100 (RAV4 2022 platform) is the same part series but unconfirmed; it is detected by the bus-1 fallback when
# the radar is already running at fingerprinting.
ARS510_FW_VERSIONS = {
  b'\x018821F0R03100\x00\x00\x00\x00',
}

STALE_S = 0.5  # radard has no staleness check of its own on track content
NO_RECORD_WARN_S = 15.0
EMPTY_PERIOD = 5  # without records, report every 5th update (card calls update at 100 Hz -> 20 Hz)
# 0x24 (yaw rate) feeds yvRel, which forks with the legacy RadarPoint fields (sunnypilot) publish
WANTED = {(RADAR_BUS, ID80_ADDR), (CAR_BUS, TOYOTA_SPEED_ADDR), (CAR_BUS, TOYOTA_KINEMATICS_ADDR), (RADAR_BUS, ACC_TARGET_VREL_ADDR),
          (RADAR_BUS, ACC_TARGET_POS_ADDR)} | {(RADAR_BUS, a) for a in SUMMARY_ADDRS}


class Ars510RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args, **kwargs):  # forks add arguments (sunnypilot: CP_SP)
    super().__init__(CP, *args, **kwargs)
    self.ars = Ars510NativeRadarInterface(replace(PROFILE, include_metadata=False))
    self.start_s: float | None = None
    self.last_record_s: float | None = None
    self.warned = False

  def update(self, can_packets):
    self.frame += 1
    latest = None
    now_s = None
    for nanos, frames in can_packets:
      now_s = nanos * 1e-9
      # card.py passes plain (address, data, src) tuples; CanData is a NamedTuple in the same order
      for address, dat, src in frames:
        if (src, address) in WANTED:
          out = self.ars.update_frame(now_s, src, address, dat)
          if out is not None:
            latest = out
    if now_s is None:
      return None
    if self.start_s is None:
      self.start_s = now_s

    if latest is None:
      if self.frame % EMPTY_PERIOD != 0:
        return None
      if self.last_record_s is None:  # radar not started yet (or silenced): radarless behaviour, no error
        if not self.warned and now_s - self.start_s > NO_RECORD_WARN_S:
          carlog.warning("ARS510: no valid 0x80 object record on bus 1 yet; radar tracks unavailable")
          self.warned = True
        return structs.RadarData()
      if now_s - self.last_record_s > STALE_S:
        ret = structs.RadarData()
        ret.errors.radarUnavailableTemporary = True
        return ret
      return None

    self.last_record_s = latest["time_s"]
    ret = structs.RadarData()
    points = []
    # RadarPoint is trackId / dRel / yRel / vRel; forks that still carry the legacy aRel / yvRel / measured fields get
    # them too. Both profiles never publish a NaN vRel, which would poison radard's per-track Kalman filter.
    for p in latest["radarData"]["points"]:
      pt = structs.RadarData.RadarPoint()
      pt.trackId = p["trackId"]
      pt.dRel = p["dRel"]
      pt.yRel = p["yRel"]
      pt.vRel = p["vRel"]
      for legacy in LEGACY_FIELDS:
        setattr(pt, legacy, p[legacy])
      points.append(pt)
    ret.points = points
    return ret


def _legacy_fields() -> tuple[str, ...]:
  pt = structs.RadarData.RadarPoint()
  return tuple(f for f in ("aRel", "yvRel", "measured") if hasattr(pt, f))


LEGACY_FIELDS = _legacy_fields()


# ---- generic hook (called from the block install.py appends to opendbc/car/toyota/interface.py) ------------------
def _radar_acc(flags) -> bool:
  from opendbc.car.toyota.values import ToyotaFlags
  return bool(int(flags) & ToyotaFlags.RADAR_ACC)


def detect(ret, fingerprint, car_fw) -> bool:
  """ARS510 on a radar-ACC Toyota: known radar FW (works at a cold start) or its object list already on bus 1."""
  if not _radar_acc(ret.flags):
    return False
  fw = any(f.ecu == "fwdRadar" and f.fwVersion in ARS510_FW_VERSIONS for f in (car_fw or []))
  return fw or {0x80, 0x85} <= set((fingerprint or {}).get(1, {}).keys())


def is_ars510(CP) -> bool:
  """Stock marks every radar-ACC Toyota radar-unavailable; only the hook clears it, and only for an ARS510."""
  return _radar_acc(CP.flags) and not CP.radarUnavailable


def hook_car_interface(car_interface):
  """Wrap a fork's Toyota CarInterface in place: detection in _get_params, dispatch in RadarInterface."""
  if getattr(car_interface, "_ars510_hooked", False):
    return car_interface
  import inspect
  get_params = car_interface.__dict__["_get_params"].__func__
  sig = inspect.signature(get_params)

  def _get_params(*args, **kwargs):
    ret = get_params(*args, **kwargs)
    bound = sig.bind_partial(*args, **kwargs).arguments
    if detect(ret, bound.get("fingerprint"), bound.get("car_fw")):
      ret.radarUnavailable = False
    return ret

  fork_radar_interface = car_interface.RadarInterface

  class RadarInterface(fork_radar_interface):
    def __new__(cls, CP, *args, **kwargs):
      if is_ars510(CP):
        return Ars510RadarInterface(CP, *args, **kwargs)
      return fork_radar_interface(CP, *args, **kwargs)

  car_interface._get_params = staticmethod(_get_params)
  car_interface.RadarInterface = RadarInterface
  car_interface._ars510_hooked = True
  return car_interface
