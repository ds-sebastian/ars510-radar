"""0x680: one object from the radar's function-level tracker (range 1/32 m, lateral 1/64 m, over-ground speed 0.15 m/s)."""
from ars510.support import parse_0x680


def test_stationary_roadside_object():
    o = parse_0x680(bytes.fromhex("01a526907fc1809f"))
    assert o.selector == 1 and o.d_rel == 165.125 and o.y_rel == -5.75 and o.flags == 1
    assert abs(o.v_ground) <= 0.15  # stationary within one code


def test_vehicle():
    o = parse_0x680(bytes.fromhex("0375ec19a7c880ef"))
    assert o.selector == 3 and o.d_rel == 117.90625 and o.y_rel == -15.609375 and o.flags == 8
    assert abs(o.v_ground - 23.85) < 1e-9


def test_idle_and_short_frames_return_none():
    assert parse_0x680(bytes.fromhex("000008008000800a")) is None
    assert parse_0x680(bytes(8)) is None
    assert parse_0x680(b"\x00\x00") is None
