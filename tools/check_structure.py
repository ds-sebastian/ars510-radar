#!/usr/bin/env python3
"""Reproduce CRC and physical-slot-index evidence from the bundled CAN samples."""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ars510.record import id80_crc_ok
from ars510.shell85 import id85_crc_ok, parse_shell
from ars510.transport import Id80RecordAssembler, Id85RecordAssembler


def audit_sample(path: Path) -> dict[str, int]:
    assemblers = {0x80: Id80RecordAssembler(), 0x85: Id85RecordAssembler()}
    counts = dict(id80_records=0, id80_crc_failures=0, slots=0, slot_index_exceptions=0,
                  id85_records=0, id85_crc_failures=0, id85_cells=0)
    with gzip.open(path, "rt") as stream:
        for row in csv.DictReader(stream):
            addr = int(row["address"], 0)
            if int(row["bus"]) != 1 or addr not in assemblers:
                continue
            record = assemblers[addr].push(float(row["t_s"]), bytes.fromhex(row["data_hex"]))
            if record is None:
                continue
            payload = record.payload
            if addr == 0x80:
                counts["id80_records"] += 1
                if not id80_crc_ok(payload):
                    counts["id80_crc_failures"] += 1
                    continue
                for slot in range(20):
                    code = payload[17 + 36 * slot] >> 2
                    counts["slots"] += 1
                    counts["slot_index_exceptions"] += int(code not in (slot, 63))
            else:
                counts["id85_records"] += 1
                if not id85_crc_ok(payload):
                    counts["id85_crc_failures"] += 1
                    continue
                prefix, cells = parse_shell(payload)
                assert prefix + b"".join(c.payload for c in cells) == payload[:141]
                counts["id85_cells"] += len(cells)
    return counts


def main() -> int:
    paths = sorted((REPO / "data" / "sample").glob("*.csv.gz"))
    if not paths:
        raise SystemExit("No bundled samples found")
    results = {p.name: audit_sample(p) for p in paths}
    print(json.dumps(results, indent=2))
    return int(any(r["id80_crc_failures"] or r["id85_crc_failures"] or r["slot_index_exceptions"]
                   or not r["id80_records"] or not r["id85_records"] for r in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
