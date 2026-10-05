"""The radar's ACC target frames (0x235 / 0x237 / 0x239 / 0x23B), the cycle header (0x190) and the 0x191 companion.

Frames are logged payloads as received; each set comes from one radar cycle."""
from ars510.support import (parse_0x190, parse_0x191, parse_0x192, parse_0x239, parse_0x23b, parse_acc_target,
                            parse_acc_target_arel, parse_acc_target_range_code, parse_acc_target_vrel)

H = bytes.fromhex
TRUCK = dict(a190="0a fc 0a 22 6d 05 50", a191="c6 fc c8 50 58 f0 2e 78", a192="03 73 08 81", a235="0d 65 66 7b 6b 34 57 06",
             a237="00 63 88 c4 a1 0e 1c a0", a239="01 62 40 88 51 13 68 28", a23b="64 61 04")
CAR = dict(a190="06 fc 5a d5 14 5d 40", a191="c8 fc c8 20 48 f0 1e 2d", a192="06 03 05 07", a235="b1 35 65 85 2b a4 f0 01",
           a237="8e 36 bc 1a e9 b0 bd 50", a239="82 31 40 8a d6 a8 a2 e8", a23b="6f 30 8c")
IDLE = dict(a190="06 fc 01 7e f5 32 50", a235="bf 61 64 80 0b 24 00 ff", a237="20 60 00 3e 80 00 00 00",
            a239="e2 67 80 00 0b f7 a9 90", a23b="5c 60 00")


def test_truck_target_every_field():
    t = parse_acc_target(H(TRUCK["a235"]), H(TRUCK["a237"]))
    assert t.target_id == 6 and abs(t.d_rel - 45.225) < 1e-9 and abs(t.y_rel - 1.96) < 1e-9
    assert t.v_rel == -4.625 and t.a_rel == 0.25 and abs(t.v_lat - 1.0875) < 1e-9 and t.a_lat == 0.25
    assert not t.in_path and t.in_path_level == 2 and t.tracker_codes == (33, 195)
    # the single-field helpers read the same bits
    assert parse_acc_target_vrel(H(TRUCK["a235"])) == t.v_rel and parse_acc_target_arel(H(TRUCK["a235"])) == t.a_rel
    assert parse_acc_target_range_code(H(TRUCK["a237"])) * 0.025 == t.d_rel


def test_lateral_is_twelve_bits_and_matches_the_summary():
    t = parse_acc_target(H(TRUCK["a235"]), H(TRUCK["a237"]))
    s = parse_0x192(H(TRUCK["a192"]))
    assert abs(s.d_rel - t.d_rel) < 0.1
    assert abs((s.field1_code13 - 2048) * 1.5 - t.y_rel * 100) < 3      # one summary lateral code = 1.5 ACC codes
    c = parse_acc_target(H(CAR["a235"]), H(CAR["a237"]))
    s = parse_0x192(H(CAR["a192"]))
    assert c.in_path and c.in_path_level == 5 and abs((s.field1_code13 - 2048) * 1.5 - c.y_rel * 100) < 3


def test_class_width_and_timestamp():
    info = parse_0x239(H(TRUCK["a239"]))
    head = parse_0x190(H(TRUCK["a190"]))
    assert info.target_class == 2 and info.present and info.in_object_list
    assert info.timestamp_us == head.timestamp_us == 170028293 and head.active_summaries == 2 and head.counter == 5
    assert parse_0x23b(H(TRUCK["a23b"])) == (260, 6, True)             # 2.60 m: the width uses the byte-1 low nibble
    tpl = parse_0x191(H(TRUCK["a191"]))
    assert (round(tpl.width_m, 1), round(tpl.height_m, 1), tpl.length_m) == (2.2, 2.3, 12.0) and tpl.quality == 30
    info = parse_0x239(H(CAR["a239"]))
    tpl = parse_0x191(H(CAR["a191"]))
    assert info.target_class == 1 and info.timestamp_us == parse_0x190(H(CAR["a190"])).timestamp_us
    assert (round(tpl.width_m, 1), tpl.height_m, tpl.length_m) == (1.8, 1.5, 4.5) and tpl.score == 100 and tpl.age == 126
    assert parse_0x23b(H(CAR["a23b"])) == (140, 3, True)               # car class is clipped at 1.40 m


def test_idle_frames():
    assert parse_acc_target(H(IDLE["a235"]), H(IDLE["a237"])) is None
    info = parse_0x239(H(IDLE["a239"]))
    assert info.target_class == 7 and not info.present and not info.in_object_list
    assert info.timestamp_us == parse_0x190(H(IDLE["a190"])).timestamp_us
    assert parse_0x23b(H(IDLE["a23b"])) == (0, 6, True)
    assert parse_acc_target_arel(H(IDLE["a235"])) == 0.0 and parse_acc_target_vrel(H(IDLE["a235"])) == 0.0
    assert parse_0x191(H("fe fe fe fc fc ff fe ff")) is None and parse_0x190(H("ff fc ff ff ff ff f0")) is None
    assert parse_0x239(b"\x00") is None and parse_acc_target(b"", b"") is None
