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
| `20\|3` | 6 on 88-92% of settled rows; counts down about 5 -> 3 -> 2 -> 1 over the last records before deletion | missed-detection countdown |
| `107\|1` | about 0.02 in settled life, 0.5-0.66 just before deletion | coasting / not-measured flag |
| `224\|7`, `240\|7`, `248\|7` | scale with range or \|yRel\|; fall with age at fixed range (rho -0.29 to -0.75); larger when range steps are noisier; rise before deletion | range / velocity uncertainty |
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
- **Consumer weighting: open.** The uncertainty candidates might weight vRel and dRel in a consumer. That needs its
  own pre-registered test.

## The bit ledger

Every bit of the object slot was re-counted from raw records:
- 227-229 of 288 slot bits are live on each drive;
- 7 fields that the earlier bit map labelled constant do vary, among them `2|6` (the slot index, see
  [02](02_object_record_0x80.md)), `15|1`, `165|3`, `190|10` and `239|1`;
- 21 constant labels hold on all three drives.

The ledger is how "we have not missed anything" becomes checkable. Every field has a status, and unexplained live
fields are listed as such.

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
