# 03. The metadata record on 0x85

0x85 carries a segmented record at the radar cycle cadence. The first frame starts `10 90`; retaining bytes 1..7 from each of 21 frames gives 147 bytes, including the length-low byte and trailer. A marker follows on 0x86.

## Verified integrity, provisional body layout

All offsets below are zero-based, with Python end-exclusive slices.

| slice | interpretation | confidence |
|---|---|---|
| `[0:1]` | `90`, transport length-low byte | observed |
| `[1:21]` | proposed prefix/header | boundary provisional |
| `[21:141]` | ten 12-byte analysis cells | repetition supported, not ten proven objects |
| `[141:145]` | CRC-32/ISO-HDLC, little-endian, over `[1:141]` | verified |
| `[145:147]` | trailer, observed zero | outside CRC; universal padding not proved |

```python
crc_ok = int.from_bytes(record[141:145], "little") == zlib.crc32(record[1:141])
```

The original independent integrity audit passed 6,967/6,967 completed records across seven logs. The bundled samples independently reproduce **911/911 CRC matches**: 497 following and 414 excursion records. Run `python tools/check_structure.py` to reproduce this without private logs.

**Correction:** the earlier 15-byte prefix plus eleven A/B-pair interpretation included CRC and trailer as its last B block. Its occupancy counts and field correlations must not be treated as evidence about eleven objects. The older four-by-36-byte slicing also crosses the checksum boundary.

The working `[21:141]` projection puts a B-like half (`00fc0f00d0xx` empty motif) before an A-like half (`8403f4010000`). Co-occurrence supports it, but competing offsets also preserve repetition. `ars510/shell85.py` therefore exposes raw cells, not semantic objects or a `filled` validity flag. Cabana exports prefix, cells and CRC/trailer separately and requires a valid CRC.

## Raw prefix alignment

The two streams contain related clock-like codes and counters. In reassembled
records (including the length-low byte), the retained relationship is:

```python
counter80 = int.from_bytes(record80[5:7], "little") >> 1
counter85 = int.from_bytes(record85[5:7], "little") >> 1
coarse80 = int.from_bytes(record80[1:5], "little")
fine85 = int.from_bytes(record85[1:5], "little")
agrees = counter80 == counter85 and coarse80 == fine85 // 100
```

An expanded research-workspace audit finds 446,371 unique agreeing pairs across
28 drives, covering over 99.96% of ID80 records in each split with starts within
120 ms. A counter-shift control yields no matches. Choosing the nearest ID80
**start time** instead gives a different cycle for 31.42% / 36.60% / 37.16% of
pairs in discovery / confirmation / further drives. Use raw prefix agreement
when testing same-cycle relationships; nearby arrival times alone are ambiguous.

These are existing raw structural fields, **not confirmed acquisition timestamps**.
Clock units, epoch origin, body freshness and cell-to-object identity do not follow
from this test. The coarse code is quantized from the fine code and resets when
the latter wraps; do not unwrap it as an independent 32-bit timer. Record pairing
also does not imply both completed records were available at either start time.

Numbers are provenance-labelled imports from workspace SCR-149, not bundled
reruns; see [summary](../data/analysis/summaries/prefix_alignment.json). Runtime
object decoding and publication are unchanged.

## Important limits

- Changing prefix/CRC does not prove changing body measurements. An original-log counterexample had 995 distinct CRC-valid records across about 60 seconds with one identical 120-byte body while ID80 changed.
- No validated fixed mapping links these cells to ID80 physical objects. Establish identity and timing before using them as quality or geometry witnesses.
- Bounded correlation tests did not produce a usable confidence/correction decoder. They do not prove no such signal exists.
- The native ID80 object path does not require ID85 gating. This is not proof that ID85 lacks useful metadata.

Next useful tests are lifecycle-linked, CRC-clean and object-associated. A repeating motif alone does not establish a field's units, object count, freshness or validity.
