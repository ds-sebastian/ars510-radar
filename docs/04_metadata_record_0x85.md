# 04. The metadata record (0x85)

0x85 carries a second segmented record at the radar cycle rate. The first frame starts `10 90`; keeping bytes 1..7 of
each of 21 frames gives **147 bytes**. A fixed marker follows on 0x86.

## Layout

| bytes (Python slice) | content | conf. |
|---|---|---|
| `[0:1]` | `90`, transport length-low byte | ● |
| `[1:21]` | prefix: fine clock (bytes 1-4, LE), counter (bytes 5-6 >> 1), other raw bytes | ● clock and counter |
| `[21:141]` | **ten 12-byte cells** | ◐ |
| `[141:145]` | CRC-32/ISO-HDLC, little-endian, over `[1:141]` | ● |
| `[145:147]` | trailer, zero | ● |

```python
crc_ok = int.from_bytes(record[141:145], "little") == zlib.crc32(record[1:141])
```

911 / 911 bundled records and 6,967 / 6,967 records across seven full logs pass. `python tools/check_structure.py`
reproduces the check on the bundled samples. `ars510/shell85.py` returns the prefix and the ten raw cells.

## Pairing with the object list

The 0x85 prefix and the 0x80 header share a clock and a record counter:

```python
counter80 = int.from_bytes(record80[5:7], "little") >> 1
counter85 = int.from_bytes(record85[5:7], "little") >> 1
same_cycle = counter80 == counter85 and int.from_bytes(record80[1:5], "little") == int.from_bytes(record85[1:5], "little") // 100
```

This matches 446,371 record pairs across 28 drives, over 99.96% of 0x80 records. Nearest arrival time picks the
neighbouring cycle about a third of the time, so pair by counter.

## Cells

Each cell holds a default block `84 03 F4 01` at payload bytes 6-9 when empty. **Cell bit 30** says whether the
cell holds parameters:

```python
parameters_present = bool(cell.payload[3] & 0x40)   # also ShellCell.parameters_present
```

It equals `payload[6:10] != b"\x84\x03\xf4\x01"` in all 4,466,850 tested cells. The cells change every record while
ego moves, also when the object list is empty.

### Lane-boundary cells

Cells 2 / 3 / 8 / 9 carry **lateral offsets of the lane boundaries** around the ego lane:

```python
raw = (int.from_bytes(cell.payload, "little") >> 32) & 0xfff
y_left_m = (raw - 2000) * 0.01
```

Cells 2 / 8 usually follow the left ego-lane boundary and 3 / 9 the right one. Against openpilot's lane model, the
median error is 3-10 cm:

| drive group | cell 2 | cell 3 | cell 8 | cell 9 |
|---|---|---|---|---|
| A | 0.036 m | 0.096 m | 0.036 m | 0.095 m |
| B | 0.033 m | 0.070 m | 0.030 m | 0.067 m |
| C | 0.031 m | 0.065 m | 0.030 m | 0.063 m |

*24,878 CRC-valid records from 25 segments, speed ≥ 5 m/s, lane probability ≥ 0.8, cells with parameters present
([summary](../data/analysis/summaries/id85_lane_lateral_candidates.json)).*

The assignment follows boundaries rather than being fixed to one: during a lane change or at a turn pocket a cell
can keep describing the old or a different boundary for a while, and single-cycle spikes of a few metres occur.
Treat a cell as "a nearby boundary", not "the ego lane's left edge".

The other cells (0, 1, 4-7) hold further road-geometry parameters. Cells 6 and 7 are candidates for road-edge offsets
(they follow openpilot's road-edge estimate within a drive).

### Road-direction association: bits 64-79

The raw word in **bits 64-79** (`64|16`) has a **◐ road-curvature association** in cells 2 / 3 / 8;
its physical angle or offset interpretation is **○ candidate**. A little-endian two's-complement view is useful
for the rank comparison below. It is an analysis view, rather than a decoded numeric format. The reference is the
car's own path over the next 60 m (gyro and wheel speed), expressed in the current radar frame, independent of the
camera.

| | cell 2 | cell 3 | cell 8 | cell 9 |
|---|---|---|---|---|
| Spearman ρ with κ (three drive partitions) | 0.64 / 0.54 / 0.66 | 0.61 / 0.55 / 0.63 | 0.59 / 0.51 / 0.60 | 0.55 / 0.49 / 0.57 |

Numbers: [`decode_references.json`](../data/analysis/summaries/decode_references.json).

**Keep this word in raw code units.** In 18,448 adjacent cell pairs around 135 motion-selected curve entries,
3,997 signed-view steps exceed 20,000 codes, each with a high-bit sign change. The median step is 32,768 codes,
while the lower 15 bits change by a median 18 codes and the future ego-path heading at 16 m changes by a median
0.00118 rad. Cells 2 / 3 alone have 279 such steps across 12 drives with lower-bit changes ≤ 128 codes,
heading changes ≤ 0.005 rad and offset-code changes ≤ 5. The word therefore requires an encoding and boundary
reference before assigning an angular scale or a lookahead distance. The lower-bit view is structural only;
the ego path does not certify which boundary the radar selected.

![Raw word and measured future ego path](img/analysis/id85_direction_code_structure.png)

*A cell-2 high-bit transition checked against original CRC-valid records. The lower 15 bits are shown as raw
structure, not as a decoded angle. Counts, limits and the relative-time example:
[`id85_direction_code_structure.json`](../data/analysis/summaries/id85_direction_code_structure.json).*

**For in-path decisions, use the yaw-rate path.** To decide whether an object 30-100 m ahead is in the ego lane,
the car's own curvature, y(x) = (yaw rate / v) · x² / 2 with the yaw rate from Toyota 0x24, is scored against the path
the car later drove:
- it classifies 92.6% of objects correctly, against 84.5% for a straight |yRel| window;
- missed in-lane objects drop from 26% to 11%, and at 60-100 m accuracy rises from 82% to 88%;
- adding the raw signed-word view leaves accuracy at 92.5%.

Numbers: `in_path_prediction` in [`decode_references.json`](../data/analysis/summaries/decode_references.json).
