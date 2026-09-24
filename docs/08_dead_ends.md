# 08. Dead ends: read before reopening an old idea

This project ran for months, and most of that time went into branches that turned out wrong. The single biggest lesson: **the 0x80 slot is one little-endian bit field.** Until that was found, every geometry "field" was a window cutting across two or three real fields. Those windows only looked usable through heavy per-route calibration.

IDs `D-xxx` keep the original research IDs, so older notes can be cross-referenced.

## Decode-level

| ID | idea | why it failed |
|---|---|---|
| D-051 | Range = slot bits `216\|13`, lateral = `44\|10` / `48\|8` (the pre-native decode) | `216\|13` crosses varying components separated by the observed zero bits 222–223; it is not a defended contiguous range field. Empirical calibration compressed far range. `44\|10` and `48\|8` truncate the native `44\|12` |
| D-018 | Promote bit windows that win a brute-force assignment search against vision | Winners changed with route and teacher, and some contradicted carry-chain structure. Search the structure first, then scale with physics |
| D-025 | Signed lateral from decision lists, polar projection (`range·sin θ`), or smoothing on the old decode | The old lateral field was unsigned garbage. The native `44\|12` is offset binary and correctly signed |
| D-001, D-015, D-019–D-024, D-028–D-033 | Using 0x85 "shell states", tuple whitelists, slot-4 far branches, publication / selection predicates to decide which objects are real | All compensated for reading the wrong bits. With the native decode, 0x80 alone gives every object and its lifecycle |
| D-002, D-010, D-013, D-017 | Broad regression / heavy-model sweeps for "the" vRel field | Found nothing, because velocity sat in `64\|10`, over ground, all along |
| D-011 | Bigger ML models trained on camera teachers to recover vRel | Same problem: the supervision was weak and the bits were wrong |
| D-003 | One global mode bit / scan selector explains the structure | Not found |
| D-014 | One global calibration explains geometry | True only once the right bits are read (native fields need no calibration beyond the fixed scales) |
| D-045, D-046, D-049, D-050 | Re-identify tracks with Hungarian matching; derive vRel from dRel differences; smooth range or lateral over bridged tracks | Motion-gated matching was worse than the radar's own lifecycle, and differentiated range is 4–10× worse than the native velocity |
| D-047 | Far-range dRel error shrinks with track age (Kalman convergence) | Age buckets were not range-matched; a confound |

## Support messages

| ID | idea | why it failed |
|---|---|---|
| D-004 | 0x23x is a Continental-standard object stream | Explicit Continental-layout audits failed. It is a mux/counter debug family |
| D-034, D-035, D-040 | 0x19x fields give vRel direction, or direct 0x80 geometry / count / azimuth | No field survived cross-drive gates. 0x191–0x194 summarise two selected targets |
| D-036 | Rare 0x195 / 0x196 bursts are an object stream | Activity not enriched for vehicles; no geometry field |
| D-037 | Older Toyota Continental `CLUSTER_F` layout on 0x680 | Median errors of 65–93 m; unrelated |
| D-041, D-043, D-044 | Fixed scales for 0x19x (0.03 / 0.04 / 0.05 m per code, /64 lateral) | 0x192 is ~3/64 m and heavily smoothed; don't use it as geometry |
| D-042 | Ego speed, steering, brake or yaw inside 0x23x | 3,428 packed candidates failed |
| D-054 | Simple correlation scan for finalised speed, confidence or correction | No usable decoder under the tested windows/labels. Not exhaustive: binary/constant fields were excluded initially and ID85 slicing crossed its CRC. Conditional follow-up remains inconclusive ([04](04_support_messages.md), [13](13_evidence_review.md)) |
| D-027 | Existing "measured" / "publication" / "confidence" columns are OEM quality state | Weak lift, no lifecycle invariant |

## vRel repair

| ID | idea | why it failed |
|---|---|---|
| D-052 | Gate or clip native vRel to the track's own 1.5 / 3 s range slope | Far range is too noisy (slope error 3.2 m/s median at 60–120 m); it did not remove the known false FCW |
| D-053a | Direct slot-field correlation as an excursion guard | No transferable guard in the tested family; weak conditional variance candidates remain, not proof that no quality metadata exists |
| D-053b | `84\|10` leads excursions | It lags velocity by ~1 s |
| D-053c | 4 s range-slope clip (pre-registered) | Contradicted braking only 4 → 3 |
| D-053d | Inverse-variance vision blend (pre-registered) | Kills real early warnings (4/12 kept) |
| D-053e | Range-dependent smoothing, radar-only state-space filter (pre-registered) | Delays or drops real closings (8/12, 6/12 kept) |
| D-055 | Parked cars or Doppler-stationary objects as range / lateral / velocity truth while driving | The radar deletes new stationary objects at about age 5 once ego is above ~2-3 m/s; no settled stationary track exists while moving ([14](14_stationary_objects_and_field_roles.md)) |
| D-056 | Stopped leads during approach as a range-scale reference | Leads usually stop together with ego: only 3 qualifying runs on all drives |
| D-057 | Coast-out fields (`20\|3` countdown, `107\|1`) to rescue track identity through occlusion | They appear in lost and surviving tracks alike; losses depend on the radar starting a new track nearby |
| — | Two's-complement or relative-velocity reading of `64\|10` | Over-ground is proven by standstill piles at 510.5 and pace-keeping objects at v_ego/0.15 |
| — | "vRel error is just 0xB4 scale" | 0xB4 explains about 0.2–0.4 m/s at highway speed, not ±5 m/s excursions |

## Method traps

- **Vision teachers disagree with each other more than with the radar.** Beyond 60 m, modelV2 and camera annotation disagree by 40–96 m, while radar jitter is about 1.6 m. modelV2 also reads about 1 m/s low at highway speed. Scoring against vision alone makes the radar look worse than it is, and invites fitting constants to vision.
- **Lead selection must follow the road.** A straight 1.8 m lane box picks adjacent-lane cars on gentle curves. On identical data it flipped a moving-lead vRel "win" into a "loss".
- **Camera tracker switches look like radar ID errors.** Check overlays before blaming the radar.
- **Box width is a bad far-range reference** (the car's side enters the box as its angle changes). Use box height.
- **Clock alignment.** One early short route had a ~1.4 s nominal model-to-CAN offset. Use `logMonoTime` from the same rlog for everything.
- **CRC mistaken for payload.** The retired ID85 eleven-pair projection consumed checksum/trailer bytes as a B block. Check integrity boundaries before semantic correlations.
- **Allocation mistaken for class.** `2|6` is the physical slot index (or unallocated code 63), not object class or reference point. Its lane correlations do not support category-dependent scale corrections.
- **No modelV2 is not the same as independent truth.** Box-growth velocity shares radar range scale; repaired camera identity uses radar continuity; three-cornered-hat SD excludes bias and assumes error independence.
