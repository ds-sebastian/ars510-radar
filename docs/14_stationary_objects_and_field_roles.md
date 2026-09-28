# 14. Stationary objects, and likely roles for unnamed slot fields (2026-09-24)

Findings from the research workspace after [13](13_evidence_review.md). Figures come from 122 one-minute segments:
- drives A, B and C;
- the first and last segment of 21 further drives, which start or end on the owner's residential street, lined with
  parked cars.

Full inputs are not bundled. The key table is in
[`data/analysis/summaries/stationary_listing_rule.json`](../data/analysis/summaries/stationary_listing_rule.json).

## The object list leaves out stationary objects while you are moving

**Raw evidence, independent of any decoder choice.** In drive B, file B1 (log time 215-230 s), the car drives down
a street lined with parked cars and brakes to a stop sign:
- the 0x80 records arrive normally: 249 records, all CRC-valid, with wheel speed present on 0xB4;
- all 20 slots stay unallocated the whole time, both while moving and while stopped;
- the road camera shows the parked cars.

**The rule, from 4051 tracks.** Every new object starts at age 1 and is decided at about age 5 (0.3 s):
- 401 of the 653 objects that never moved end at exactly age 5;
- the decision depends on the object's own over-ground speed and on ego speed, not on closing speed.

Share of new objects that survive the age-5 decision, by the object's median \|over-ground speed\| over its first
5 records:

| ego speed | < 0.2 m/s | 0.2-0.4 m/s | >= 0.8 m/s |
|---|---|---|---|
| <= 2 m/s | 0.41-0.56 | 0.58-0.71 | 0.6-1.0 |
| 2-5 m/s | 0.34 | 0.67 | 0.57-1.0 |
| 5-10 m/s | 0.12 | 0.46 | 0.71-0.88 |
| > 10 m/s | 0.06-0.07 | 0.27-0.30 | 0.47-1.0 |

- Stationary objects that survive the decision above about 3 m/s do not last: none of them stays listed for 30
  records (2 s).
- Slow movers (0.7-3 m/s over ground: pedestrians, cyclists, creeping cars) are kept at every ego speed.
- **Objects first seen moving keep their track after they stop.** This is why stopped leads in queues are tracked
  through the stop.
- No other radar-bus message carries the missing objects in the B1 window:
  - 0x19x hold their no-target sentinels;
  - 0x235 / 0x237 / 0x23b carry only a 4-bit counter (16 distinct payloads, against 340-656 while objects are listed);
  - 0x190 / 0x239 vary the same way with and without objects (ego-speed-like);
  - 0x202, 0x24x and 0x680 are counters or status.
- The car bus (bus 0) was not searched.

Working rule: an object classed as stationary (over-ground speed below about 0.2-0.4 m/s) is deleted at about age
5 unless ego is below about 2 m/s. Whether the cut is fixed or scales with ego speed (to allow for noisier
ground-speed estimates at speed) cannot be separated yet. This behaviour is typical of ACC radars, whose object list
serves moving targets.

**Consequence for openpilot.** A vehicle that is already stopped when the radar first sees it will not appear in
the native object list while ego drives above about 3-5 m/s. Examples: a stalled car in lane, a parked car, the tail
of a queue that stopped before coming into range. As a second opinion to vision, this radar helps with leads it has
watched slow down and stop, not with those cases.

## Tests this rules out

- **Parked cars as ground truth.** Curbside parked cars were meant to give stationary truth at longer range and a
  gyro-based lateral scale. The radar does not list them, so the pre-registered test returned *unverified*. No radar
  metric was computed.
- **Doppler-selected stationary objects while moving.** No settled stationary track exists while ego > 2 m/s on
  any drive.
- **Stopped leads during your approach.** Selecting them by the velocity field would not bias a range-scale test
  against odometry. But only 3 qualifying runs exist on all drives (slopes 1.04-1.07, not a result), because leads
  usually stop together with ego.
- **Still possible:** a *parked* reflector session. While ego is stopped the radar does list some never-moving
  objects (for example 134 tracks on drive B). See [10](10_open_questions.md).

## Likely roles for unnamed slot fields

The published Continental ARS408 object list (class, size, rms uncertainties, existence probability, measurement
state) was used only as a hypothesis template. The decisions come from this radar's data, replicated with the same
sign on drives A, B and C. None is promoted to a named signal: units are not pinned, and the camera size reference
is coarse (40-79 tracks per drive, 3-8 trucks or buses).

| bits | behaviour on all three drives | candidate role |
|---|---|---|
| `20\|3` | 6 on 88-92% of settled rows; counts down about 5 -> 3 -> 2 -> 1 over the last records before deletion | upper bits of the byte-16 countdown; missed-detection meaning unproved (see below) |
| `107\|1` | about 0.02 in settled life, 0.5-0.66 just before deletion | coasting / not-measured flag |
| `224\|7`, `240\|7`, `248\|7` | scale with range or \|yRel\|; fall with age at fixed range (rho -0.29 to -0.75); larger when range steps are noisier; rise before deletion. `240\|7` also tracks vRel error against the camera (stratified AUC 0.62) | range / velocity uncertainty (`240\|7`: velocity) |
| `232\|7` | scales with \|yRel\|; falls with age at fixed range (rho -0.50 to -0.59) | lateral uncertainty |
| `264\|5` | falls with age at fixed range (rho -0.61 to -0.68); rises before deletion | uncertainty |
| `256\|5` | rises with age at fixed range (rho +0.86 to +0.90); drops about 1.5 codes before deletion | existence / confidence |
| `56\|7`, `216\|6`, `272\|5` | per-track medians follow camera vehicle height (partial rho 0.41-0.71 at fixed range) and are higher for trucks and buses (0.24-0.42); width follows on A and C | size, class or radar cross-section |

**What they do and do not buy:**

- **Track identity: no.** Across 29 camera-confirmed occlusions on B and C, `20|3` counts down and `107|1` switches
  on in lost and surviving tracks alike. Whether identity survives depends on the radar starting a new track near
  the predicted position, which no field of the dying track can supply.
- **vRel excursions: no clean flag.**
  - Mid-life dips of `20|3` (8-12% of settled rows) carry about 1.3x the share of \|vRel error\| > 2 m/s at
    30-100 m. That is weak.
  - `240|7` did not separate contradicted from confirmed braking episodes earlier ([08](08_dead_ends.md)).
- **Consumer weighting: tested (2026-09-24).** `240|7` is the one candidate that tracks velocity error.
  - It was checked on settled tracks paired with the camera's scale-based closing speed.
  - It is higher when native vRel and the camera disagree by more than 2 m/s: AUC 0.70 at 30-60 m, per drive 0.65,
    0.73 and 0.67.
  - The signal survives stratification by 5 m range bins, saturated age and drive: 0.62, and again 0.62 after
    regressing out range, age and ego speed.
  - The other candidates fall to about 0.5.
  - The decoder now exposes it as `vel_unc_code` (relative only).
  - A pre-registered test used it for confidence-weighted vRel smoothing (`vrel_smooth_unc_tau_s`). The result is in
    [06](06_known_limitations.md): it works as designed, but it moves along the same smoothing-versus-timing
    trade-off rather than breaking it.

## The bit ledger

Every bit of the object slot was re-counted from raw records:
- 227-229 of 288 slot bits are live on each drive;
- 7 fields that the earlier bit map labelled constant do vary, among them `2|6` (the slot index, see
  [02](02_object_record_0x80.md)), `15|1`, `165|3`, `190|10` and `239|1`;
- 21 constant labels hold on all three drives.

The ledger records the raw partitions tested so far and lists unexplained live
fields. It does not prove that those partitions match semantic boundaries, or
that a desired measurement is absent from the bus.

## Expanded-corpus raw-field corrections (2026-09-27)

A later audit of 399 segments, including 656,953 nondefault slots from CRC-valid
records, found 234 changing bit positions out of 288. These include the known
kinematics and lifecycle fields; they are not 234 unknown signals. Several old
constant labels and two raw-window boundaries needed correction.

| region | structural evidence | Cabana raw view |
|---|---|---|
| bit 256 onward | repeated 31↔32 steps: 25 in discovery, 17 in confirmation, 6 on further drives | `UNK_256_6` plus `UNK_262_2`; the previous five-bit view wrapped these steps |
| bit 264 onward | 199 / 126 / 98 unit steps across low-four-bit wraps in the same three sets, mostly 15↔16 | `UNK_264_5` plus `UNK_269_3`; bit 268 is not constant |
| `15`, `63`, `165`, `182`, `190`, `239` | rare changes, including within-track changes | `UNK_*` views replace constant or fixed-per-track labels |

The boundary follow-up used another 65 segments containing 109,577 slot rows on
further drives. Discovery and confirmation carry evidence for bit 256 spans six
and five routes respectively; the later carries occur on one route. The bit-264
wrap evidence spans all object-bearing routes in each set. Counts include any
multiple of the low-window modulus: the confirmation bit-264 count includes one
31→32 step. All-crossing counts are also retained in the summary, so large jumps
are not hidden by selecting successful unit steps.

**These are expanded raw inspection windows, not fully decoded quantities.**
Higher bits sometimes change too; complete field widths, units and meanings
remain open. The older scan/uncertainty and confidence associations above used
the stated low-bit windows. They do not establish a scan identifier or a physical
uncertainty scale for the complete quantity.

Bit 15 almost matches zero-range rows, but has 11 exceptions in each direction.
Bit 190 almost matches positive age, but has three exceptions. Neither is a new
validity gate. Bit 182 has only one short observed episode, so it cannot yet be
named as a merge, class or elevation flag.

Provenance-labelled aggregate evidence:
[`raw_field_corrections.json`](../data/analysis/summaries/raw_field_corrections.json).
The expanded raw corpus is not bundled in this repository; these counts are
imported research results, not results reproduced by the two bundled samples.
The historical reference bit map is preserved; the DBC generator applies explicit
corrections. No runtime kinematics, publication rules or control behavior changed.

## Rare tail and header states (2026-09-28)

A further retained drive contradicts two more historical constant labels. Its
186 source files add 184,492 complete object records and 392,005 nondefault slot
rows to the raw inventory. They are one previously researched drive, not 186
independent drives or a new holdout. All native records were independently
reassembled with their CRCs checked; byte histograms and saved witnesses were
also independently verified.

- **Slot bit 277:** set in four positive-age samples from three early track
  sequences, at ages 1 or 2. The complete slot byte at bits 272–279 reads 33,
  35, 35 and 37. All four have lateral sentinel code zero; their geometry is
  not a physical reference. `CONST_277_11` becomes `UNK_277_11` in the Cabana
  DBC. The evidence does not decide whether bit 277 extends the neighboring
  `272|5` quantity or is separate metadata. It is not a decoded size, SNR,
  elevation, merge or validity flag.
- **Header bit 111:** clear in two consecutive records before one observed
  fine-clock rollover. The historical `111|4` window reads 2 instead of its
  usual 3. `CONST_HDR111_4` becomes `UNK_HDR111_4`. This observation does not
  establish a timing unit, measurement age or a usable clock correction.

Both bit states were absent from the preceding 512-segment inventory. The
historical reference bit map remains frozen; generator corrections preserve
every raw bit without assigning a new physical meaning. Runtime kinematics and
publication rules are unchanged. The header's legacy `OBJECT_COUNT` comment
also now reflects the already documented allocation-count interpretation.

The aggregate counts in [`rare_raw_states.json`](../data/analysis/summaries/rare_raw_states.json)
are imported research evidence; the expanded captures are not bundled here.

## Rotating-frame kinematics and lateral acceleration (2026-09-27)

The previously unexplained `96|10` field now has a supported **lateral
ground-acceleration-like** interpretation. A useful candidate conversion is:

```
candidate_ay_mps2 = (raw_96_10 - 511) * 0.05
```

The scale remains provisional. Cabana continues to expose the raw code, and the
openpilot interface does not use it.

The key was accounting for the radar's rotating coordinate frame. With x forward,
y left and positive left yaw rate `omega`, ground lateral velocity is
`Vy = dy/dt + omega*x`, and ground lateral acceleration is
`Ay = dVy/dt + omega*Vx`. Omitting the second term makes the field look poorly
related to lateral motion, especially while cornering.

The test uses approximately two-second settled track windows below 60 m, fresh
IMU-derived yaw and native velocity fields. Discovery selected a coarse +0.5 s
lag, meaning the field follows the kinematic reference. The .05 scale and lag
were then applied unchanged to confirmation and further drives:

| evidence set | windows | fitted scale | correlation | RMSE using fixed .05 |
|---|---:|---:|---:|---:|
| discovery | 1,474 | .0513 | .924 | .224 m/s² |
| confirmation | 622 | .0486 | .884 | .282 m/s² |
| further drives | 225 | .0505 | .899 | .232 m/s² |

Removing the ego vehicle's own lateral acceleration still leaves correlations
.840/.783/.829, supporting an object-specific relationship. Zero-lag and
common-support lag results are both preserved in
[`rotating_kinematics.json`](../data/analysis/summaries/rotating_kinematics.json).
These are provenance-labelled research-workspace results; the expanded corpus
is not bundled here.

Limits matter: this is internal kinematic consistency with ego-motion input,
not independent target-acceleration ground truth. It uses the provisional .15
lateral-velocity scale. Some route-specific fits differ substantially, and the
two-second analysis does not establish exact measurement latency. The evidence
supports a filtered acceleration-like quantity; it does not establish an early
velocity-excursion flag.

Rotation correction also strengthens `74|10` lateral velocity: pooled fitted
scales are .1422/.1444/.1454 across discovery/confirmation/further drives, close
to the existing nominal .15. A discovery-route exception still fails the stated
common-scale criterion, so its calibration remains provisional.

One research-input correction: `carState.yawRate` was zero throughout this atlas
and cannot establish straight driving. These tests use fresh `livePose` angular
velocity. Earlier circular-code candidates were rechecked with that yaw source;
none acquired a verified Doppler interpretation.

## Related radars as hypothesis templates

Three published Continental interfaces were used to generate hypotheses. The decisions still come from this radar's data:

- **Tesla's Continental ARS4-B object list** (opendbc `generator/tesla/_radar_common.py`):
  - LongDist 12 bits at 1/16 m, the same scale as `32|12`;
  - ProbExist 5 bits, LongAccel 10 bits at 0.03125 m/s^2, LatSpeed 10 bits at 0.125 m/s;
  - Length and dZ 6 bits each; position / velocity / accel sigmas 6 bits each;
  - MovingState 2 bits (indeterminate / moving / stopped / standing), Class 3 bits.
- **ARS548 RDI** (Ethernet; [arXiv 2404.04589](https://arxiv.org/abs/2404.04589), appendix A):
  - per-object measurement status and movement status;
  - position, velocity and acceleration with std and covariance;
  - existence probability, class probabilities, length / width;
  - a status message that says whether the car's speed and yaw inputs are OK or timed out, plus blockage status.
- **ARS408** (public CAN protocol, e.g. tier4 `ars408_driver`): an object list *and* a separate cluster (detection) list, DynProp movement states, MeasState, ProbOfExist and 5-bit rms fields.

Each hypothesis was then tested properly:
- values derived on drives A, B and C;
- pass criteria written down before scoring;
- round 1 on the 40 route-endpoint segments;
- round 2, with revised definitions, on 12 mid-route segments from other drives that had not been used for anything.

| bits | derived on A / B / C | round 1 (endpoints) | round 2 (unseen mid-route) | outcome |
|---|---|---|---|---|
| `109\|2` movement state | 0 -> moving 99.7-99.9%; 2 -> oncoming 99.0-99.7%; 1 / 3 -> slow 59-87% | fail: with a 2 m/s "moving" cut, 0 -> moving only 80% (slow residential traffic moves at 0.5-2 m/s) | pass: 0 -> over-ground speed > 0.5 m/s on 99.65%; 2 -> < -0.5 m/s on 99.88%; 1 / 3 -> \|v\| < 2 m/s on 89.5% | **named `MOVE_STATE`** in the DBCs and decoder: 0 moving away, 2 moving toward, 1 / 3 not clearly moving (1 vs 3 unresolved) |
| `14\|1` oncoming flag | 1 -> oncoming 96-98% | fail: 1 -> currently oncoming only 74.5%; the flag stays on after an oncoming object slows | pass: 1 -> over-ground speed < 0 on 100%; 88.5% of objects approaching faster than 2 m/s flagged | **named `ONCOMING_FLAG`** (oncoming now or earlier) |
| `74\|10` lateral velocity scale | 0.147 / 0.131 / 0.135 m/s per code (pooled 0.1365) | unverified: 15 windows | unverified: 23 windows, 0.097 (CI 0.073-0.117) | **not pinned**; sign confirmed; 0.15 kept as a placeholder (openpilot does not use it) |
| `84\|10` accel scale | 0.041 / 0.051 / 0.030 m/s^2 per code at 0.5 s lag, CIs do not overlap | 0.110 | 0.040 | report only: about 0.04 on most data but drive-dependent; stays in centred codes |

The round-1 failures are recorded; round 2 used new data and revised definitions written down before scoring. Numbers: [`data/analysis/summaries/template_field_tests.json`](../data/analysis/summaries/template_field_tests.json).
The labels come from the radar's own over-ground velocity. So `MOVE_STATE` and `ONCOMING_FLAG` are shown to agree
with the radar's motion estimate, which is what their names claim; they are not checked against independent truth.

**0x85 is active when the object list is empty.** In the B1 parked-car stretch above:
- 0x85 carries about 4 filled cells per record;
- the cell bodies change every record while ego moves (83 distinct per 5 s) and much less once it stops (18 per 5 s);
- that fits a detection, cluster or stationary-object list, which is how ARS408 pairs clusters with objects;
- no cell bit window yet keeps a fixed codes-per-metre relation with ego travel across cells and records;
- no cell window (8-16 bits, signed or unsigned) tracks ego speed the way a stationary detection's radial velocity would (|r| <= 0.32 on 7 files);
- cells matched on index plus bytes 2-3 show no window that moves with ego travel (|r| <= 0.14);
- so 0x85 is scene-dependent but not a plain range / radial-velocity detection list. The encoding stays open ([10](10_open_questions.md)).

## Coarse nonnegative velocity heading (2026-09-27)

`208|6` closely follows the direction of the radar's ground-velocity vector,
with an important limitation: negative angles almost always produce zero.
An empirical prediction for the raw code is:

```
clip(floor(max(atan2(Vy, Vx), 0) * 64/pi), 0, 63)
```

This suggests bins of approximately pi/64 radians (2.8125 degrees). It is not
a recovered firmware formula. `Vx` and `Vy` use the native velocity fields;
this provides internal consistency evidence, not independent body-heading truth.
The field is not elevation, an independent Doppler measurement, or a jitter flag.

| evidence set | eligible rows | exact raw-code match | within one code |
|---|---:|---:|---:|
| discovery | 103,794 | 98.18% | 99.60% |
| confirmation | 40,892 | 97.43% | 99.44% |
| further drives | 25,057 | 98.34% | 99.71% |

Eligibility requires settled tracks, 5–60 m forward range, lateral position
within 20 m and native ground speed at least 5 m/s. Many rows have zero codes.
On leftward-moving rows with motion-axis angle magnitude at least .08 radians,
exact agreement is 81.90/81.42/80.87%, and one-bin agreement is
94.05/94.63/95.94%. Position bearing is a much poorer explanation.

Among 43,369/16,320/8,724 rightward-moving rows, only 11/1/4 have a nonzero code.
**Zero must not be interpreted as proof of straight motion.** Oncoming objects
with positive lateral velocity have codes approaching 63, consistent with angles
approaching pi. Some large counterexamples remain. Clipping, internal filtering
and field validity are not fully explained.

The candidate was identified in discovery and checked on the other sets; the
final quadrant interpretation followed those checks and is explicitly
exploratory. It has no pristine holdout. The raw `UNK_208_6` decoder is retained,
with no runtime use or control change. Imported research aggregates, not a
bundled rerun: [`velocity_heading.json`](../data/analysis/summaries/velocity_heading.json).


## Full movement code (2026-09-27)

**Correction:** the historical `109|2` view is too narrow to distinguish the
observed motion classifications. The full raw `109|3` code takes values
0, 1, 2, 3, 4, 5 and 7 on 762,474 allocated samples; 6 was not observed.
The decoder exposes `NativeObject.movement_code`. Its existing `move_state`
attribute and Cabana `MOVE_STATE` remain the legacy low-two-bit projection.
To inspect the full code in the current Cabana layout, combine
`MOVE_STATE | ((UNK_111_4 & 1) << 2)`; remaining bits of that raw window are
separate unknowns. Old labels and statistics describe the coarse projection.

| full code | supported behavior | interpretation limit |
|---|---|---|
| 0 | predominantly positive longitudinal ground velocity | forward-motion-like; legacy 0 also includes full 4 |
| 1 | predominantly slow | stationary-like; low-bit 1 also includes full 5 |
| 2 | predominantly negative longitudinal ground velocity | oncoming-like; unseen full 6 must remain representable |
| 3 | nominal lateral velocity below −0.15 m/s on all 393 mature samples | rightward-motion-like; one clear crossing vehicle in video, but other events have uncertain association |
| 4 | nominal lateral velocity above +0.15 m/s on 600/602 mature samples | leftward-motion-like; turning ego coordinates and classification lag matter |
| 5 | all 48,044 observed age-1 through age-3 samples; also some mature objects | initialization/unsettled-like, not simply a birth flag or a decoded invalid state |
| 7 | all 81 slow endpoints following the earlier study's mature-motion antecedent | stopped-after-motion-like; does not prove the converse or instantaneous zero speed |

Full 3 and 7 previously both appeared as coarse 3; full 4 aliased forward 0;
full 5 aliased slow 1. This explains why naming the low-bit states was incomplete.
The broader discovery was exploratory and used previously studied datasets,
not a new pre-registered semantic validation. Native velocities are internal
witnesses, not ground truth. A separate position-plus-ego-yaw direction check
agrees on 91/103 selected allocation/state windows, with counterexamples retained.
Video includes a clear rightward crossing, plus curved-road, night and ambiguous
cases. These are descriptions of the radar's classifier, not guaranteed physical
motion, scan source or an early excursion warning. No velocity or control policy
changes with this metadata addition.

Aggregate values are provenance-labelled imports from workspace SCR-158, not
bundled reruns; see [summary](../data/analysis/summaries/full_movement_code.json).
The helper preserves all eight raw values, including the currently unseen 6.


## Startup decay and the historical six-bit window (2026-09-27)

The historical `8|6` window should not be described simply as a quantity that
ramps upward with age. Its lower five bits follow an exact startup sequence,
while bit 13 sometimes changes separately. The native decoder now exposes
`raw8_low5` and `raw13_bit`; both remain raw values with unknown physical meaning.
The Cabana `UNK_8_6` view is retained: `low5 = value & 31`, `bit13 = value >> 5`.
No control policy, geometry, velocity, publication or validity rule changes.

For a continuous allocation observed from age 1, **only until the first full
movement code `109|3` other than 5**, the lower code is:

```text
q(age) = min(30, floor(31 * (2/3)^max(age - 4, 0)))
```

Thus ages 1..4 yield 30, followed by 20, 13, 9, 6, 4, 2, 1, 1, 0. This is consistent with
fractional decay before output quantization; a lookup table or another equivalent
implementation cannot be distinguished from these observations. Rounding the
previous transmitted code as though it were the complete internal state misses
the repeated 1. Do not infer a calibrated probability or an ECU implementation.

The frozen formula matches **134,217/134,217 startup samples** across 24 routes
and 16,526 contiguous allocations: 76,022 development, 37,692 confirmation and
20,503 further-drive samples. Of these, 73,024 are after age 4, so this is not merely
an initialization-constant match. Every observed route passes. The formula was
selected on development evidence; other partitions had been used in earlier
research and are not globally pristine. Missing birth observations, re-entry to
code 5, other movement codes and mature semantics are outside this exact claim.

Across 762,474 positive-age samples, low code 31 is unobserved and bit 13 is clear
on 226 samples. There are 182 continuous transitions toggling bit 13, 147 of them
changing the historical six-bit value by exactly 32 without changing its low
code. No 31/32 carry was observed. All 14 startup exceptions to the whole-six-bit
formula `32 + q(age)` are explained by bit 13 being clear. This supports exposing
the two raw parts separately; it does not identify the bit's function or prove
that code 31 is reserved in every possible radar mode.

The bit is not the missing excursion warning in the tested cohort: it stays set
from 3 s before through 1 s after all 34 labelled excursions and 29 real closings.
Labels and target identity remain imperfect. Startup structure does not prove
measured-this-cycle status, SNR, false-detection probability or raw Doppler.

Provenance-labelled aggregate evidence is in
[`startup_low5_decay.json`](../data/analysis/summaries/startup_low5_decay.json).
These full-route research results are imported summaries, not bundled reruns;
public tests check raw extraction and neighboring-field independence.

## Three-component weight candidates (2026-09-27)

The adjacent nibbles `148|4`, `152|4`, `156|4` form a nearly normalized triplet.
The decoder exposes the raw tuple as `NativeObject.raw_weights148`. Cabana keeps
its existing non-overlapping raw layout: extract the first two components from
`UNK_148_8` as `value & 15` and `value >> 4`; the third is `UNK_156_4`.
Updated comments explain why the combined `148|8` integer is not one component.

A fixed structural test passed on development, confirmation and further drives:

| group | positive-age slots | nonzero triplets | mixed triplets | one-count transfers | sum outside 15/16 |
|---|---:|---:|---:|---:|---:|
| Development | 451,970 | 110,778 | 3,546 | 1,137 | 0 |
| Confirmation | 201,646 | 49,783 | 1,570 | 542 | 2 |
| Further drives | 108,858 | 30,592 | 826 | 320 | 0 |

Mixed triplets contain a component between 1 and 14. A transfer moves one count
between two components while preserving the sum and the third component, within
a continuous slot lifetime. These occur on all 24 routes with positive-age
objects, supporting more than a collection of one-hot flags.

Of 191,153 nonzero triplets, 191,151 sum to 15 or 16. The two exceptions are
`(7, 1, 6)` and `(10, 1, 3)`, both summing to 14. All nine observations with three
nonzero components and every exception remain in the research evidence. The
pattern is compatible with quantized weights, but does not establish a unique
quantizer or justify dividing by 15 or 16 to publish calibrated probabilities.

**Follow-up: lateral-position associations (2026-09-28).** A fixed mapping chosen
on development data transfers to confirmation and further drives:

| raw component | supported association |
|---|---|
| `148\|4` | right |
| `152\|4` | left |
| `156\|4` | central |

The test includes mature slots (age at least 60), range 5–120 m, and a unique
dominant component of at least 12. Reference categories use native lateral
position: at most −2.5 m, within ±1.5 m, or at least +2.5 m. Intermediate bands
are excluded. The mapping and thresholds were frozen before transfer scoring.

| group | eligible rows | mean recall across three classes | agreement |
|---|---:|---:|---:|
| Development | 78,807 | 98.26% | 98.66% |
| Confirmation | 31,948 | 98.42% | 98.50% |
| Further drives | 20,197 | 98.14% | 99.17% |

All per-class precision/recall and support gates pass. This is not exact:
1,701 eligible rows disagree. Of 384,328 mature, range-eligible rows, 249,429
have zero triplets and are not assigned a category. The corresponding fixed
interpretation as instantaneous lateral-motion directions fails all three groups.

A camera-bearing check agrees on 22,399 of 22,665 eligible observations across
drives A, B and C; nine inspected examples show boxed vehicles in the corresponding
right, left or ego lanes. **This witness is only partially independent:** its
metric conversion uses radar range, and its existing object pairing selects by
azimuth agreement. It corroborates lateral placement but does not independently
establish radar target identity or metric accuracy.

**Exact lane semantics remain unresolved.** The test does not distinguish
radar-frame lateral bands from road-relative lane membership on curves, validate
soft weights as probabilities, or explain the zero triplet. Do not use this
candidate as a lane gate. Curved-road and lane-change cases where coordinate
systems disagree are the next necessary witnesses.

These are not decoded SNR, false-detection probabilities, scan-source weights,
merge indicators or measurement validity. All possible raw triplets are preserved,
including values outside the observed sum pattern; no normalization or rejection
is performed. The interface's radar points and control policy do not use them.

They are not a demonstrated early excursion discriminator. Any nonzero triplet
appears in 18/20 development excursions but also 10/16 real closings; transfer
results are similarly nonspecific. Mixed triplets appear in only 2/9 confirmation
excursions and 1/5 further-drive excursions. The label windows cover three seconds
before through one second after a disagreement trigger, not independently proven
physical onset. Earlier research used all these drive groups.

[Machine-readable summary](../data/analysis/summaries/midband_weight_triplet.json)
contains provenance-labelled imports from workspace SCR-177, not bundled full-route
reruns. Public tests check raw preservation and independence from neighboring fields.
The [lateral-role summary](../data/analysis/summaries/weight_lateral_roles.json)
contains provenance-labelled SCR-178 aggregates; private camera frames and full
route inputs are not bundled. No decoder values or control behavior changed.

## Raw weight-state view (2026-09-28)

`NativeObject.raw_weight_state128` exposes the three-bit raw view `128|3`.
It combines Cabana's existing `UNK_128_2 | (UNK_130_1 << 2)` without changing
the DBC's non-overlapping layout. A discovery-selected code mapping transfers
with **zero exceptions across 762,474 positive-age slot observations**:

| observed code | weight tuple | dominant-component association |
|---|---|---|
| 2 | nonzero | usually 148, right-associated |
| 3 | nonzero | usually 156, central-associated |
| 4 | nonzero | usually 152, left-associated |
| 1, 5, 7 | all zero | physical meanings unresolved |
| 0, 6 | unobserved in this cohort | preserve if encountered |

There are 191,153 nonzero tuples. On the 191,122 with a unique largest component,
the code/category mapping agrees 190,414 times and disagrees 708 times. Each code
passes the fixed 99% agreement gate in development, confirmation and further
groups; ties and strong-weight counterexamples remain. **The raw state is not
an exact replacement for the weights.** Exact lane roles remain unproved.

Availability is not solely record-wide: 17,585 records contain mature objects
with both populated and zero tuples within the fixed near-corridor selection.
In 3,434 continuous record pairs, one eligible object changes availability while
another remains stable. A shared necessary enable plus object-specific eligibility
is still possible; the relation does not identify the source ECU.

The decoder preserves all eight codes and every weight combination, including
unseen or contradictory values. It does not normalize, invalidate or filter
objects using this metadata. Codes 1/5/7 are not decoded false-detection, lane-
exclusion or measurement-validity states. State changes and state/weight conflicts
have not supplied a transferable early excursion guard.

The [machine-readable summary](../data/analysis/summaries/weight_state128.json)
contains provenance-labelled aggregate imports from workspace SCR-181/182,
not bundled full-route reruns. All drive groups had prior research use.

## State-2 score countdown (2026-09-28)

The full raw byte `16|8` has a transferable arithmetic structure: on consecutive
mature updates whose current `0|2` state is 2, it decreases by **exactly 1 or 20**.

| group | state-2 updates | decrement 1 | decrement 20 | exceptions |
|---|---:|---:|---:|---:|
| development | 3,676 | 902 | 2,774 | 0 |
| confirmation | 1,907 | 534 | 1,373 | 0 |
| further drives | 747 | 49 | 698 | 0 |

The scope is same-slot updates with both ages 60–126, 30–90 ms apart, and a
one-step native record-counter increment. Startup and retirement are outside
this claim. The familiar `20|3` sequence 6→5→3→2→1 is the upper portion of the
byte sequence 100→80→60→40→20; it is not established as a separate missed-scan
counter.

**The choice of decrement remains unresolved.** A proposed rule using bit 107
and a threshold of 40 fails on 64 development updates. Only the narrower
one-or-twenty relation passed the frozen transfer gates. State 1 can also show
these decrements, so the relation cannot be reversed into a state classifier.

This is metadata arithmetic, not a calibrated probability, proof of measurement
absence, or an early velocity-excursion warning. Preserve the received values;
no decoder, validity or control behavior changes follow.

The [aggregate summary](../data/analysis/summaries/score16_countdown.json) imports
workspace SCR-189 evidence with provenance labels. Full-route captures are not
bundled reruns, and all groups had prior research use.

### What happens on the next update

A frozen follow-up tests a narrower current-time pattern: state 2, previous
score at most 40, current bit107 clear, and decrement 20. It often precedes
**allocation removal on the next complete record**:

| group | pattern occurrences | next-record removals | fraction | share of all eligible removals detected |
|---|---:|---:|---:|---:|
| development | 63 | 54 | 85.7% | 8.4% |
| confirmation | 35 | 30 | 85.7% | 9.5% |
| further drives | 17 | 14 | 82.4% | 9.0% |

Removal means explicit age zero or an exact idle slot, inferred from the
complete-record atlas contract. It does not establish physical disappearance.
All pattern occurrences have next-record coverage. **Seventeen allocations
survive**, and one small further-drive group has zero removals in two cases.
The pattern passes its frozen transfer gates but detects only a small minority
of removals. These are observed cohort fractions, not calibrated probabilities.

Exact-score fast/slow comparisons have no supported strata, so this does not
establish an effect independent of score. Returning from state 2 to state 1
also does not guarantee score restoration: the score decreases in 249/1,041,
111/454 and 39/216 continuing transitions across the three groups.

This adds a bounded lifecycle association, with no measurement-validity,
false-detection probability, scan-source or excursion-warning interpretation.
No filtering or decoder behavior changes. The [outcome summary](../data/analysis/summaries/score16_outcomes.json)
imports anonymized SCR-192 aggregates; full captures are not bundled reruns,
and all groups had prior research use.

## Categorical recoding and the low nibble at 136 (2026-09-28)

Two disjoint three-bit views carry the same observed category through a fixed
recoding. The adjacent `136|4` changes independently:

| `163|3` | `140|3` |
|---|---|
| 1 | 0 |
| 2 | 5 |
| 3 | 7 |
| 4 | 1 |
| 5 | 3 |
| 6 | 4 |

The dictionary was found on development captures, then frozen. It has **zero
exceptions across 1,253,081 non-idle slot rows in 698 segments**, including
retiring age-zero payloads. All five provenance groups reproduce it; two groups
contain only five of the six categories. Codes 0/7 at163 and2/6 at140 were not
observed, so they have no inferred mapping or prohibition.

On exact same-slot native edges, the lower nibble changes alone 75,524 times in
development and 114,075 in pooled transfer; the upper category changes alone
3,302 and 4,215 times respectively. No unit carry crosses the nibble boundary.
This supports separate raw views rather than interpreting the old `136|6` plus
bit142 as a calibrated scalar. It does not establish the lower nibble's units.

Independent byte decoding checks the complete atlas and its input hashes.
Native sequence/CRC checks verify 28 category witnesses and 334,800 raw slots
(including idle slots) from 16,740 valid records. One malformed sequence and
eight incomplete records are excluded from that native check. A separate test
checks the dictionary on all18,220slots in the bundled samples.

**Physical class labels remain unresolved.** Earlier car/heavy naming had real
counterexamples; recoding the same information does not repair that classifier.
Likewise, the lower nibble is not yet calibrated confidence, detection probability
or scan history. No Doppler, SNR, elevation or excursion discriminator follows.

Cabana now exposes `UNK_136_4`, `UNK_140_3`, full `UNK_163_3` and remaining
`UNK_166_2`, preserving every raw bit. Both categorical values remain independently
visible; nothing synthesizes one from the other or rejects future disagreements.
Decoder kinematics, interface behavior and control gates are unchanged.
The [machine-readable summary](../data/analysis/summaries/attribute_recoding.json)
labels imported workspace evidence separately from the bundled fixture check.
