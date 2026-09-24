"""CRC-checked ID85 evidence projection; cell alignment and semantics provisional.

The checksum boundary is verified. Ten raw cells in [21:141] are an analysis
projection, not ten established objects. Never interpret CRC/trailer as a cell.
"""
from __future__ import annotations

from dataclasses import dataclass
import zlib

from .constants import ID85_RECORD_LEN

HEADER_LEN = 21
CELL_COUNT = 10
CELL_LEN = 12
CRC_START, CRC_END = 141, 145


@dataclass(frozen=True)
class ShellCell:
    index: int
    payload: bytes

def id85_crc_ok(record: bytes) -> bool:
    if len(record) != ID85_RECORD_LEN:
        return False
    return int.from_bytes(record[CRC_START:CRC_END], "little") == zlib.crc32(record[1:CRC_START])


def parse_shell(record: bytes) -> tuple[bytes, list[ShellCell]]:
    """Return the proposed 21-byte prefix and ten raw cells; reject bad CRC."""
    if len(record) != ID85_RECORD_LEN:
        raise ValueError(f"0x85 record must be {ID85_RECORD_LEN} bytes, got {len(record)}")
    if not id85_crc_ok(record):
        raise ValueError("0x85 CRC mismatch")
    cells = []
    for k in range(CELL_COUNT):
        o = HEADER_LEN + CELL_LEN * k
        cells.append(ShellCell(k, record[o:o + CELL_LEN]))
    return record[:HEADER_LEN], cells
