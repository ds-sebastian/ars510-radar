"""Interface tests on synthetic 0x80 records."""
from __future__ import annotations

import math
import zlib

import pytest

from ars510.constants import ID80_IDLE_SLOT
from ars510.interface import (
    OPENPILOT_CONFIG,
    RAW_CONFIG,
    RELINK_MIN_PUBLISH_AGE,
    NATIVE_VREL_STATUS,
    UNRESOLVED_NAN,
    Ars510NativeRadarInterface,
    NativeInterfaceConfig,
    parse_toyota_speed_mps,
)
from ars510.objects import AGE, LAT_DIST, LONG_DIST, LONG_VEL_GROUND

IDLE = ID80_IDLE_SLOT


def slot_bytes(*, r_code, lat_code, vel_code, age) -> bytes:
    value = 0
    for field, code in [(LONG_DIST, r_code), (LAT_DIST, lat_code), (LONG_VEL_GROUND, vel_code), (AGE, age)]:
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
        rec = record({3: slot_bytes(r_code=160 + 16 * 30, lat_code=2048 - 64 * 2, vel_code=int(510.5 + 100), age=40)})
        out = iface.update_many([speed_frame(0.0, 20.0)] + frames(rec, 0.01))
        assert len(out) == 1
        (p,) = out[0]["radarData"]["points"]
        assert p["dRel"] == pytest.approx(30.0)
        assert p["yRel"] == pytest.approx(-2.0)  # right of ego
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
    assert OPENPILOT_CONFIG.min_publish_age == 60 and OPENPILOT_CONFIG.relink_max_gap_s > 0
    assert OPENPILOT_CONFIG.min_publish_age >= RELINK_MIN_PUBLISH_AGE
    assert RAW_CONFIG.min_publish_age == 1 and RAW_CONFIG.relink_max_gap_s == 0


def test_openpilot_profile_applies_the_measured_velocity_scale() -> None:
    assert OPENPILOT_CONFIG.vground_scale == pytest.approx(0.149 / 0.15)
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


def test_range_clip_bounds_vrel_to_the_track_range_slope() -> None:
    cfg = NativeInterfaceConfig(vrel_range_clip_window_s=2.0, vrel_range_clip_mps=1.0)
    # range constant at 40 m while the velocity field claims about -5.1 m/s closing
    pts = TestRangeFusionAndUnresolvedVrel._run(cfg, [40.0] * 60)
    late = [p["vRel"] for p in pts[40:]]
    assert all(v == pytest.approx(-1.0, abs=0.05) for v in late)
    raw = TestRangeFusionAndUnresolvedVrel._run(NativeInterfaceConfig(), [40.0] * 60)
    assert raw[-1]["vRel"] == pytest.approx(0.15 * 99.5 - 20.0, abs=0.01)


def test_far_vrel_smoothing_leaves_near_raw_and_lags_far() -> None:
    cfg = NativeInterfaceConfig(vrel_smooth_far_tau_s=1.0)
    near = TestRangeFusionAndUnresolvedVrel._run(cfg, [20.0] * 10)
    assert all(p["vRel"] == pytest.approx(0.15 * 99.5 - 20.0, abs=0.01) for p in near)
    # far object: ego speed steps from 20 to 25 m/s; smoothed vRel approaches the new value with a ~1 s lag
    iface = Ars510NativeRadarInterface(cfg)
    vals = []
    for i in range(70):
        t = i * 0.06
        rec = record({0: slot_bytes(r_code=160 + 16 * 80, lat_code=2048, vel_code=int(510.5 + 100), age=min(126, 60 + i))})
        for payload in iface.update_many([speed_frame(t, 20.0 if i < 10 else 25.0)] + frames(rec, t + 0.001)):
            vals += [p["vRel"] for p in payload["radarData"]["points"]]
    raw_after = 0.15 * 99.5 - 25.0
    assert vals[10] > raw_after + 3.0  # not jumped yet
    assert abs(vals[-1] - raw_after) < 0.5  # converged ~3.6 s after the step
