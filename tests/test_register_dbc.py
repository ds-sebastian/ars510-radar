"""The raw register DBC must preserve the five-bit carry across 15/16."""
from pathlib import Path
import re


def test_a501_dbc_preserves_active_carry_and_startup_bits():
    text = (Path(__file__).resolve().parents[1] / "dbc/ars510_radar_bus.dbc").read_text()
    message = text.split("BO_ 1281 ", 1)[1].split("\nBO_ ", 1)[0]
    fields = {
        name: (int(start), int(length))
        for name, start, length in re.findall(r"SG_ (\w+) : (\d+)\|(\d+)@1\+", message)
    }
    for byte5, code, low3 in ((0x7C, 15, 4), (0x84, 16, 4), (0xA4, 20, 4), (0x54, 10, 4), (0xF8, 31, 0)):
        word = int.from_bytes(bytes((0, 0, 0, 0, 0, byte5, 0)), "little")
        start, length = fields["A501_STATUS_43_5"]
        assert (word >> start) & ((1 << length) - 1) == code
        start, length = fields["A501_B5_LOW3"]
        assert (word >> start) & ((1 << length) - 1) == low3
    assert "A501_STATUS_40_4" not in text
    assert "A501_B5_HIGH4" not in text
