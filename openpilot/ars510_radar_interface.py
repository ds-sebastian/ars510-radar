"""openpilot radar tracks from the Toyota / Continental ARS510: the ACC target (`acc`, default) or the native object list (`fused`, `raw`).

Installed by `openpilot/install.py` as `opendbc/car/toyota/ars510_radar_interface.py`, together with the `ars510`
decoder package as `opendbc/car/toyota/ars510/`. The installer appends a marked block to the end of
`opendbc/car/toyota/interface.py` that calls `hook_car_interface(CarInterface)`; every other file of the fork stays as shipped,
so the same install works on openpilot and its forks (sunnypilot, StarPilot, CarrotPilot, FrogPilot-style trees):
  - detection: the radar-ACC platforms (ARS510_PLATFORMS: RAV4 2022 and 2023-25, C-HR, Yaris) whose radar frames
    reach bus 1 during fingerprinting get radarUnavailable = False (stock keeps radar-ACC Toyotas radar-unavailable);
  - tracks: `CarInterface.RadarInterface` becomes a thin dispatcher that builds `Ars510RadarInterface` for such a car
    and the fork's own RadarInterface otherwise. ToyotaFlags stays as shipped, so fork flag bits stay free.
Worth knowing (docs/07, docs/08, docs/12):
  - the object list's vRel has occasional 1-10 s excursions (mostly false closings beyond 40 m, docs/07): `fused` filters them with the ACC target's speed, and the default `acc` publishes the ACC target alone;
  - the radar deletes most new stationary objects at age 5, more often the faster ego drives (7 % kept above 10 m/s),
    so a car that was already stopped when it came into view comes mostly from vision;
  - radard weights lateral position only through the camera's uncertainty when it picks the lead; `fused` adds a
    yaw-rate path gate.

The object-list profiles (`fused`, `raw`) parse from card's raw `can_packets`: the object list is ONE 742-byte record sent as 106 ISO-TP-style frames on 0x80 every
~60 ms. CANParser keeps the latest value per address (or a per-call list in vl_all), and a DBC maps address and bits, while the
part of the record a frame carries follows from its sequence nibble (which wraps every 16 frames). The frames are reassembled from the
raw `can_packets` card.py passes in, CRC-checked, and decoded in `ars510`. The DBCs in `dbc/` are for cabana; the `acc`
profile parses its three 50 Hz ACC target messages with CANParser and `toyota_tss2_ars510.dbc` (installed as
`ars510_acc_target.dbc`, so opendbc's own copy of that DBC stays as shipped).

Output cadence: one RadarData per completed record (~16.6 Hz, inside radard's 8-24 Hz radarTracks window).
- After power-up the radar sends its first object record ~6 s after first CAN. Until the first valid record, this
  behaves like openpilot's radarless default: empty RadarData at 20 Hz, error-free status, vision-only leads. A warning is
  logged when the record count is still 0 at NO_RECORD_WARN_S after start (e.g. wiring, or firmware that also silences bus 1 on
  the alpha-longitudinal radar disable; on 8821F0R03100 bus 1 keeps running).
- Once records have arrived and STALE_S passes between two of them, a radarUnavailableTemporary RadarData is sent at 20 Hz
  until records resume, so radard sees that report in place of the last tracks.
- A CRC-failed record is dropped; the staleness check covers sustained loss.
- Every profile: while the radar's own fault flag (0x196 byte 1 bit 0) is set on two or more consecutive cycles, the
  only report is radarUnavailableTemporary with no points, at 20 Hz. The radar holds it
  through minutes in which it declares itself blocked (car-bus 0x411 dust), sometimes with no ACC target for a lead
  that the object list still tracks (docs/05).
"""
import importlib
from dataclasses import replace

from opendbc.car import structs
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.toyota.ars510 import BASE_CONFIG, FUSED_CONFIG, Ars510NativeRadarInterface
from opendbc.car.toyota.ars510.constants import (ACC_TARGET_POS_ADDR, ACC_TARGET_VREL_ADDR, CAR_BUS, ID80_ADDR, RADAR_BUS, RADAR_FAULT_ADDR,
                                                 SUMMARY_ADDRS, TOYOTA_KINEMATICS_ADDR, TOYOTA_SPEED_ADDR)
from opendbc.car.toyota.ars510.support import RadarFaultFlag

# Decoder profile (docs/08): "acc" (default: the radar's ACC target alone as one point, ars510_acc_target.py, docs/17),
# "fused" (FUSED_CONFIG: one Kalman speed filter fusing the object list and the ACC target by the radar's own
# uncertainty, plus a path gate, docs/12), "raw" (BASE_CONFIG: the unfiltered radar decode, research only) or
# "openpilot" (fused in one file, ars510_upstream.py); "acc_summaries" adds the radar's summary cars to acc (docs/11);
# "shared_speed" / "shared_range" are research files with one gate-free Kalman model
# over every object (docs/17). `install.py --profile` rewrites this one line.
STANDALONE = {"acc": "ars510_acc_target", "acc_summaries": "ars510_acc_summaries", "shared_speed": "ars510_shared_speed", "shared_range": "ars510_shared_range"}
PROFILES = {"fused": FUSED_CONFIG, "openpilot": None, "raw": BASE_CONFIG, **{k: k for k in STANDALONE}}
PROFILE = PROFILES["acc"]

# Radar-ACC platforms: every radar firmware they list (RAV4 8821F0R01100 / 8821F0R03100, C-HR 8821FF41xx00, Yaris
# 8821F0D0xx00) is the Continental ARS510 sending the same bus-1 messages (docs/01), so the car model selects the parser.
# The RAV4s carry the replay and road evidence; C-HR and Yaris are enabled for testing.
ARS510_PLATFORMS = {"TOYOTA_RAV4_TSS2_2022", "TOYOTA_RAV4_TSS2_2023", "TOYOTA_CHR_TSS2", "TOYOTA_YARIS"}
# The object-list profiles need the 0xB4 wheel speed, which the Yaris does not send: it runs `acc` whatever the profile.
ACC_ONLY_PLATFORMS = {"TOYOTA_YARIS"}

STALE_S = 0.5  # radard leaves track-content staleness to this interface
NO_RECORD_WARN_S = 15.0
EMPTY_PERIOD = 5  # during record gaps, report every 5th update (card calls update at 100 Hz -> 20 Hz)
# 0x24 (yaw rate) feeds yvRel, which forks with the legacy RadarPoint fields (sunnypilot) publish
WANTED = {(RADAR_BUS, ID80_ADDR), (CAR_BUS, TOYOTA_SPEED_ADDR), (CAR_BUS, TOYOTA_KINEMATICS_ADDR), (RADAR_BUS, ACC_TARGET_VREL_ADDR),
          (RADAR_BUS, ACC_TARGET_POS_ADDR)} | {(RADAR_BUS, a) for a in SUMMARY_ADDRS}


class Ars510RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args, **kwargs):  # forks add arguments (sunnypilot: CP_SP)
    super().__init__(CP, *args, **kwargs)
    self.standalone = None
    profile = "acc" if str(CP.carFingerprint) in ACC_ONLY_PLATFORMS else PROFILE
    if isinstance(profile, str):  # a standalone file: a complete RadarInterface of its own (frames, cadence, staleness)
      module = importlib.import_module(f"opendbc.car.toyota.{STANDALONE[profile]}")
      self.standalone = module.RadarInterface(CP, *args, **kwargs)
      self.standalone_fills_legacy = hasattr(module, "LEGACY")  # acc_summaries sets aRel / yvRel / measured itself
    else:
      self.ars = UpstreamCandidate() if profile is None else Ars510NativeRadarInterface(replace(profile, include_metadata=False))
    self.start_s: float | None = None
    self.last_record_s: float | None = None
    self.warned = False
    self.fault = RadarFaultFlag()
    self.calls = 0

  def update(self, can_packets):
    self.calls += 1
    for _, frames in can_packets:
      for address, dat, src in frames:
        if address == RADAR_FAULT_ADDR and src == RADAR_BUS:
          self.fault.update(dat)
    return self._with_fault(self._update(can_packets))

  def _with_fault(self, ret):
    if not self.fault.active:
      return ret
    if self.calls % EMPTY_PERIOD != 0:  # one report per 5 updates (20 Hz), so radard's 8-24 Hz radarTracks check holds
      return None
    ret = structs.RadarData()
    ret.errors.radarUnavailableTemporary = True
    return ret

  def _update(self, can_packets):
    if self.standalone is not None:
      ret = self.standalone.update(can_packets)
      if ret is not None and ret.points and LEGACY_FIELDS and not self.standalone_fills_legacy:  # as for the upstream version
        ret.points = [_point({"trackId": p.trackId, "dRel": p.dRel, "yRel": p.yRel, "vRel": p.vRel, **ACC_LEGACY}) for p in ret.points]
      return ret
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
      if self.last_record_s is None:  # radar still starting (or silenced): radarless behaviour, error-free status
        if not self.warned and now_s - self.start_s > NO_RECORD_WARN_S:
          carlog.warning("ARS510: waiting for the first valid 0x80 object record on bus 1; radar tracks unavailable until then")
          self.warned = True
        return structs.RadarData()
      if now_s - self.last_record_s > STALE_S:
        ret = structs.RadarData()
        ret.errors.radarUnavailableTemporary = True
        return ret
      return None

    self.last_record_s = latest["time_s"]
    ret = structs.RadarData()
    # Every profile withholds points with a NaN vRel, which would poison radard's per-track Kalman filter.
    ret.points = [_point(p) for p in latest["radarData"]["points"]]
    return ret


def _point(p: dict) -> structs.RadarData.RadarPoint:
  """RadarPoint is trackId / dRel / yRel / vRel; forks that still carry the legacy aRel / yvRel / measured fields get them too."""
  pt = structs.RadarData.RadarPoint()
  pt.trackId, pt.dRel, pt.yRel, pt.vRel = p["trackId"], p["dRel"], p["yRel"], p["vRel"]
  for legacy in LEGACY_FIELDS:
    setattr(pt, legacy, p[legacy])
  return pt


class UpstreamCandidate:
  """The single-file fused version behind the decoder's update_frame call (aRel / yvRel at their legacy defaults)."""
  def __init__(self):
    from opendbc.car.toyota.ars510_upstream import Ars510Radar
    self.radar = Ars510Radar()

  def update_frame(self, time_s, bus, address, dat):
    points = self.radar.update(time_s, bus, address, dat)
    if points is None:
      return None
    return {"time_s": self.radar.record_t, "radarData": {"points": [
      {"trackId": i, "dRel": d, "yRel": y, "vRel": v, "aRel": float("nan"), "yvRel": float("nan"), "measured": True}
      for i, d, y, v in points]}}


def _legacy_fields() -> tuple[str, ...]:
  pt = structs.RadarData.RadarPoint()
  return tuple(f for f in ("aRel", "yvRel", "measured") if hasattr(pt, f))


LEGACY_FIELDS = _legacy_fields()
ACC_LEGACY = {"aRel": float("nan"), "yvRel": float("nan"), "measured": True}


# ---- generic hook (called from the block install.py appends to opendbc/car/toyota/interface.py) ------------------
def _radar_acc(flags) -> bool:
  from opendbc.car.toyota.values import ToyotaFlags
  return bool(int(flags) & ToyotaFlags.RADAR_ACC)


# The radar's cycle frames on bus 1 (cycle header, target summaries, ACC target) start 0.14-1.0 s after the first CAN frame,
# inside openpilot's fingerprint window on all 74 recorded cold starts; the object list (0x80) starts only after ~6 s.
RADAR_BUS1_EARLY = {0x190, 0x191, 0x193, ACC_TARGET_VREL_ADDR, ACC_TARGET_POS_ADDR, 0x239}


def ars510_platform(CP) -> bool:
  return _radar_acc(CP.flags) and str(CP.carFingerprint) in ARS510_PLATFORMS


def detect(ret, fingerprint, car_fw) -> bool:
  """ARS510: a radar-ACC RAV4 2022 / 2023-25, C-HR or Yaris (the car model) whose radar frames reach bus 1. Without them
  (wiring, harness) the car gets a radarless setup with vision leads: a radar that is declared but never reports
  leaves radarState invalid, and openpilot then refuses to engage (commIssue). A fork that passes no fingerprint gets the
  car model alone."""
  if not ars510_platform(ret):
    return False
  return fingerprint is None or bool(RADAR_BUS1_EARLY & set(fingerprint.get(RADAR_BUS, {})))


def is_ars510(CP) -> bool:
  """An ARS510 platform the hook left with a radar. Radar-ACC cars outside ARS510_PLATFORMS keep the fork's interface,
  whatever radar opendbc declares for them."""
  return ars510_platform(CP) and not CP.radarUnavailable


def hook_car_interface(car_interface):
  """Wrap a fork's Toyota CarInterface in place: detection in _get_params, dispatch in RadarInterface."""
  if getattr(car_interface, "_ars510_hooked", False):
    return car_interface
  import inspect
  get_params = inspect.getattr_static(car_interface, "_get_params")  # the fork's class, or a base class it inherits from
  get_params = getattr(get_params, "__func__", get_params)
  sig = inspect.signature(get_params)

  def _get_params(*args, **kwargs):
    ret = get_params(*args, **kwargs)
    bound = sig.bind_partial(*args, **kwargs).arguments
    # Set both ways: stock keeps radar-ACC Toyotas radarless, and opendbc with its own ARS510 radar
    # (commaai/opendbc#3860) declares the radar without checking that its frames arrive.
    if ars510_platform(ret):
      ret.radarUnavailable = not detect(ret, bound.get("fingerprint"), bound.get("car_fw"))
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
