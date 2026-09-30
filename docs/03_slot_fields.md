# 03. Slot fields: what every bit of an object means

![slot field map](img/analysis/field_map.png)

Each 36-byte slot is **one little-endian bit field**: bit 0 is the LSB of slot byte 0, bit 8 the LSB of byte 1, and so
on. A field `start|len` is

```python
(int.from_bytes(slot, "little") >> start) & ((1 << len) - 1)
```

In a DBC that is Intel `start|len@1+` on the slot bytes. Most numeric fields are **offset binary** (zero near
the middle of the code range).

**Confidence:** ● confirmed (exact rule or replicated on held-out drives) · ◐ likely (consistent structure and
physics, scale or name still being pinned) · ○ candidate (a leading interpretation with supporting patterns).

The layout matches Continental's generic ARS object list (kinematics with standard deviations, class and dimensions,
lifecycle and maintenance state, existence probability). That template guided the naming; every decision below comes
from this radar's own data.

## Kinematics

| bits | field | decode | conf. |
|---|---|---|---|
| `32\|12` | **dRel**, forward distance from the radar | `(code − 160) / 16` m | ● field/scale; ◐ physical zero |
| `44\|12` | **yRel**, lateral, left positive | `(code − 2048) / 64` m; \|code − 2048\| ≥ 2000 is a sentinel | ● sign, ◐ scale (±10%) |
| `64\|10` | **vx over ground** | nominal `(code − 510.5) × 0.15` m/s; vRel = vx − v_ego | ● ground-speed interpretation; ◐ exact zero/scale |
| `74\|10` | **vy over ground**, left positive | `(code − 510.5) × ~0.145` m/s | ◐ |
| `84\|10` | **ax over ground**, filtered | `(code − 511) × ~0.04` m/s²; follows vx by 0.5-1 s | ◐ |
| `96\|10` | **ay over ground**, filtered | `(code − 511) × 0.05` m/s²; follows the kinematic value by ~0.5 s | ◐ |
| `208\|6` | **heading-like angle output** | empirical clipped velocity-angle relationship, approximately π/64 rad per code | ◐ |

- **The velocity is over ground**, not relative: traffic sits on the ego-speed diagonal, parked objects on 0 and
  oncoming traffic on −v_ego.

  ![over ground](img/analysis/vground_vs_ego.png)

- **Lateral motion and acceleration live in the radar's rotating frame.** With yaw rate ω (left positive):
  `vy = dy/dt + ω·x` and `ay = dvy/dt + ω·vx`. With that correction, `74|10` fits 0.142-0.145 m/s per code on
  three drive groups, and `96|10` tracks lateral acceleration at r = 0.92 / 0.88 / 0.90 (development / confirmation /
  further drives), 0.84 / 0.78 / 0.83 after removing ego's own lateral acceleration.
- **Heading-like angle** matches `floor(max(atan2(vy, vx), 0) × 64 / π)` exactly on 98.2% of the original
  settled moving samples (99.6% within one code). Negative angles generally read 0 and oncoming motion reads near
  63. This is an empirical relationship; angle outputs can change while both published velocity codes remain
  unchanged. Three original-CAN-verified mature examples have angle changes 0→4, 62→28 and 0→14 with component
  codes held constant. A 700-segment census retains discrepancies under ±1-code input allowances, independent
  component units of .14–.16 m/s/code and an angle interval covering round/floor interpretations. Confirmation
  has 268 incompatible mature-moving rows among 60,029; further drives have 196 among 35,778. These declared
  allowances are not factory calibration bounds. Input precision/calibration, initialization, timing and
  filtering remain possible sources of the difference; the field does not independently certify physical
  direction or a fixed delay. Clipped 0/near63 changes need not represent a physical half-turn.
  Counts and definitions: [`heading_component_bins.json`](../data/analysis/summaries/heading_component_bins.json).

  ![heading](img/analysis/heading_field.png)

  ![angle and published component updates](img/analysis/heading_component_updates.png)

Scales and accuracy are in [06](06_accuracy.md).

## Lifecycle and confidence

| bits | field | decode | conf. |
|---|---|---|---|
| `0\|2` | **state** | 1 measured this cycle, 2 predicted (coasting); 0 rare | ◐ |
| `2\|6` | **slot index** | 0-19 = this slot's position; 63 = unallocated | ● |
| `8\|5` | **startup code** | `min(30, floor(31 × (2/3)^max(age − 4, 0)))` while the motion code is 5 | ● |
| `13\|1` | flag next to the startup code | set on almost every sample; toggles independently of `8\|5` | raw |
| `14\|1` | **oncoming flag** | 1 = oncoming now or earlier in the track's life | ● |
| `16\|8` | **score** | existence-like, 0-100 | ◐ |
| `24\|7` | **age** | radar cycles: 1 at birth, saturates at 126, 0 = slot retiring | ● |
| `107\|1` | coast flag | rarely set in settled life, often set just before deletion | ○ |
| `109\|3` | **motion code** | see table below | ◐ |

**Score `16|8`.** Sits at 100 on a well-measured object and dips while measurements are weak. In state 2 it steps
down by **exactly 20 or 1 per cycle** (every one of 18,804 mature state-2 updates), and the slot is freed near 20.
When the score is at most 40, the step is 20 and `107|1` is clear, the allocation is removed on the next record 82-86%
of the time. The upper three bits of this byte (`20|3`) read 6 → 5 → 3 → 2 → 1 during that countdown.

**Startup code `8|5`** matches its formula on 134,217 / 134,217 birth samples across 24 drives: ages 1-4 read 30, then
20, 13, 9, 6, 4, 2, 1, 1, 0. Once the motion code leaves 5 the field takes other, mature values.

**Motion code `109|3`** (the historical 2-bit `109|2` view drops bit 111):

| code | behaviour | reading |
|---|---|---|
| 0 | positive longitudinal ground velocity | moving forward |
| 1 | slow | slow or standing |
| 2 | negative longitudinal ground velocity | oncoming |
| 3 | lateral velocity < −0.15 m/s on all mature samples | moving right (crossing) |
| 4 | lateral velocity > +0.15 m/s on 600 / 602 mature samples | moving left (crossing) |
| 5 | every age-1 to age-3 sample | initializing |
| 7 | slow after sustained motion | stopped after moving |

## Lane assignment

| bits | field | decode | conf. |
|---|---|---|---|
| `128\|3` | **lane state** | 3 ego lane, 2 right lane, 4 left lane; 1 / 5 / 7 = no lane weights | ● structure, ◐ names |
| `148\|4` | **right-lane weight** | 0-15 | ◐ |
| `152\|4` | **left-lane weight** | 0-15 | ◐ |
| `156\|4` | **ego-lane weight** | 0-15 | ◐ |

The three weights **sum to 15 or 16** whenever any is nonzero (191,151 of 191,153 samples): a lane-assignment
probability in 1/15 steps. The lane state matches the dominant weight on 99.6% of samples and is exactly zero-weight
for codes 1 / 5 / 7.

![lane weights](img/analysis/lane_weights.png)

The dominant weight sits one lane width apart: median yRel −3.8 m (right), 0 m (ego), +3.7 m (left). At the lane
edges, weight moves smoothly from one lane to the next. The ego-lane weight is the radar's own **in-path** estimate,
which openpilot's radard does not have (radard has no lateral gate; [08](08_openpilot_integration.md)).

The decoder exposes the triplet as `NativeObject.raw_weights148` (right, left, ego order as on the wire) and the state
as `raw_weight_state128`.

## Class and size

| bits | field | decode | conf. |
|---|---|---|---|
| `163\|3` | **class** | 1 not yet classified, 2 car, 3 large vehicle, 4 pedestrian, 5 provisional (cyclist/person associations), 6 two-wheeler | ◐; 5 ○ |
| `140\|3` | class, second encoding | 0, 5, 7, 1, 3, 4 ↔ class 1, 2, 3, 4, 5, 6 (exact on 1,253,081 rows) | ● |
| `136\|4` | class confidence | 0-15; 15 on nearly all pedestrians and two-wheelers | ○ |
| `216\|6` | **width** | `(code + 1) × 0.1` m | ◐ |
| `56\|7` | **length** | `code × 0.1` m | ◐ |
| `272\|5` | height-like size code | larger for large vehicles | ○ |

The class code and the two size fields describe one consistent object box (mature tracks, 399 one-minute segments):

| class | share of rows | median speed | width | length |
|---|---|---|---|---|
| 1 not yet classified | 15% (median age 5) | 2.6 m/s | — | — |
| 2 car | 75% | 9.2 m/s | 1.8 m | 4.9 m |
| 3 large vehicle | 9% | 4.9 m/s | 2.0 m | 5.7 m |
| 4 pedestrian | 1% | 0.7 m/s | 0.5 m | 0.4 m |
| 6 two-wheeler | rare | 9.4 m/s | 0.7 m | 1.7 m |

Width also matches camera-measured vehicle width to about 0.05-0.07 m in the per-track median. Video review shows
class 4 on people at crossings and fuel pumps and class 6 on motorcycles.

**Class 5 has candidate cyclist and person associations.** Four reviewed lifecycles across three drives align
with visible cyclists, including two that reach mature age. Two runs on another drive nominally follow visible
walkers, including one with 31 mature rows. The camera review covers 21 episodes across 11 drives from a
45-episode inventory, with ambiguous parked-vehicle, road and traffic-furniture scenes also represented.
Association remains provisional under geometry sensitivity; the code alone does not certify physical identity.
All 968 class-5 samples read 15 in `136|4`;
that maximum is a raw confidence-like code, without a calibrated classification guarantee. The height-like
`272|5` code spans 4–11 on these samples and remains unscaled. Counts and witness limits are in
[`class5_video_review.json`](../data/analysis/summaries/class5_video_review.json).

![object size](img/analysis/object_size.png)

## Uncertainty and quality

| bits | field | behaviour | conf. |
|---|---|---|---|
| `224\|7` | σ dRel | grows with range, shrinks with track age, rises before deletion | ◐ |
| `232\|7` | σ yRel | grows with \|yRel\|, shrinks with age | ◐ |
| `240\|7` | σ vx | grows with range, shrinks with age; higher when vRel disagrees with the camera (AUC 0.70 at 30-60 m) and during velocity excursions | ◐ |
| `248\|7` | σ vy | grows with \|yRel\|, shrinks with age | ◐ |
| `200\|7` | σ heading | follows the angular uncertainty implied by σ vx and σ vy (70% exact, 95% within one code) | ○ |
| `256\|8` | existence-like | rises with age at fixed range (ρ +0.86 to +0.90), drops before deletion | ○ |
| `264\|8` | measurement state | settled values depend on range (4 ≈ 10 m, 3 ≈ 12 m, 1 ≈ 30 m, 2 ≈ 47 m): a near/far-scan mode | ○ |
| `184\|8` | secondary score | 59-100 on allocated slots | ○ |

`240|7` is exposed as `NativeObject.vel_unc_code`. A saturated velocity (`64|10` = 1023, about +77 m/s over ground)
always comes with `240|7` = 127 and is an invalid reading: it appears in short runs on mature tracks at 34-97 m (about
once per hour of driving) and often decays through 1022, 1014, 1006 … over the next records. Record-to-record jumps
of more than 5 m/s on a mature track (≈ 83 m/s² in 60 ms) belong to the same family and are about 20 times more
common. Both profiles withhold the saturated reading; `STEADY_CONFIG` also withholds jumps above 8 m/s
([07](07_velocity_excursions.md#options)).

![saturated velocity](img/shots/night_dying_track_excursion.jpg)

*Night, drive B: track #2 (a car about 61 m ahead in the left lane) jumps to 72 m and +55 to +61 m/s relative
(76 m/s over ground, code 1023) in its last second before the radar drops it.*

## Raw and constant bits

- **Raw, unnamed:** 13, 15, 63, 106, `112|3`, `115|8`, `131|4`, `166|2`, `168|10` (only codes 0, 768, 832, 1023),
  181, 182, 183, `192|8`, 239, `277|11`. Bits 15 and 239 are mostly active near track birth.
- **Constant in the captured data:** 31, `94|2`, 108, `123|5`, 135, `143|5`, `160|3`, `178|3`, 207, `214|2`,
  `222|2`, 231, 247, 255.

The full per-bit statistics of the original survey are in
[`data/reference/slot_bit_map.json`](../data/reference/slot_bit_map.json); the Cabana DBC
([`dbc/ars510_objects_vbus.dbc`](../dbc/ars510_objects_vbus.dbc)) carries these readings as signal comments.
