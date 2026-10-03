"""0x23B check byte: CRC-8 (poly 0x1D) over the counter nibble, a zero nibble, the low nibble and the value byte."""
from ars510.support import crc_0x23b, parse_0x23b

# frames in received byte order (check, counter << 4 | low nibble, value)
FRAMES = ["0940b2", "8650b2", "0a60b2", "8570b2", "0380b2", "8c90b2", "00a0b2", "8fb0b2", "05c0b2", "8ad0b2", "06e0b2", "89f0b2",
          "0f00b2", "8010b2"]
# logged 0x23B frames from a fresh drive (value 0), as received
LOGGED = ["d61000", "5a2000", "d53000", "5f4000", "d05000", "5c6000", "d37000", "558000", "da9000", "56a000"]


def test_corpus_frames_pass_and_expose_value_and_counter():
    for f in FRAMES:
        value, counter, ok = parse_0x23b(bytes.fromhex(f))
        assert ok and value == 0xB2 and counter == int(f[2], 16)


def test_logged_frames_pass_in_received_byte_order():
    for f in LOGGED:
        value, counter, ok = parse_0x23b(bytes.fromhex(f))
        assert ok and value == 0 and counter == int(f[2], 16)
    assert not any(parse_0x23b(bytes.fromhex(f)[::-1])[2] for f in LOGGED)  # the reversed order is wrong


def test_a_flipped_check_bit_fails_and_startup_frame_is_not_valid():
    good = bytearray.fromhex("0940b2")
    good[0] ^= 0x01
    assert parse_0x23b(bytes(good))[2] is False
    assert parse_0x23b(bytes.fromhex("000fff")) == (0xFF, 0, False)
    assert parse_0x23b(b"\x00\x00") is None


def test_known_table_entries():
    assert crc_0x23b(0, 0) == 0x59                 # xor-out only
    assert crc_0x23b(0x10, 0) == 0x59 ^ 0xCD       # entry 0x10 of the 0x1D table
    assert crc_0x23b(0x20, 0) == 0x59 ^ 0x87
