"""Decode-level tests: transport, CRC, slot fields, track IDs, 0x85 structure, and the bundled real samples."""
from __future__ import annotations

import csv
import gzip
import math
import zlib
from pathlib import Path

import pytest

from ars510 import OPENPILOT_CONFIG, RAW_CONFIG, Ars510NativeRadarInterface
from ars510.constants import ID80_IDLE_SLOT, ID80_RECORD_LEN, ID85_RECORD_LEN
from ars510.objects import (
    AGE_SATURATION,
    LAT_DIST,
    LONG_DIST,
    LONG_VEL_GROUND,
    decode_native_slot,
    encode_slot,
)
from ars510.record import id80_crc, id80_crc_ok, occupied_slots
from ars510.shell85 import id85_crc_ok, parse_shell
from ars510.support import parse_0x192
from ars510.tracks import NativeTrackIdAssigner
from ars510.transport import Id80RecordAssembler, Id85RecordAssembler

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample"


def make_record(slots: dict[int, bytes]) -> bytes:
    rec = bytearray(ID80_RECORD_LEN)
    rec[0] = 0xE4
    for s in range(20):
        rec[17 + 36 * s:17 + 36 * (s + 1)] = slots.get(s, ID80_IDLE_SLOT)
    rec[737:741] = id80_crc(bytes(rec[1:737])).to_bytes(4, "little")
    return bytes(rec)


def to_frames(rec: bytes, first: int = 0x12) -> list[bytes]:
    out = [bytes([first]) + rec[0:7]]
    for k in range(1, len(rec) // 7):
        out.append(bytes([0x20 | (k & 0xF)]) + rec[7 * k:7 * k + 7])
    return out


def sample_frames(name: str):
    with gzip.open(SAMPLES / name, "rt") as fh:
        for r in csv.DictReader(fh):
            yield float(r["t_s"]), int(r["bus"]), int(r["address"], 0), bytes.fromhex(r["data_hex"])


class TestTransportAndCrc:
    def test_reassembles_742_byte_record_from_106_frames(self) -> None:
        rec = make_record({0: encode_slot(long_dist=640, lat_dist_left=2048, long_vel_over_ground=600, age_cycles=5)})
        asm = Id80RecordAssembler()
        done = [asm.push(0.001 * i, f) for i, f in enumerate(to_frames(rec))]
        assert all(d is None for d in done[:-1])
        assert done[-1].payload == rec and done[-1].frame_count == 106 and done[-1].time_s == 0.0
        assert id80_crc_ok(rec)

    def test_corrupted_record_fails_crc(self) -> None:
        rec = bytearray(make_record({}))
        rec[100] ^= 1
        assert not id80_crc_ok(bytes(rec))

    def test_frames_before_a_start_are_ignored_and_bad_length_resets(self) -> None:
        asm = Id80RecordAssembler()
        assert asm.push(0.0, bytes([0x21]) + bytes(7)) is None
        assert asm.push(0.0, bytes(7)) is None

    def test_id85_record_is_147_bytes(self) -> None:
        rec = bytes([0x90]) + bytes(ID85_RECORD_LEN - 1)
        asm = Id85RecordAssembler()
        out = [asm.push(0.0, f) for f in to_frames(rec, first=0x10)]
        assert out[-1] is not None and out[-1].payload == rec


class TestSlotFields:
    def test_idle_slots_are_skipped(self) -> None:
        rec = make_record({4: encode_slot(age_cycles=3)})
        assert [s for s, _ in occupied_slots(rec)] == [4]

    def test_field_scales_and_signs(self) -> None:
        slot = encode_slot(long_dist=160 + 16 * 42, lat_dist_left=2048 + 64 * 3, long_vel_over_ground=510 + 100, age_cycles=77)
        o = decode_native_slot(0, slot)
        assert o.d_rel == pytest.approx(42.0)
        assert o.y_rel == pytest.approx(3.0)  # left positive
        assert o.v_long_ground == pytest.approx(0.15 * 99.5)
        assert o.age == 77 and o.geometry_valid and o.lateral_valid

    def test_zero_points(self) -> None:
        o = decode_native_slot(0, encode_slot(long_dist=160, lat_dist_left=2048, age_cycles=1))
        assert o.d_rel == 0.0 and o.y_rel == 0.0
        assert LONG_DIST.zero_code * LONG_DIST.scale == pytest.approx(10.0)  # zero code 160 is exactly 10 m

    def test_lateral_sentinel_and_age_zero(self) -> None:
        assert not decode_native_slot(0, encode_slot(lat_dist_left=10, age_cycles=5)).lateral_valid
        assert not decode_native_slot(0, encode_slot(age_cycles=0)).geometry_valid

    def test_field_layout_does_not_overlap(self) -> None:
        spans = sorted((f.bit_start, f.bit_start + f.bit_len) for f in (LONG_DIST, LAT_DIST, LONG_VEL_GROUND))
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


class TestTrackIds:
    def test_age_restart_and_saturation(self) -> None:
        tr = NativeTrackIdAssigner()
        a = tr.update(0.00, 2, 125)
        assert tr.update(0.06, 2, AGE_SATURATION) == a
        assert tr.update(0.12, 2, AGE_SATURATION) == a  # saturated age keeps the ID
        assert tr.update(0.18, 2, 1) != a  # restart
        with pytest.raises(ValueError):
            tr.update(0.10, 3, 5)  # time went backwards


class TestShellAndSupport:
    def test_shell_cells_exclude_crc_and_trailer(self) -> None:
        rec = bytearray([0x90]) + bytearray(20) + bytearray(range(120)) + bytearray(6)
        rec[141:145] = zlib.crc32(rec[1:141]).to_bytes(4, "little")
        header, cells = parse_shell(bytes(rec))
        assert len(header) == 21 and len(cells) == 10
        assert header + b"".join(c.payload for c in cells) == rec[:141]
        assert cells[-1].payload == rec[129:141]
        rec[145:147] = b"\x12\x34"  # trailer is not covered by this CRC
        assert id85_crc_ok(rec)
        rec[140] ^= 1
        assert not id85_crc_ok(rec)
        with pytest.raises(ValueError, match="CRC mismatch"):
            parse_shell(bytes(rec))

    def test_shell_rejects_wrong_length(self) -> None:
        assert not id85_crc_ok(bytes(146))
        with pytest.raises(ValueError, match="147 bytes"):
            parse_shell(bytes(146))

    def test_0x192(self) -> None:
        assert parse_0x192(bytes.fromhex("00FF00FF")) is None
        t = parse_0x192((640).to_bytes(2, "big") + bytes([7, 0]))
        assert t.distance_m == pytest.approx(30.0) and t.lateral_bin == 7


@pytest.mark.parametrize("name", ["highway_following_30s.csv.gz", "highway_vrel_excursion_25s.csv.gz"])
def test_real_samples_decode_cleanly(name: str) -> None:
    for cfg in (RAW_CONFIG, OPENPILOT_CONFIG):
        iface = Ars510NativeRadarInterface(cfg)
        out = iface.update_many(sample_frames(name))
        assert len(out) > 400 and iface.crc_failures == 0
        for p in out:
            ids = [pt["trackId"] for pt in p["radarData"]["points"]]
            assert len(ids) == len(set(ids))  # never a duplicate ID in one record
            for pt in p["radarData"]["points"]:
                assert math.isfinite(pt["dRel"]) and math.isfinite(pt["yRel"])
                if cfg is OPENPILOT_CONFIG:
                    assert math.isfinite(pt["vRel"]) and pt["age"] >= 60


def test_sample_record_rate_is_the_radar_cycle() -> None:
    iface = Ars510NativeRadarInterface(RAW_CONFIG)
    t = [p["time_s"] for p in iface.update_many(sample_frames("highway_following_30s.csv.gz"))]
    dt = sorted(b - a for a, b in zip(t, t[1:]))
    assert 0.055 < dt[len(dt) // 2] < 0.065


def test_excursion_sample_shows_the_known_false_closing() -> None:
    """The settled lead's over-ground speed dips ~8 m/s for ~1 s while its range keeps opening (docs/06)."""
    iface = Ars510NativeRadarInterface(RAW_CONFIG)
    lead = [(p["time_s"], pt) for p in iface.update_many(sample_frames("highway_vrel_excursion_25s.csv.gz"))
            for pt in p["radarData"]["points"] if pt["age"] >= 60 and abs(pt["yRel"]) < 1.8 and pt["dRel"] < 80]
    v = [pt["v_long_ground"] for _, pt in lead]
    d = [pt["dRel"] for _, pt in lead]
    assert max(v) - min(v) > 6.0
    assert d[-1] > d[0]  # range opened over the sample


@pytest.mark.parametrize("name,records", [("highway_following_30s.csv.gz", 497),
                                          ("highway_vrel_excursion_25s.csv.gz", 414)])
def test_bundled_crc_and_slot_index_invariants(name: str, records: int) -> None:
    from tools.check_structure import audit_sample

    result = audit_sample(SAMPLES / name)
    assert result["id80_records"] == result["id85_records"] == records
    assert result["slots"] == records * 20
    assert result["id85_cells"] == records * 10
    assert result["slot_index_exceptions"] == result["id80_crc_failures"] == result["id85_crc_failures"] == 0


def test_generated_dbc_matches_checked_in_layout() -> None:
    from tools.build_cabana_route import DBC_OUT, dbc_text

    text = dbc_text()
    assert DBC_OUT.read_text() == text
    assert "SG_ SLOT_INDEX_CODE : 2|6@1+" in text
    assert "SG_ SCORE_CODE : 16|8@1+" in text
    assert "SG_ STATE_CODE : 0|2@1+" in text
    assert "ARS510_SHELL85_PAIR" not in text
    assert "ARS510_SHELL85_CELL_09" in text
    assert "ARS510_SHELL85_CELL_10" not in text
    assert "BO_ 1899 ARS510_SHELL85_CRC: 8" in text
