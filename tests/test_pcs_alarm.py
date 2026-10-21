"""0x100 byte 0 bit 1, the radar's PCS alarm; the power-up FF FF frame is not an alarm (docs/15)."""
from ars510.support import pcs_alarm


def test_pcs_alarm():
    assert pcs_alarm(bytes([0x02, 0, 0, 0, 0, 0, 0]))
    assert not pcs_alarm(bytes(7))
    assert not pcs_alarm(bytes([0xFF, 0xFF, 0, 0, 0, 0, 0]))  # first frame after power-up
    assert not pcs_alarm(b"")
