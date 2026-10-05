"""Interface tests on synthetic 0x80 records."""
from __future__ import annotations

from dataclasses import replace
import math
import zlib

import pytest

from ars510.constants import ID80_IDLE_SLOT
from ars510.interface import (
    FUSED_CONFIG,
    BASE_CONFIG,
    ALL_TRACKS_CONFIG,
    RELINK_MIN_PUBLISH_AGE,
    NATIVE_VREL_STATUS,
    UNRESOLVED_NAN,
    Ars510NativeRadarInterface,
    NativeInterfaceConfig,
    parse_toyota_speed_mps,
)
from ars510.objects import ACCEL_LIKE, AGE, LAT_DIST, LAT_VEL, LENGTH, LONG_DIST, LONG_VEL_GROUND, WIDTH

IDLE = ID80_IDLE_SLOT


def slot_bytes(*, r_code, lat_code, vel_code, age, width=17, length=49, vy_code=0, ax_code=0) -> bytes:
    value = 0
    fields = [(LONG_DIST, r_code), (LAT_DIST, lat_code), (LONG_VEL_GROUND, vel_code), (AGE, age), (WIDTH, width),
              (LENGTH, length), (LAT_VEL, vy_code), (ACCEL_LIKE, ax_code)]
    for field, code in fields:
        value |= (code & ((1 << field.bit_len) - 1)) << field.bit_start
    return value.to_bytes(36, "little")


def record(slots: dict[int, bytes]) -> bytes:
    rec = bytearray(742)
    rec[0] = 0xE4
    for s in range(20):
        rec[17 + 36 * s:17 + 36 * (s + 1)] = slots.get(s, IDLE)
    rec[737:741] = (zlib.crc32(bytes(rec[1:737])) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(rec)


def frames(rec: bytes, t0: float):
    out = [(t0, 1, 0x80, bytes([0x12]) + rec[0:7])]
    for k in range(1, 106):
        out.append((t0 + 0.0001 * k, 1, 0x80, bytes([0x20]) + rec[7 * k:7 * k + 7]))
    return out


def speed_frame(t: float, v_mps: float):
    code = round(v_mps * 3.6 / 0.01)
    return (t, 0, 0xB4, bytes(5) + code.to_bytes(2, "big") + b"\x00")


class TestNativeInterface:
    def test_decodes_one_object_with_signed_lateral_and_relative_velocity(self) -> None:
        iface = Ars510NativeRadarInterface()
        rec = record({3: slot_bytes(r_code=160 + 16 * 30, lat_code=2048 - 128, vel_code=int(510.5 + 100), age=40)})
        out = iface.update_many([speed_frame(0.0, 20.0)] + frames(rec, 0.01))
        assert len(out) == 1
        (p,) = out[0]["radarData"]["points"]
        assert p["dRel"] == pytest.approx(30.0)
        assert p["yRel"] == pytest.approx(-128 * 0.015)  # right of ego
        assert p["vRel"] == pytest.approx(0.15 * 99.5 - 20.0, abs=0.01)
        assert p["vrel_status"] == NATIVE_VREL_STATUS

    def test_vrel_is_nan_without_ego_speed(self) -> None:
        iface = Ars510NativeRadarInterface()
        rec = record({0: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=10)})
        (p,) = iface.update_many(frames(rec, 0.0))[0]["radarData"]["points"]
        assert math.isnan(p["vRel"]) and p["vrel_status"] == UNRESOLVED_NAN

    def test_age_zero_object_is_not_emitted(self) -> None:
        iface = Ars510NativeRadarInterface()
        rec = record({0: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=0)})
        assert iface.update_many(frames(rec, 0.0))[0]["radarData"]["points"] == []

    def test_min_publish_age_holds_back_settling_tracks_but_keeps_their_id(self) -> None:
        iface = Ars510NativeRadarInterface(NativeInterfaceConfig(min_publish_age=60))
        ids = []
        for k, age in enumerate([58, 59, 60, 61]):
            rec = record({2: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=age)})
            pts = iface.update_many(frames(rec, 0.06 * k))[0]["radarData"]["points"]
            ids.append(pts[0]["trackId"] if pts else None)
        assert ids[:2] == [None, None] and iface.settling_suppressed == 2
        assert ids[2] is not None and ids[2] == ids[3]  # lifecycle was tracked while held back

    def _relink_run(self, new_objs, cfg):
        """Track in slot 3 at 50 m for ages 40-49, gone for ~0.6 s, then new objects (slot, r_m) from age 2."""
        iface = Ars510NativeRadarInterface(cfg)
        t, out = 0.0, []
        for age in range(40, 50):
            rec = record({3: slot_bytes(r_code=160 + 16 * 50, lat_code=2048, vel_code=int(510.5 + 100), age=age)})
            out += iface.update_many([speed_frame(t, 15.0)] + frames(rec, t + 0.001)); t += 0.06
        t += 0.6
        for age in range(2, 12):
            slots = {s: slot_bytes(r_code=160 + 16 * r, lat_code=2048, vel_code=int(510.5 + 100), age=age) for s, r in new_objs}
            out += iface.update_many([speed_frame(t, 15.0)] + frames(record(slots), t + 0.001)); t += 0.06
        old = out[0]["radarData"]["points"][0]["trackId"]
        new = {p["slot"]: p["trackId"] for p in out[-1]["radarData"]["points"]}
        return iface, old, new

    def test_relink_gives_a_reinitialized_track_the_lost_id(self) -> None:
        # vRel = 0.15*99.5 - 15 = -0.075 m/s, so the prediction stays at ~50 m
        iface, old, new = self._relink_run([(7, 50)], NativeInterfaceConfig(min_publish_age=6, relink_max_gap_s=2.5))
        assert new[7] == old and iface.relinks == 1

    def test_relink_rejects_wrong_position_ambiguity_and_missing_delay(self) -> None:
        cfg = NativeInterfaceConfig(min_publish_age=6, relink_max_gap_s=2.5)
        _, old, new = self._relink_run([(7, 70)], cfg)
        assert new[7] != old
        _, old, new = self._relink_run([(7, 50), (8, 51)], cfg)
        assert old not in new.values()
        _, old, new = self._relink_run([(7, 50)], NativeInterfaceConfig(min_publish_age=1, relink_max_gap_s=2.5))
        assert new[7] != old

    def test_track_id_persists_and_restarts_on_age_reset(self) -> None:
        iface = Ars510NativeRadarInterface()
        seq = [40, 41, 42, 0, 1]
        ids = []
        for k, age in enumerate(seq):
            rec = record({5: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=age)})
            pts = iface.update_many(frames(rec, 0.06 * k))[0]["radarData"]["points"]
            ids.append(pts[0]["trackId"] if pts else None)
        assert ids[0] == ids[1] == ids[2]
        assert ids[3] is None  # age 0: stale position, suppressed
        assert ids[4] is not None and ids[4] != ids[0]

    def test_bad_crc_is_dropped(self) -> None:
        iface = Ars510NativeRadarInterface()
        rec = bytearray(record({0: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=10)}))
        rec[20] ^= 0xFF
        assert iface.update_many(frames(bytes(rec), 0.0)) == []
        assert iface.crc_failures == 1

    def test_other_buses_and_addresses_are_ignored(self) -> None:
        iface = Ars510NativeRadarInterface()
        assert iface.update_frame(0.0, 2, 0x80, bytes(8)) is None
        assert iface.update_frame(0.0, 1, 0x85, bytes(8)) is None

    def test_toyota_speed_parse(self) -> None:
        assert parse_toyota_speed_mps(bytes(5) + (3600).to_bytes(2, "big") + b"\x00") == pytest.approx(10.0)
        assert parse_toyota_speed_mps(b"\x00") is None


def test_openpilot_profile_holds_settling_tracks_and_relinks() -> None:
    assert BASE_CONFIG.min_publish_age == 60 and BASE_CONFIG.relink_max_gap_s > 0
    assert BASE_CONFIG.min_publish_age >= RELINK_MIN_PUBLISH_AGE
    assert ALL_TRACKS_CONFIG.min_publish_age == 1 and ALL_TRACKS_CONFIG.relink_max_gap_s == 0


def test_openpilot_profile_applies_the_measured_velocity_scale() -> None:
    assert BASE_CONFIG.vground_scale == pytest.approx(0.149 / 0.15)
    iface = Ars510NativeRadarInterface(NativeInterfaceConfig(vground_scale=0.149 / 0.15))
    rec = record({3: slot_bytes(r_code=600, lat_code=2048, vel_code=int(510.5 + 100), age=40)})
    (p,) = iface.update_many([speed_frame(0.0, 20.0)] + frames(rec, 0.01))[0]["radarData"]["points"]
    assert p["vRel"] == pytest.approx(0.149 * 99.5 - 20.0, abs=0.01)


class TestRangeFusionAndUnresolvedVrel:
    @staticmethod
    def _run(cfg, ranges, v_ego=20.0, vel_code=int(510.5 + 100), dt=0.06):
        iface = Ars510NativeRadarInterface(cfg)
        out = []
        for i, r in enumerate(ranges):
            t = i * dt
            rec = record({0: slot_bytes(r_code=160 + round(16 * r), lat_code=2048, vel_code=vel_code, age=min(126, 60 + i))})
            for payload in iface.update_many([speed_frame(t, v_ego)] + frames(rec, t + 0.001)):
                out += payload["radarData"]["points"]
        return out

    def test_default_publishes_raw_range(self) -> None:
        pts = self._run(NativeInterfaceConfig(), [30.0, 34.0, 30.0])
        assert [p["dRel"] for p in pts] == pytest.approx([30.0, 34.0, 30.0])

    def test_fusion_follows_velocity_and_damps_range_walks(self) -> None:
        vrel = 0.15 * 99.5 - 20.0  # about -5.1 m/s
        truth = [50.0 + vrel * 0.06 * i for i in range(60)]
        walk = [d + (4.0 if (i // 5) % 2 else -4.0) for i, d in enumerate(truth)]
        pts = self._run(NativeInterfaceConfig(range_fusion_gain=0.1), walk)
        err_fused = max(abs(p["dRel"] - d) for p, d in zip(pts[20:], truth[20:]))
        err_raw = max(abs(w - d) for w, d in zip(walk[20:], truth[20:]))
        assert err_fused < 0.5 * err_raw

    def test_fusion_restarts_from_measurement_without_velocity(self) -> None:
        iface = Ars510NativeRadarInterface(NativeInterfaceConfig(range_fusion_gain=0.1))
        rec = record({0: slot_bytes(r_code=160 + 16 * 40, lat_code=2048, vel_code=600, age=70)})
        (p,) = iface.update_many(frames(rec, 0.0))[0]["radarData"]["points"]
        assert math.isnan(p["vRel"]) and p["dRel"] == pytest.approx(40.0)

    def test_drop_unresolved_vrel_withholds_nan_points(self) -> None:
        iface = Ars510NativeRadarInterface(NativeInterfaceConfig(drop_unresolved_vrel=True))
        rec = record({0: slot_bytes(r_code=600, lat_code=2048, vel_code=600, age=10)})
        assert iface.update_many(frames(rec, 0.0))[0]["radarData"]["points"] == []
        assert iface.unresolved_suppressed == 1
        out = iface.update_many([speed_frame(0.1, 20.0)] + frames(rec, 0.11))
        assert len(out[0]["radarData"]["points"]) == 1


def _acc_frames(t: float, vrel: float, x: float, y: float) -> list:
    v = round(vrel / 0.125) + 1024
    b235 = (v << 29 | 2 << 26 | 4 << 48).to_bytes(8, "big")  # byte 1 bit 2: target available
    xc, yc = round((x - 9.6) / 5.26), round(y / 0.01) + 2000
    b237 = (xc << 47 | yc << 27 | 1 << 10).to_bytes(8, "big")  # bit 10: target present
    return [(t, 1, 0x235, b235), (t, 1, 0x237, b237)]


def test_acc_target_decodes_round_trip() -> None:
    from ars510.support import parse_acc_target_position, parse_acc_target_vrel
    (_, _, _, b235), (_, _, _, b237) = _acc_frames(0.0, -2.3, 41.7, 1.2)
    assert parse_acc_target_vrel(b235) == pytest.approx(-2.3, abs=0.07)
    x, y = parse_acc_target_position(b237)
    assert abs(x - 41.7) < 2.7 and y == pytest.approx(1.2, abs=0.01)


FUSED_ACC = replace(FUSED_CONFIG, min_publish_age=1, relink_max_gap_s=0.0, range_fusion_gain=0.0, publish_speed_std_mps=99.0,
                    vground_scale=1.0)


def test_acc_target_reading_pulls_only_the_matched_object() -> None:
    from ars510.objects import encode_slot
    cfg = replace(FUSED_ACC, young_sigma_scale=1.0)
    iface = Ars510NativeRadarInterface(cfg)
    # lead at 40 m in lane with a native vRel glitch (-6 m/s); a second car 3.6 m to the left with the same glitch
    # 240|7 = 40: object-list sigma 1.8 m/s, so the ACC target (0.5 m/s) dominates once the filter has run a few cycles
    frames = []
    for k in range(6):
        t = 0.06 * k
        lead, side = (encode_slot(long_dist=160 + 40 * 16, lat_dist_left=2048 + dy, long_vel_over_ground=round(510.5 + 4.0 / 0.15),
                                  age_cycles=80 + k, vel_uncertainty_candidate=40) for dy in (0, 240))
        frames += [speed_frame(t, 10.0)] + _acc_frames(t + 0.005, 0.0, 40.0, 0.0) + frames_(record({0: lead, 1: side}), t + 0.01)
    pts = {round(p["yRel"]): p for p in iface.update_many(frames)[-1]["radarData"]["points"]}
    native = (round(510.5 + 4.0 / 0.15) - 510.5) * 0.15 - 10.0
    assert pts[0]["vRel"] > native + 4  # the matched lead follows the ACC target (0.0), not the -6 m/s glitch
    assert pts[4]["vRel"] == pytest.approx(native, abs=1e-6)  # the side car is untouched
    assert iface._acc_assoc[0] is not None


frames_ = frames


def _sliding_lead_run() -> list[float]:
    """Matched lead at 40 m; then its native range slides to 30 m while vRel drops to -6 m/s (a re-association
    excursion). The ACC target stays at 40 m / 0.0 m/s throughout."""
    from ars510.objects import encode_slot
    iface = Ars510NativeRadarInterface(FUSED_ACC)
    out = []
    for k in range(12):
        t = 0.06 * k
        d = 40.0 if k < 4 else 40.0 - 2.5 * (k - 3)
        vg = 10.0 if k < 4 else 4.0
        lead = encode_slot(long_dist=round(160 + d * 16), lat_dist_left=2048,
                           long_vel_over_ground=round(510.5 + vg / 0.15), age_cycles=80 + k, vel_uncertainty_candidate=40)
        fr = [speed_frame(t, 10.0)] + _acc_frames(t + 0.001, 0.0, 40.0, 0.0) + frames_(record({0: lead}), t + 0.002)
        out += [p["vRel"] for r in iface.update_many(fr) for p in r["radarData"]["points"]]
    return out


def test_acc_association_holds_through_a_range_slide() -> None:
    # the native range slides 20 m away from the ACC coarse range, yet the track keeps its ACC reading
    assert min(_sliding_lead_run()) > -2.5  # the object list alone says -6 m/s


def test_acc_association_rematches_after_an_acc_target_jump() -> None:
    from ars510.objects import encode_slot
    iface = Ars510NativeRadarInterface(FUSED_ACC)
    near = encode_slot(long_dist=160 + 30 * 16, lat_dist_left=2048, long_vel_over_ground=round(510.5 + 4.0 / 0.15), age_cycles=80)
    far = encode_slot(long_dist=160 + 60 * 16, lat_dist_left=2048, long_vel_over_ground=round(510.5 + 4.0 / 0.15), age_cycles=80)
    fr = [speed_frame(0.0, 10.0)] + _acc_frames(0.001, 0.0, 30.0, 0.0) + frames_(record({0: near, 1: far}), 0.002)
    fr += [speed_frame(0.06, 10.0)] + _acc_frames(0.061, 0.0, 60.0, 0.0) + frames_(record({0: near, 1: far}), 0.062)
    out = iface.update_many(fr)
    ids = {round(p["dRel"]): p["trackId"] for p in out[-1]["radarData"]["points"]}
    assert iface._acc_assoc is not None and iface._acc_assoc[0] == ids[60]  # the target jumped to the far car


@pytest.mark.parametrize("address,data", [
    (0x235, bytes.fromhex("000164800B2400FF")),
    (0x237, bytes.fromhex("0000003E80000000")),
    (0x235, bytes(7)), (0x237, bytes(9)),
])
def test_acc_unavailable_clears_both_halves(address, data):
    iface = Ars510NativeRadarInterface(FUSED_ACC)
    iface.update_many(_acc_frames(0.0, -2.0, 40.0, 0.0))
    assert iface._acc_vrel is not None and iface._acc_pos is not None
    iface.update_frame(0.01, 1, address, data)
    assert iface._acc_vrel is None and iface._acc_pos is None
    iface.update_frame(*_acc_frames(0.02, -2.0, 40.0, 0.0)[0])
    assert iface._acc_vrel is not None and iface._acc_pos is None
    iface.update_frame(*_acc_frames(0.03, -2.0, 40.0, 0.0)[1])
    assert iface._acc_pos is not None


def test_idle_acc_cannot_pull_a_real_closing_object():
    iface = Ars510NativeRadarInterface(FUSED_ACC)
    rec = record({0: slot_bytes(r_code=320, lat_code=2048, vel_code=537, age=80)})
    inputs = [speed_frame(0.0, 10.0),
              (0.001, 1, 0x235, bytes.fromhex("000164800B2400FF")),
              (0.001, 1, 0x237, bytes.fromhex("0000003E80000000"))] + frames(rec, 0.01)
    (point,) = iface.update_many(inputs)[0]["radarData"]["points"]
    assert point["vRel"] == pytest.approx((537 - 510.5) * .15 - 10.)
    assert point["dRel"] == 10.0 and iface._acc_assoc is None


def test_other_bus_idle_does_not_clear_acc():
    iface = Ars510NativeRadarInterface()
    iface.update_many(_acc_frames(0.0, -2.0, 40.0, 0.0))
    before = iface._acc_vrel, iface._acc_pos
    iface.update_frame(0.01, 0, 0x235, bytes(8))
    assert (iface._acc_vrel, iface._acc_pos) == before


def _guard_run(vel_codes: list[int], cfg) -> list:
    """One mature track (age 70+) at 40 m with the given 64|10 codes, one record every 60 ms; returns its points."""
    from ars510.objects import encode_slot
    iface = Ars510NativeRadarInterface(cfg)
    out = []
    for k, vel in enumerate(vel_codes):
        t = 0.06 * k
        slot = encode_slot(long_dist=160 + 16 * 40, lat_dist_left=2048, long_vel_over_ground=vel, age_cycles=70 + k)
        out.append(iface.update_many([speed_frame(t, 20.0)] + frames(record({2: slot}), t + 0.001))[0]["radarData"]["points"])
    return out


def test_saturation_guard_withholds_the_sentinel_and_restarts_the_track_id() -> None:
    base = round(510.5 + 20.0 / 0.15)
    codes = [base] * 5 + [1023] * 3 + [1014, base] + [base] * 3
    guarded = _guard_run(codes, NativeInterfaceConfig(drop_saturated_codes=True))
    assert [len(p) for p in guarded] == [1] * 5 + [0] * 4 + [1] * 4  # sentinel and its decaying tail withheld
    assert guarded[9][0]["trackId"] != guarded[4][0]["trackId"]  # radard restarts the track's filter
    plain = _guard_run(codes, NativeInterfaceConfig())
    assert all(len(p) == 1 for p in plain) and plain[5][0]["vRel"] > 50  # without the guard the reading is published


def test_age_one_initialization_template_is_withheld() -> None:
    template = slot_bytes(r_code=160, lat_code=2047, vel_code=700, age=1, width=0, length=0)
    out = Ars510NativeRadarInterface(ALL_TRACKS_CONFIG).update_many(frames(record({0: template}), 0.0))
    assert out and out[-1]["radarData"]["points"] == []


def test_yvrel_removes_ego_rotation_and_arel_subtracts_ego_accel() -> None:
    iface = Ars510NativeRadarInterface(replace(ALL_TRACKS_CONFIG, include_metadata=True))
    # yaw rate 0.1 rad/s left: raw = (5.7296 deg/s + 125) / 0.244 = 535.8 -> 536
    yaw_raw = 536
    yaw = (yaw_raw * 0.244 - 125) * math.pi / 180
    out = None
    for k in range(10):
        t = 0.06 * k
        iface.update_frame(t, 0, 0x24, bytes([(yaw_raw >> 8) & 3, yaw_raw & 0xFF, 0, 0, 0, 0, 0, 0]))
        v = 20.0 + 1.0 * t  # ego accelerating at 1 m/s^2
        iface.update_frame(t, 0, 0xB4, bytes(5) + int(round(v * 3.6 * 100)).to_bytes(2, "big") + bytes(1))
        rec = record({2: slot_bytes(r_code=160 + 16 * 40, lat_code=2048, vel_code=644, age=70 + k,
                                    vy_code=531, ax_code=536)})
        out = iface.update_many(frames(rec, t + 0.001))
    pt = out[-1]["radarData"]["points"][0]
    assert pt["yvRel"] == pytest.approx((531 - 510.5) * 0.15 - yaw * 40.0, abs=1e-6)
    assert pt["aRel"] == pytest.approx((536 - 511) * 0.04 - 1.0, abs=0.1)


def test_yvrel_is_nan_without_yaw_rate() -> None:
    iface = Ars510NativeRadarInterface(ALL_TRACKS_CONFIG)
    iface.set_ego_speed(20.0, 0.0)
    rec = record({2: slot_bytes(r_code=160 + 16 * 40, lat_code=2048, vel_code=644, age=70, vy_code=531, ax_code=536)})
    pt = iface.update_many(frames(rec, 0.001))[-1]["radarData"]["points"][0]
    assert math.isnan(pt["yvRel"]) and math.isnan(pt["aRel"])


def test_measured_follows_the_predicted_flag_and_existence_is_exposed() -> None:
    from ars510.objects import encode_slot
    iface = Ars510NativeRadarInterface(NativeInterfaceConfig())
    measured = encode_slot(long_dist=160 + 30 * 16, lat_dist_left=2048, long_vel_over_ground=round(510.5 + 10.0 / 0.15),
                           age_cycles=80, existence_pct=100)
    predicted = encode_slot(long_dist=160 + 40 * 16, lat_dist_left=2048 + 230, long_vel_over_ground=round(510.5 + 10.0 / 0.15),
                            age_cycles=80, existence_pct=60, predicted=1)
    out = iface.update_many([speed_frame(0.0, 10.0)] + frames_(record({0: measured, 1: predicted}), 0.01))
    pts = {round(p["dRel"]): p for p in out[0]["radarData"]["points"]}
    assert pts[30]["measured"] is True and pts[30]["existence_pct"] == 100
    assert pts[40]["measured"] is False and pts[40]["existence_pct"] == 60


def _fused_run(cfg: NativeInterfaceConfig, d0: float, unc: int, v_of_t, n: int = 80, summary: bool = False,
               age0: int = 120) -> list[tuple[float, float]]:
    """One lead at range d0 (closing with its relative speed); over-ground speed v_of_t(k), 240|7 = unc."""
    from ars510.objects import encode_slot
    iface = Ars510NativeRadarInterface(cfg)
    out, d = [], d0
    for k in range(n):
        t = 0.06 * k
        vg = v_of_t(k)
        d += (vg - 10.0) * 0.06 if not summary else -0.06
        lead = encode_slot(long_dist=round(160 + d * 16), lat_dist_left=2048, long_vel_over_ground=round(510.5 + vg / 0.15),
                           age_cycles=min(126, age0 + k), vel_uncertainty_candidate=unc)
        fr = [speed_frame(t, 10.0)]
        if summary:
            code = round(160 + d * 16)
            fr.append((t + 0.001, 1, 0x192, code.to_bytes(2, "big") + (2048).to_bytes(2, "big")))
        fr += frames_(record({0: lead}), t + 0.002)
        out += [(t, p["vRel"]) for r in iface.update_many(fr) for p in r["radarData"]["points"]]
    return out


def test_fused_filter_weights_each_reading_by_the_radars_sigma() -> None:
    cfg = replace(NativeInterfaceConfig(), min_publish_age=1, fused_speed_filter=True, publish_speed_std_mps=99.0)
    noisy = lambda amp: (lambda k: 10.0 + (amp if k % 2 else -amp))
    spread = lambda pts: max(v for _, v in pts[20:]) - min(v for _, v in pts[20:])
    far = spread(_fused_run(cfg, 80.0, 50, noisy(2.25)))       # sigma 2.25 m/s, noise of that size
    near = spread(_fused_run(cfg, 15.0, 5, noisy(0.3)))        # sigma 0.23 m/s
    assert far / 4.5 < 0.06 and near / 0.6 > 3 * far / 4.5   # far readings are averaged, near ones followed
    assert NativeInterfaceConfig().fused_speed_filter is False


def test_fused_filter_follows_the_summary_through_an_excursion() -> None:
    """Object-list speed drifts 6 m/s low (sigma 1.35 m/s) while the 0x192 summary keeps closing at 1 m/s."""
    cfg = replace(NativeInterfaceConfig(), min_publish_age=1, fused_speed_filter=True, publish_speed_std_mps=99.0)
    out = _fused_run(cfg, 70.0, 30, lambda k: 9.0 if k < 25 else 3.0, summary=True)
    assert all(v > -2.5 for _, v in out[-20:])                # object list says -7 m/s; the radar's tracker says -1


def test_fused_filter_publishes_young_far_tracks_once_their_speed_is_known() -> None:
    cfg = replace(NativeInterfaceConfig(), min_publish_age=60, fused_speed_filter=True)
    near = _fused_run(cfg, 20.0, 8, lambda k: 10.0, n=40, age0=55)
    far = _fused_run(cfg, 90.0, 60, lambda k: 10.0, n=40, age0=55)
    assert near and near[0][0] < 0.06 * 7                     # published at age 60
    assert not far or far[0][0] > near[0][0] + 0.5            # speed std still above 0.75 m/s at age 60


def test_colored_filter_follows_the_summary_and_still_tracks_a_lasting_speed_change() -> None:
    from ars510 import COLORED_CONFIG
    cfg = replace(COLORED_CONFIG, min_publish_age=1, publish_speed_std_mps=99.0)
    excursion = _fused_run(cfg, 70.0, 30, lambda k: 9.0 if k < 25 else 3.0, summary=True)
    assert all(v > -2.5 for _, v in excursion[-20:])          # the 6 m/s drop is read as object-list bias
    step = _fused_run(cfg, 40.0, 30, lambda k: 10.0 if k < 20 else 7.0, n=140)
    assert -3.0 < step[-1][1] < -2.0                         # without trackers a lasting change is followed, but slowly
    assert COLORED_CONFIG.fused_speed_filter and COLORED_CONFIG.speed_bias_tau_s > 0
