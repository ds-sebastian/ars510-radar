"""openpilot radar tracks from the Toyota / Continental ARS510: the radar's ACC target (`acc`, default), optionally with
the two target-summary cars (`acc_summaries`).

Installed by `openpilot/install.py` as `opendbc/car/toyota/ars510_radar_interface.py`, together with the `ars510`
package as `opendbc/car/toyota/ars510/` (its constants and support code: the PCS alarm, the radar's fault flag). The
installer appends a marked block to the end of `opendbc/car/toyota/interface.py` that calls
`hook_car_interface(CarInterface)`; every other file of the fork stays as shipped, so the same install works on openpilot
and its forks (sunnypilot, StarPilot, CarrotPilot, FrogPilot-style trees):
  - detection: the radar-ACC platforms (ARS510_PLATFORMS: RAV4 2022 and 2023-25, C-HR, Yaris) whose radar frames
    reach bus 1 during fingerprinting get radarUnavailable = False (stock keeps radar-ACC Toyotas radar-unavailable);
  - tracks: `CarInterface.RadarInterface` becomes a thin dispatcher that builds `Ars510RadarInterface` for such a car
    and the fork's own RadarInterface otherwise. ToyotaFlags stays as shipped, so fork flag bits stay free.
  - PCS alarm: the radar's alarm bit on bus 1 (0x100) sets carState.stockFcw, as 0x411 FCW does with the radar enabled.
    Upstream this is part of commaai/opendbc#3860, in Toyota's carstate (upstream/opendbc_ars510.patch); the hook does the same after the
    fork's update, since the installer leaves the fork's carstate as shipped.
Both profiles publish only the radar's own tracker outputs (ACC target, target summaries). The raw object list (0x80)
is not published: its speeds have 1-10 s excursions, mostly false closings beyond 40 m (docs/07), that no filter has
yet removed reliably (docs/12).

Every profile: while the radar's own fault flag (0x196 byte 1 bit 0) is set on two or more consecutive cycles, the only
report is radarUnavailableTemporary with no points, at 20 Hz. The radar holds it through minutes in which it declares
itself blocked (car-bus 0x411 dust), sometimes with no ACC target for a lead that the object list still tracks (docs/05).
"""
import importlib

from opendbc.car import structs
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.toyota.ars510.constants import ACC_TARGET_POS_ADDR, ACC_TARGET_VREL_ADDR, PCS_STATE_ADDR, RADAR_BUS, RADAR_FAULT_ADDR
from opendbc.car.toyota.ars510.support import RadarFaultFlag, pcs_alarm

STANDALONE = {"acc": "ars510_acc_target", "acc_summaries": "ars510_acc_summaries"}
PROFILES = {k: k for k in STANDALONE}
PROFILE = PROFILES["acc"]

ARS510_PLATFORMS = {"TOYOTA_RAV4_TSS2_2022", "TOYOTA_RAV4_TSS2_2023", "TOYOTA_CHR_TSS2", "TOYOTA_YARIS"}
ACC_ONLY_PLATFORMS = {"TOYOTA_YARIS"}

EMPTY_PERIOD = 5  # while the fault flag holds, report every 5th update (card calls update at 100 Hz -> 20 Hz)


class Ars510RadarInterface(RadarInterfaceBase):
  def __init__(self, CP, *args, **kwargs):  # forks add arguments (sunnypilot: CP_SP)
    super().__init__(CP, *args, **kwargs)
    profile = "acc" if str(CP.carFingerprint) in ACC_ONLY_PLATFORMS else PROFILE
    module = importlib.import_module(f"opendbc.car.toyota.{STANDALONE[profile]}")
    self.standalone = module.RadarInterface(CP, *args, **kwargs)  # a complete RadarInterface (frames, cadence, staleness)
    self.standalone_fills_legacy = hasattr(module, "LEGACY")  # acc_summaries sets aRel / yvRel / measured itself
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
    ret = self.standalone.update(can_packets)
    if ret is not None and ret.points and LEGACY_FIELDS and not self.standalone_fills_legacy:
      ret.points = [_point({"trackId": p.trackId, "dRel": p.dRel, "yRel": p.yRel, "vRel": p.vRel, **ACC_LEGACY}) for p in ret.points]
    return ret


def _point(p: dict) -> structs.RadarData.RadarPoint:
  """RadarPoint is trackId / dRel / yRel / vRel; forks that still carry the legacy aRel / yvRel / measured fields get them too."""
  pt = structs.RadarData.RadarPoint()
  pt.trackId, pt.dRel, pt.yRel, pt.vRel = p["trackId"], p["dRel"], p["yRel"], p["vRel"]
  for legacy in LEGACY_FIELDS:
    setattr(pt, legacy, p[legacy])
  return pt


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
  """Wrap a fork's Toyota CarInterface in place: detection in _get_params, dispatch in RadarInterface, PCS alarm in update."""
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

  fork_update = car_interface.update

  def update(self, can_packets, *args, **kwargs):
    ret = fork_update(self, can_packets, *args, **kwargs)
    if is_ars510(self.CP):
      # as the carstate in upstream/opendbc_ars510.patch, read from the raw frames so a quiet 0x100 can't mark CAN invalid
      for _, frames in can_packets:
        for address, dat, src in frames:
          if address == PCS_STATE_ADDR and src == RADAR_BUS:
            self.ars510_pcs_alarm = pcs_alarm(dat)
      cs = ret[0] if isinstance(ret, tuple) else ret  # sunnypilot and StarPilot return (CarState, extra)
      cs.stockFcw = cs.stockFcw or getattr(self, "ars510_pcs_alarm", False)
    return ret

  car_interface._get_params = staticmethod(_get_params)
  car_interface.RadarInterface = RadarInterface
  car_interface.update = update
  car_interface._ars510_hooked = True
  return car_interface
