"""0x23B check byte: CRC-8 (poly 0x1D) over the counter nibble, a zero nibble, the low nibble and the value byte."""
from ars510.support import crc_0x23b, parse_0x23b

# frames from the research corpus (payload bytes: value, counter << 4 | low nibble, check)
FRAMES = ["b24009", "b25086", "b2600a", "b27085", "b28003", "b2908c", "b2a000", "b2b08f", "b2c005", "b2d08a", "b2e006", "b2f089",
          "b2000f", "b21080"]


def test_corpus_frames_pass_and_expose_value_and_counter():
    for f in FRAMES:
        value, counter, ok = parse_0x23b(bytes.fromhex(f))
        assert ok and value == 0xB2 and counter == int(f[2], 16)


def test_a_flipped_check_bit_fails_and_startup_frame_is_not_valid():
    good = bytearray.fromhex("b24009")
    good[2] ^= 0x01
    assert parse_0x23b(bytes(good))[2] is False
    assert parse_0x23b(bytes.fromhex("ff0f00")) == (0xFF, 0, False)
    assert parse_0x23b(b"\x00\x00") is None


def test_known_table_entries():
    assert crc_0x23b(0, 0) == 0x59                 # xor-out only
    assert crc_0x23b(0x10, 0) == 0x59 ^ 0xCD       # entry 0x10 of the 0x1D table
    assert crc_0x23b(0x20, 0) == 0x59 ^ 0x87
