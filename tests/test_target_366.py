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
