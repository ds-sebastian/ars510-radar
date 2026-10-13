"""0x195 range field: the function-tracker object of the event frame (docs/05)."""
from ars510.support import A195_IDLE, parse_0x195_range


def test_idle_and_short_frames_have_no_range():
    assert parse_0x195_range(A195_IDLE) is None
    assert parse_0x195_range(bytes(7)) is None


def test_range_is_the_low_eleven_bits_at_5_cm():
    assert abs(parse_0x195_range(bytes.fromhex("7E9B1CA05B22A137")) - 0x137 * 0.05) < 1e-9   # 15.55 m, recorded frame
    assert abs(parse_0x195_range(bytes.fromhex("7FBF1FE0001AC1CB")) - 0x1CB * 0.05) < 1e-9   # 22.95 m, no ACC target


def test_range_is_the_acc_distance_code_halved():
    for acc_code in (300, 612, 613, 1999):                       # ACC distance code, 0.025 m
        frame = (0x7E00000000000000 | (acc_code // 2)).to_bytes(8, "big")
        assert 0 <= acc_code * 0.025 - parse_0x195_range(frame) < 0.05
