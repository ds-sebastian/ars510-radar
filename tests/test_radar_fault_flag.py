"""0x196 byte 1 bit 0, the radar's own fault flag: active after two consecutive set cycles, cleared by the first clear one (docs/05)."""
from ars510.support import RadarFaultFlag


def frame(bit: int) -> bytes:
    return bytes([0xFF, bit, 0, 0, 0, 0, 0, 0])


def test_single_power_up_cycle_is_ignored():
    f = RadarFaultFlag()
    f.update(bytes([0xFF] * 8))  # power-up frame: byte 1 = 0xFF for one cycle
    assert not f.active
    f.update(frame(0))
    assert not f.active


def test_two_consecutive_cycles_activate_and_one_clear_cycle_clears():
    f = RadarFaultFlag()
    f.update(frame(1))
    f.update(frame(1))
    assert f.active
    for _ in range(1000):  # held through a blocked minute
        f.update(frame(1))
    assert f.active
    f.update(frame(0))
    assert not f.active


def test_short_frame_leaves_the_state_alone():
    f = RadarFaultFlag()
    f.update(frame(1))
    f.update(frame(1))
    f.update(b"\x00")
    assert f.active
