"""0x680: one object from the radar's function-level tracker (range 1/32 m, lateral 0.015 m, over-ground speed 0.15 m/s)."""
from ars510.support import parse_0x680


def test_stationary_roadside_object():
    o = parse_0x680(bytes.fromhex("01 a5 26 90 7f c1 80 9f"))
    assert o.selector == 1 and o.d_rel == 165.125 and abs(o.y_rel - -368 * 0.015) < 1e-9 and o.flags == 1
    assert o.stationary and not o.oncoming and not o.seen_moving
    assert abs(o.v_ground) <= 0.15  # stationary within one code


def test_vehicle():
    o = parse_0x680(bytes.fromhex("03 75 ec 19 a7 c8 80 ef"))
    assert o.selector == 3 and o.d_rel == 117.90625 and abs(o.y_rel - -999 * 0.015) < 1e-9 and o.flags == 8
    assert o.seen_moving and not o.stationary and not o.oncoming
    assert abs(o.v_ground - 23.85) < 1e-9


def test_idle_and_short_frames_return_none():
    assert parse_0x680(bytes.fromhex("00 00 08 00 80 00 80 0a")) is None
    assert parse_0x680(bytes(8)) is None
    assert parse_0x680(b"\x00\x00") is None
