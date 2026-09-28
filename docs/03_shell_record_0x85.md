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

The lane-boundary finding below changes the next step: investigate road-boundary
lifecycle and remaining cell parameters before assuming object association. A
repeating motif alone does not establish units, freshness or validity.

## Lane-lateral-offset candidates (2026-09-27)

At least part of the body strongly resembles **road-boundary geometry**, rather
than a list of radar objects or reflections. For zero-based cells 2/3/8/9 in the
working `[21:141]` projection, a fixed diagnostic formula is:

```python
raw = (int.from_bytes(cell.payload, "little") >> 32) & 0xfff
y_left_m = (raw - 2000) * 0.01
```

Cells 2/8 usually follow the left ego-lane boundary, and 3/9 the right. This formula,
sign and assignment were frozen before comparing with camera lane-model values.
It was tested on 24,878 CRC-valid records from 25 predetermined segments in three
drive groups. All groups had prior research use for other questions. Selection
required nondefault-looking cells, speed at least 5 m/s, model lane probability at
least .8 and model/ego messages within 150 ms. Cells matching the default motif
`payload[6:10] == b"\x84\x03\xf4\x01"` are excluded; they can otherwise produce a misleading 0 m value.
That exclusion is **not a decoded validity flag**.

| drive group | cell 2 median error | cell 3 | cell 8 | cell 9 | fixed tests passed |
|---|---:|---:|---:|---:|---:|
| A (development) | .036 m | .096 m | .036 m | .095 m | 4/4 |
| B (transfer) | .033 m | .070 m | .030 m | .067 m | 4/4 |
| C (transfer) | .031 m | .065 m | .030 m | .063 m | 2/4 |

These numbers measure agreement with camera-model lane geometry, **not surveyed
physical accuracy**. Constant-position and 5 s time-shift controls give larger mean
errors in all 12 comparisons. The two right-side tests in group C nevertheless
fail the fixed within-segment correlation gate: .348 and .411 versus required .8.
All scores, coverage and gates are in the [machine-readable summary](../data/analysis/summaries/id85_lane_lateral_candidates.json).
These are provenance-labelled imports from research-workspace SCR-165, not reruns
from the bundled samples; repeated frames are not independent validation trials.

Review of 21 synchronized private road frames supports the boundary interpretation
on straight and curved roads and preserves counterexamples. During one lane
change, the right cells stay near the old boundary while the model changes its
ego-right assignment. Other large transients occur **without an obvious lane
change**. The largest model discrepancy is 3.744 m. A fixed cell is therefore not
an unconditional ego-lane boundary, and nondefault cells can still be wrong.

The transmitting ECU remains unknown: bus placement and prefix agreement with
ID80 do not prove these are radar-generated lane measurements. Camera/ADAS data
received or forwarded on this bus is another possibility. The complete record
is not proven lane-only, the duplicate-cell roles and remaining parameters are
unresolved, and no scan source or acquisition time follows from this finding.

This changes an earlier search assumption: activity when the ID80 object list is
empty need not represent otherwise-hidden reflections. Keep searching for Doppler
and quality metadata without treating all ten cells as object measurements.
The parser exposes raw cells and the structural marker below; no lane-control
output or object publication policy changes.

### Further-drive limits

The unchanged lateral formula and fixed cell assignments were tested on 16
additional predetermined segments from four further drives. Only **5 of 16**
drive/cell comparisons pass all the same gates. Eight comparisons fail coverage
(only two eligible segments per cell); several also fail numeric gates. The other
failures include left-side centered correlations of .406/.443 and a right-side
correlation of .747. Median errors are 2.3–22.4 cm, but the maximum is 4.042 m.
Thus the earlier left-side transfer success does not establish a universally
reliable left ego-boundary assignment.

Review of 12 additional private frames preserves a straight-road left-cell spike
without a lane change, turn-pocket boundary reassignment, and a night lane change.
Both sides can describe a different boundary or suffer a transient error.
The four further drives had prior use for other research, but their lane values
did not tune this test. These imported SCR-167 results and all 16 scores are
included in the [follow-up summary](../data/analysis/summaries/id85_parameter_presence.json).

## Nondefault parameter marker

Cell bit 30 is a supported structural availability code:

```python
parameters_present = bool(cell.payload[3] & 0x40)
# Also exposed as cell.parameters_present by ars510.shell85.
```

It equals `payload[6:10] != b"\x84\x03\xf4\x01"` in **4,466,850 / 4,466,850**
tested cells: all ten cell positions in 446,685 CRC-checked records across 28
drives. Counts are provenance-labelled imports from workspace SCR-168, not that
many independent physical detections. Both bundled samples reproduce the relation
in the test suite. Cabana exposes it as `PARAMETERS_PRESENT` alongside raw bytes.

When clear, `10|10` is always 1023 and `32|12` is always 2000 in this corpus.
However, 297 populated cells also have `32|12 == 2000`: a numerical lateral zero
is not an absence test. There are 24,829 clear and 24,832 set transitions within
continuous segment-local pairs; this is not a permanently fixed cell attribute.

**Presence is not accuracy or physical validity.** Of 229 further-drive samples
with lane-model disagreement above 1 m, 179 are more than one second from either
direction of an availability transition. A transition guard cannot explain all
large errors. The bit does not identify a fresh measurement, an ego-lane boundary,
a radar reflection, scan source, or originating ECU. Exact agreement with a default
block establishes a redundant encoding relationship, not independent correctness.
