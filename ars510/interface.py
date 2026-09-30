"""openpilot-shaped radar interface on the native 0x80 decode.

Feed it raw CAN frames `(time_s, bus, address, data)`. It reassembles 0x80 records on the radar bus, checks
the record CRC, decodes every occupied slot, and returns RadarData-shaped dicts:

    {"time_s": t, "radarData": {"points": [...], "errors": {...}}}

with points carrying dRel (m, forward), yRel (m, LEFT positive), vRel (m/s, over-ground velocity minus ego
speed) and trackId (from the radar's own slot / age lifecycle).

Ego speed comes from Toyota SPEED (0xB4) on the car bus, or from `set_ego_speed`. Without a fresh ego speed
vRel is NaN, and OPENPILOT_CONFIG withholds such points (radard's per-track Kalman never recovers from a NaN).

Use OPENPILOT_CONFIG for anything openpilot-facing. RAW_CONFIG publishes every valid track and is the
decode-level view used for analysis. STEADY_CONFIG adds velocity-aided range, far-range vRel smoothing,
the velocity-jump guard and delayed first publication for far tracks
(docs/07_velocity_excursions.md has the measured effect of each option).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import inf, isfinite, nan
from collections.abc import Iterable

from .constants import ACC_TARGET_POS_ADDR, ACC_TARGET_VREL_ADDR, CAR_BUS, ID80_ADDR, RADAR_BUS, TOYOTA_SPEED_ADDR
from .objects import decode_native_slot
from .record import id80_crc_ok, occupied_slots
from .support import parse_acc_target_position, parse_acc_target_vrel
from .tracks import NativeTrackIdAssigner
from .transport import Id80RecordAssembler

RAMP_RESET_GAP_S = 3.5  # a longer silence restarts the ramp limiter's state
GUARD_ID_STRIDE = 10_000_000  # added to a trackId after a guard episode, so radard restarts that track's filter
RELINK_MIN_LOST_AGE = 30
RELINK_MIN_PUBLISH_AGE = 6


@dataclass(frozen=True)
class NativeInterfaceConfig:
    radar_bus: int = RADAR_BUS
    ego_speed_bus: int = CAR_BUS
    max_ego_speed_age_s: float = 0.5
    include_metadata: bool = True
    # Suppress age-1 samples only (a subset of what min_publish_age does).
    suppress_age_one: bool = False
    # Hold back tracks younger than this many cycles. Young tracks carry unconverged range and velocity
    # (stopped cars read as moving; one lead read 38 m while ~100 m away for ~3 s). 60 cycles ~ 3.6 s.
    min_publish_age: int = 1
    # When a new track is first published, give it the trackId of a settled track (age >= 30) lost within
    # this many seconds if it starts where that track predicts and the match is one-to-one. 0 disables.
    # Requires min_publish_age >= RELINK_MIN_PUBLISH_AGE so the lost ID has ended (no duplicate IDs).
    relink_max_gap_s: float = 0.0
    # Multiplies the decoded over-ground velocity. Against Toyota 0xB4, steady following reads 0.149 m/s/code
    # instead of nominal 0.150. This empirical 0.667% alignment is separate from the measured
    # ~1.5% discrepancy between ego references; it is not an exact inverse or an OEM wire constant.
    # Use 1.0 with a carState.vEgo or GPS ego reference.
    vground_scale: float = 1.0
    # Withhold points whose vRel is unresolved (no fresh ego speed).
    drop_unresolved_vrel: bool = False
    # --- options, off by default (docs/07 has their measured effect; STEADY_CONFIG turns on the first and third) ---
    # Velocity-aided range: predict dRel with vRel, correct toward measured dRel with this gain (0 disables).
    range_fusion_gain: float = 0.0
    # Clip vRel to the track's own causal range slope over this window +/- vrel_range_clip_mps (0 disables).
    vrel_range_clip_window_s: float = 0.0
    vrel_range_clip_mps: float = 3.5
    # Causal EMA on vRel with tau = clip((dRel-30)/30, 0, 1) * this value (0 disables).
    vrel_smooth_far_tau_s: float = 0.0
    # Uncertainty-weighted vRel smoothing: tau = this value * clip((code - lo) / (hi - lo), 0, 1), where code is the
    # candidate velocity-uncertainty field 240|7. Confident tracks pass through unsmoothed (0 disables).
    vrel_smooth_unc_tau_s: float = 0.0
    vrel_smooth_unc_lo: float = 25.0
    vrel_smooth_unc_hi: float = 42.0
    # ACC-target cross-check: the radar's own ACC target (0x235 / 0x237) is matched to an object by position. The matched
    # object's vRel is clipped to the target's closing speed +/- this many m/s (0 disables). 1.0 is the p95 of their
    # difference on normal samples (docs/05).
    acc_target_clip_mps: float = 0.0
    acc_target_max_age_s: float = 0.1
    # Saturation guard: withhold a mature track's point while its velocity code is the invalid 1023 (or 0), and after
    # that until the velocity is back within sat_recover_mps of the last good value (the sentinel decays over ~6
    # records) or guard_hold_s has passed. The track then continues under a new trackId (docs/07).
    drop_saturated_codes: bool = False
    sat_recover_mps: float = 5.0
    # Velocity-jump guard: a record whose over-ground velocity differs from the track's last accepted one by more than
    # this (m/s, 0 = off) is withheld the same way. A new level that persists for guard_hold_s is accepted as a real
    # step under a new trackId.
    vjump_thresh_mps: float = 0.0
    guard_hold_s: float = 1.0
    guard_min_age: int = 60  # younger tracks legitimately converge and are not guarded
    # Delay the first publication of a far track while its velocity settles. Once published, it stays eligible.
    far_min_publish_age: int = 0
    far_publish_range_m: float = 70.0
    # Ramp limiter: a mature track's over-ground velocity may move AWAY from its slow reference (EMA, ramp_ref_tau_s)
    # by at most ramp_up_mps2 / ramp_down_mps2; moves back toward the reference pass unchanged. Real vehicles do not
    # change speed at 20+ m/s^2, while excursion ramps do (docs/07). 0 = off.
    ramp_up_mps2: float = 0.0
    ramp_down_mps2: float = 0.0
    ramp_ref_tau_s: float = 3.0


# Every valid track, radar's own IDs: the decode-level view.
RAW_CONFIG = NativeInterfaceConfig(min_publish_age=1, relink_max_gap_s=0.0)
# Base openpilot-facing profile (docs/08_openpilot_integration.md).
OPENPILOT_CONFIG = NativeInterfaceConfig(
    min_publish_age=60, relink_max_gap_s=3.5, vground_scale=0.149 / 0.15, drop_unresolved_vrel=True,
    drop_saturated_codes=True,
)
# Recommended profile ("K4" + guards, docs/07): velocity-aided range, far-range vRel smoothing and the 8 m/s velocity-jump
# guard. Removes about half of radar's extra output roughness over vision-only for ~0.07 s of radar's head start, and
# about a fifth of the hard radar-only braking requests. Far tracks first publish at age 100 to reduce settling pickups.
# The ramp limiter (+4 / -6 m/s^2 away from a 3 s reference) removes gradual-ramp excursions and a further ~23% of the
# hard radar-only requests.
STEADY_CONFIG = replace(OPENPILOT_CONFIG, range_fusion_gain=0.1, vrel_smooth_far_tau_s=1.0, vjump_thresh_mps=8.0,
                       far_min_publish_age=100, far_publish_range_m=70.0, ramp_up_mps2=4.0, ramp_down_mps2=6.0)

NATIVE_VREL_STATUS = "native_over_ground_minus_ego"
UNRESOLVED_NAN = "unresolved_nan"


def parse_toyota_speed_mps(data: bytes) -> float | None:
    """Toyota SPEED (0xB4): bytes 5-6 big-endian, 0.01 km/h."""
    if len(data) < 7:
        return None
    return int.from_bytes(data[5:7], "big") * 0.01 / 3.6


class Ars510NativeRadarInterface:
    def __init__(self, config: NativeInterfaceConfig | None = None) -> None:
        self.config = config or NativeInterfaceConfig()
        self._assembler = Id80RecordAssembler()
        self._tracks = NativeTrackIdAssigner()
        self._v_ego: float | None = None
        self._v_ego_time_s: float | None = None
        self.crc_failures = 0
        self.records = 0
        self.startup_suppressed = 0
        self.settling_suppressed = 0
        self.relinks = 0
        self.unresolved_suppressed = 0
        self._first: dict[int, tuple[float, float, float]] = {}  # native id -> (t, x, y) at first age>=2 sample
        self._last: dict[int, tuple[float, float, float, float, int]] = {}  # -> (t, x, y, vrel, age) latest
        self._out_id: dict[int, int] = {}
        self._claimed: set[int] = set()
        self._range_est: dict[int, tuple[float, float, float]] = {}
        self._range_hist: dict[int, list[tuple[float, float]]] = {}
        self._vrel_smooth: dict[int, tuple[float, float]] = {}
        self._ramp: dict[int, tuple[float, float, float]] = {}  # tid -> (t, limited v, reference)
        self._acc_vrel: tuple[float, float] | None = None  # (time, closing speed)
        self._acc_pos: tuple[float, float, float] | None = None  # (time, coarse x, y)
        self.acc_target_clips = 0
        self._guard_state: dict[int, list] = {}  # tid -> [t_last, ref_v, episode_start | None, saturated_in_episode]
        self._guard_gen: dict[int, int] = {}
        self.guard_rejected = 0

    # ---- inputs -----------------------------------------------------------------------------------
    def set_ego_speed(self, v_ego_mps: float, time_s: float) -> None:
        if isfinite(v_ego_mps) and isfinite(time_s):
            self._v_ego, self._v_ego_time_s = float(v_ego_mps), float(time_s)

    def _fresh_ego_speed(self, time_s: float) -> float | None:
        if self._v_ego is None or self._v_ego_time_s is None:
            return None
        if abs(time_s - self._v_ego_time_s) > self.config.max_ego_speed_age_s:
            return None
        return self._v_ego

    def update_frame(self, time_s: float, bus: int, addr: int, data: bytes) -> dict | None:
        if bus == self.config.ego_speed_bus and addr == TOYOTA_SPEED_ADDR:
            v = parse_toyota_speed_mps(bytes(data))
            if v is not None:
                self.set_ego_speed(v, time_s)
            return None
        if bus == self.config.radar_bus and addr in (ACC_TARGET_VREL_ADDR, ACC_TARGET_POS_ADDR):
            data = bytes(data)
            available = len(data) == 8 and (
                bool(data[1] & 4) if addr == ACC_TARGET_VREL_ADDR
                else data[2:] != bytes.fromhex("003E80000000")
            )
            if not available:
                # Idle payloads decode numerically; neither cached half may survive target loss.
                self._acc_vrel = self._acc_pos = None
                return None
            if addr == ACC_TARGET_VREL_ADDR:
                v = parse_acc_target_vrel(bytes(data))
                self._acc_vrel = (time_s, v) if v is not None else self._acc_vrel
            else:
                p = parse_acc_target_position(bytes(data))
                self._acc_pos = (time_s, p[0], p[1]) if p is not None else self._acc_pos
            return None
        if bus != self.config.radar_bus or addr != ID80_ADDR:
            return None
        complete = self._assembler.push(time_s, bytes(data))
        if complete is None:
            return None
        if not id80_crc_ok(complete.payload):
            self.crc_failures += 1
            return None
        self.records += 1
        return self._payload(complete.time_s, complete.payload)

    def update_many(self, frames: Iterable[tuple[float, int, int, bytes]]) -> list[dict]:
        out = []
        for time_s, bus, addr, data in frames:
            p = self.update_frame(time_s, bus, addr, data)
            if p is not None:
                out.append(p)
        return out

    # ---- track re-link ----------------------------------------------------------------------------
    def _relink(self, nid: int, time_s: float, seen: set[int]) -> int:
        cfg = self.config
        if cfg.relink_max_gap_s <= 0 or cfg.min_publish_age < RELINK_MIN_PUBLISH_AGE or nid not in self._first:
            return nid

        def matches(first: tuple[float, float, float], lid: int) -> bool:
            t0, x0, y0 = first
            tl, xl, yl, vl, al = self._last[lid]
            gap = t0 - tl
            if al < RELINK_MIN_LOST_AGE or not (0.0 < gap <= cfg.relink_max_gap_s):
                return False
            x_pred = xl + (vl if isfinite(vl) else 0.0) * gap
            return abs(x0 - x_pred) <= max(3.0, 0.10 * xl) + 1.0 * gap and abs(y0 - yl) <= 1.2 + 0.5 * gap

        lost = [lid for lid in self._last if lid not in seen and lid != nid and lid not in self._claimed
                and time_s - self._last[lid][0] > self._tracks.max_gap_s]
        cands = [lid for lid in lost if matches(self._first[nid], lid)]
        if len(cands) != 1:
            return nid
        lid = cands[0]
        # ambiguity: another unpublished new track also starts where the lost one predicts
        if any(o != nid and o not in self._out_id and o in self._first and matches(self._first[o], lid)
               for o in self._last if o in seen):
            self._claimed.add(lid)  # nobody inherits an ambiguous ID
            return nid
        self._claimed.add(lid)
        self.relinks += 1
        return self._out_id.get(lid, lid)

    # ---- ACC-target cross-check ----------------------------------------------------------------------
    def _acc_target_match(self, time_s: float, decoded: list) -> tuple[int | None, float]:
        """The object the radar's own ACC target describes: best position match, cost < 1 and margin > 1, age >= 60."""
        cfg = self.config
        if cfg.acc_target_clip_mps <= 0 or self._acc_vrel is None or self._acc_pos is None:
            return None, nan
        if abs(time_s - self._acc_vrel[0]) > cfg.acc_target_max_age_s or abs(time_s - self._acc_pos[0]) > cfg.acc_target_max_age_s:
            return None, nan
        _, ax, ay = self._acc_pos
        costs = sorted((abs(obj.d_rel - ax) / 6.0 + abs(obj.y_rel - ay) / 0.5, tid, obj.age)
                       for _, obj, tid in decoded if obj.geometry_valid and obj.lateral_valid)
        if not costs or costs[0][0] >= 1.0 or costs[0][2] < 60:
            return None, nan
        if len(costs) > 1 and costs[1][0] - costs[0][0] <= 1.0:
            return None, nan
        return costs[0][1], self._acc_vrel[1]

    # ---- candidate options --------------------------------------------------------------------------
    def _range_clipped_vrel(self, tid: int, time_s: float, d_meas: float, vrel: float) -> float:
        w = self.config.vrel_range_clip_window_s
        hist = self._range_hist.setdefault(tid, [])
        if hist and time_s - hist[-1][0] > 0.5:
            hist.clear()
        hist.append((time_s, d_meas))
        while hist and hist[0][0] < time_s - w:
            hist.pop(0)
        if not isfinite(vrel) or len(hist) < 9 or hist[-1][0] - hist[0][0] < 0.7 * w:
            return vrel
        n = len(hist)
        mt = sum(t for t, _ in hist) / n
        md = sum(d for _, d in hist) / n
        den = sum((t - mt) ** 2 for t, _ in hist)
        if den <= 0:
            return vrel
        slope = sum((t - mt) * (d - md) for t, d in hist) / den
        m = self.config.vrel_range_clip_mps
        return min(max(vrel, slope - m), slope + m)

    def _smoothed_vrel(self, tid: int, time_s: float, d_meas: float, vrel: float, unc_code: int = 0) -> float:
        cfg = self.config
        prev = self._vrel_smooth.get(tid)
        tau = min(max((d_meas - 30.0) / 30.0, 0.0), 1.0) * cfg.vrel_smooth_far_tau_s
        if cfg.vrel_smooth_unc_tau_s > 0 and cfg.vrel_smooth_unc_hi > cfg.vrel_smooth_unc_lo:
            w = (unc_code - cfg.vrel_smooth_unc_lo) / (cfg.vrel_smooth_unc_hi - cfg.vrel_smooth_unc_lo)
            tau = max(tau, min(max(w, 0.0), 1.0) * cfg.vrel_smooth_unc_tau_s)
        if prev is None or not isfinite(vrel) or not isfinite(prev[1]) or not 0.0 < time_s - prev[0] <= 0.5 or tau <= 0:
            out = vrel
        else:
            out = prev[1] + min(1.0, (time_s - prev[0]) / tau) * (vrel - prev[1])
        self._vrel_smooth[tid] = (time_s, out)
        return out

    def _fused_range(self, tid: int, time_s: float, d_meas: float, vrel: float) -> float:
        prev = self._range_est.get(tid)
        if prev is None or not isfinite(vrel) or not isfinite(prev[2]) or not 0.0 < time_s - prev[0] <= 0.5:
            d = d_meas
        else:
            d = prev[1] + 0.5 * (prev[2] + vrel) * (time_s - prev[0])
            d += self.config.range_fusion_gain * (d_meas - d)
        self._range_est[tid] = (time_s, d, vrel)
        return d

    # ---- output -----------------------------------------------------------------------------------
    def _guard(self, tid: int, time_s: float, v: float, code: int, age: int) -> bool:
        """True when this record of the track is rejected by the saturation / velocity-jump guard."""
        cfg = self.config
        sat = cfg.drop_saturated_codes and (code >= 1023 or code == 0)
        st = self._guard_state.get(tid)
        if st is not None and time_s - st[0] > 0.5:
            st = None  # the track was silent: restart the reference
        if st is None:
            if age < cfg.guard_min_age:
                self._guard_state.pop(tid, None)
                return False
            self._guard_state[tid] = [time_s, nan, time_s, True] if sat else [time_s, v, None, False]
            self.guard_rejected += sat
            return sat
        st[0] = time_s
        ref = st[1]
        bad = sat
        if not sat and isfinite(ref):
            dv = abs(v - ref)
            bad = (cfg.vjump_thresh_mps > 0 and dv > cfg.vjump_thresh_mps) or (
                cfg.drop_saturated_codes and st[3] and dv > cfg.sat_recover_mps)
        if not bad:
            if st[2] is not None:  # episode over: continue under a new trackId
                self._guard_gen[tid] = self._guard_gen.get(tid, 0) + 1
                st[2], st[3] = None, False
            st[1] = v
            return False
        if st[2] is None:
            st[2] = time_s
        if sat:
            st[3] = True
        elif time_s - st[2] > cfg.guard_hold_s:  # a persistent new level is a real step
            self._guard_gen[tid] = self._guard_gen.get(tid, 0) + 1
            st[1], st[2], st[3] = v, None, False
            return False
        self.guard_rejected += 1
        return True

    def _ramp_limited(self, tid: int, time_s: float, v: float, age: int) -> float:
        cfg = self.config
        st = self._ramp.get(tid)
        # guard-withheld records do not update this state, so allow gaps as long as a guard episode
        if st is None or age < cfg.guard_min_age or time_s - st[0] > RAMP_RESET_GAP_S:
            self._ramp[tid] = (time_s, v, v)
            return v
        t0, prev, ref = st
        dt = time_s - t0
        if abs(v - ref) <= abs(prev - ref):
            new = v  # back toward the reference
        else:
            up = cfg.ramp_up_mps2 * dt if cfg.ramp_up_mps2 > 0 else inf
            down = cfg.ramp_down_mps2 * dt if cfg.ramp_down_mps2 > 0 else inf
            new = prev + min(max(v - prev, -down), up)
        self._ramp[tid] = (time_s, new, ref + min(dt / cfg.ramp_ref_tau_s, 1.0) * (new - ref))
        return new

    def _payload(self, time_s: float, record: bytes) -> dict:
        cfg = self.config
        v_ego = self._fresh_ego_speed(time_s)
        decoded = []
        for slot, seg in occupied_slots(record):
            obj = decode_native_slot(slot, seg)
            # every occupied slot updates the lifecycle, including age 0, so a restart is never missed
            decoded.append((slot, obj, self._tracks.update(time_s, slot, obj.age)))
        seen = {tid for _, _, tid in decoded}
        acc_tid, acc_vrel = self._acc_target_match(time_s, decoded)
        points = []
        for slot, obj, tid in decoded:
            if not obj.geometry_valid or not obj.lateral_valid:
                continue
            if (cfg.drop_saturated_codes or cfg.vjump_thresh_mps > 0) and \
                    self._guard(tid, time_s, obj.v_long_ground, obj.vel_code, obj.age):
                continue
            v_long = obj.v_long_ground
            if cfg.ramp_up_mps2 > 0 or cfg.ramp_down_mps2 > 0:
                v_long = self._ramp_limited(tid, time_s, v_long, obj.age)
            v_ground = v_long * cfg.vground_scale
            vrel = float(v_ground - v_ego) if v_ego is not None else nan
            if tid == acc_tid and isfinite(vrel):
                clipped = min(max(vrel, acc_vrel - cfg.acc_target_clip_mps), acc_vrel + cfg.acc_target_clip_mps)
                self.acc_target_clips += clipped != vrel
                vrel = clipped
            if cfg.vrel_range_clip_window_s > 0:
                vrel = self._range_clipped_vrel(tid, time_s, obj.d_rel, vrel)
            if cfg.vrel_smooth_far_tau_s > 0 or cfg.vrel_smooth_unc_tau_s > 0:
                vrel = self._smoothed_vrel(tid, time_s, obj.d_rel, vrel, obj.vel_unc_code)
            d_rel = self._fused_range(tid, time_s, obj.d_rel, vrel) if cfg.range_fusion_gain > 0 else obj.d_rel
            if obj.age >= 2:
                self._first.setdefault(tid, (time_s, obj.d_rel, obj.y_rel))
                self._last[tid] = (time_s, obj.d_rel, obj.y_rel, vrel, obj.age)
            if cfg.suppress_age_one and obj.age == 1:
                self.startup_suppressed += 1
                continue
            if obj.age < cfg.min_publish_age:
                self.settling_suppressed += 1
                continue
            if tid not in self._out_id and obj.age < cfg.far_min_publish_age and obj.d_rel > cfg.far_publish_range_m:
                self.settling_suppressed += 1
                continue
            if cfg.drop_unresolved_vrel and not isfinite(vrel):
                self.unresolved_suppressed += 1
                continue
            if tid not in self._out_id:
                self._out_id[tid] = self._relink(tid, time_s, seen)
            point = {
                "trackId": int(self._out_id[tid]) + GUARD_ID_STRIDE * self._guard_gen.get(tid, 0),
                "dRel": float(d_rel),
                "yRel": float(obj.y_rel),
                "vRel": vrel,
                "aRel": nan,
                "yvRel": nan,
                "measured": True,
            }
            if cfg.include_metadata:
                point.update(slot=slot, age=obj.age, v_long_ground=float(v_ground), native_id=tid,
                             move_state=obj.move_state, oncoming_flag=obj.oncoming_flag,
                             vrel_status=NATIVE_VREL_STATUS if v_ego is not None else UNRESOLVED_NAN)
            points.append(point)
        self._prune(time_s)
        errors = {"canError": False, "radarFault": False, "wrongConfig": False, "radarUnavailableTemporary": False}
        return {"time_s": float(time_s), "radarData": {"points": points, "errors": errors}}

    def _prune(self, time_s: float) -> None:
        if len(self._last) > 400:  # forget tracks lost long ago
            horizon = time_s - max(self.config.relink_max_gap_s, 1.0) - 60.0
            for k in [k for k, v in self._last.items() if v[0] < horizon]:
                self._last.pop(k, None)
                self._first.pop(k, None)
        for store in (self._range_est, self._vrel_smooth, self._guard_state, self._ramp):
            if len(store) > 400:
                for k in [k for k, v in store.items() if v[0] < time_s - 5.0]:
                    store.pop(k, None)
        if len(self._range_hist) > 400:
            for k in [k for k, v in self._range_hist.items() if not v or v[-1][0] < time_s - 5.0]:
                self._range_hist.pop(k, None)
