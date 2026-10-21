"""0x100 byte 0 bit 1, the radar's PCS alarm: set during the alarm, ignored on the power-up frame, dropped when stale (docs/15)."""
from ars510.support import PcsAlarm


def frame(byte0: int) -> bytes:
    return bytes([byte0, 0, 0, 0, 0, 0, 0])


def test_power_up_frame_is_not_an_alarm():
    a = PcsAlarm()
    a.update(0.0, bytes([0xFF, 0xFF, 0, 0, 0, 0, 0]))
    assert not a.active(0.0)


def test_alarm_follows_the_bit():
    a = PcsAlarm()
    a.update(0.0, frame(0x00))
    assert not a.active(0.0)
    a.update(0.1, frame(0x02))
    assert a.active(0.1)
    a.update(0.2, frame(0x00))
    assert not a.active(0.2)


def test_alarm_drops_when_frames_stop():
    a = PcsAlarm()
    a.update(1.0, frame(0x02))
    assert a.active(1.4)
    assert not a.active(1.6)


def test_empty_frame_leaves_the_state_alone():
    a = PcsAlarm()
    a.update(0.0, frame(0x02))
    a.update(0.1, b"")
    assert a.active(0.1)
