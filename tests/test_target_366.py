"""Car-bus 0x366 fixed coding, sentinel and nine-bit boundary checks."""
import pytest

from ars510.support import parse_0x366


def test_observed_closing_target():
    # A recorded target report: about 38 m, -20km/h in the accompanying 0x365.
    t = parse_0x366(bytes.fromhex("50003a30908200"))
    assert t.speed_code == 116 and t.distance_code == 48
    assert t.d_rel == pytest.approx(38.4)
    assert abs(t.v_rel - -20 / 3.6) <= .5 / 3.6
    assert t.header_raw == 0x5000 and t.tail_raw == 0x908200


def test_distance_msb_is_speed_lsb():
    a = parse_0x366(bytes.fromhex("50004d00007a00"))
    b = parse_0x366(bytes.fromhex("52004d80007a00"))
    assert a.distance_code == b.distance_code == 0
    assert a.speed_code == 154 and b.speed_code == 155
    assert a.v_rel == pytest.approx(-.5 / 3.6) and b.v_rel == 0
    assert b.header_raw == 0x5200


def test_idle_word_is_not_a_numeric_target():
    assert parse_0x366(bytes.fromhex("50007fff007a00")) is None
    assert parse_0x366(bytes.fromhex("52007fff007a00")) is None
    assert parse_0x366(bytes(6)) is None
    assert parse_0x366(bytes(8)) is None


def test_zero_payload_preserves_codes_without_inventing_a_sentinel():
    t = parse_0x366(bytes(7))
    assert t.speed_code == t.distance_code == 0
    assert t.v_rel < 0 and t.d_rel == 0


@pytest.mark.parametrize("raw,code", [("5000fd0f188200", 506), ("5000dd5a187a00", 442),
                                     ("5000fc16688200", 504)])
def test_observed_high_codes_preserve_range_but_do_not_invent_positive_speed(raw, code):
    t = parse_0x366(bytes.fromhex(raw))
    assert t.speed_code == code and t.v_rel is None
    assert t.d_rel == pytest.approx((bytes.fromhex(raw)[3] & 127) * .8)
    assert t.tail_raw == int(raw[8:], 16)


def test_unobserved_high_domain_is_also_unqualified():
    # The 256 boundary is an API qualification limit, not a claimed signed encoding.
    assert parse_0x366(bytes.fromhex("50007f80000200")).v_rel == pytest.approx(100 * 5 / 36)
    assert parse_0x366(bytes.fromhex("50008000000200")).v_rel is None


def test_lateral_code_is_signed_five_bits_with_no_target_value():
    # byte 5 high five bits: 0 -> centre, 3 -> right 1 m, 29 (-3) -> left 1 m, 15 -> no target
    assert parse_0x366(bytes.fromhex("50003a30900200")).lateral_code == 0
    right = parse_0x366(bytes.fromhex("50003a30901a00"))
    left = parse_0x366(bytes.fromhex("50003a3090ea00"))
    assert right.lateral_code == 3 and right.y_rel == pytest.approx(-1.02)
    assert left.lateral_code == -3 and left.y_rel == pytest.approx(1.02)
    assert parse_0x366(bytes.fromhex("50003a30907a00")).y_rel is None
    assert parse_0x366(bytes.fromhex("50003a30908200")).y_rel is None  # -16: invalid
