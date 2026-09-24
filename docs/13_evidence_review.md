# 13. Evidence review and latest follow-up

Reviewed against the research workspace on 2026-09-23. This note separates reproducible wire facts, historical measurements, and unresolved interpretations. No geometry constants or runtime publication rules were changed by the public-repo review.

## Reproduce the strongest corrections locally

```bash
python tools/check_structure.py
pytest
python tools/build_cabana_route.py --dbc-only
```

| bundled sample | ID85 records / valid CRC | ID80 slots checked | slot-code exceptions |
|---|---|---|---|
| highway_following_30s | 497 / 497 | 9,940 | 0 |
| highway_vrel_excursion_25s | 414 / 414 | 8,280 | 0 |

- ID85 CRC is little-endian `[141:145]`, computed over `[1:141]`. The retired eleven-pair slicing interpreted checksum/trailer as payload. Ten cells in `[21:141]` are a useful **provisional projection**, not ten established physical objects.
- ID80 `2|6` is the physical slot index, or 63 in an unallocated-form header. It is not object category or reference point. The slot may retain non-default stale bytes when unallocated.
- `0|2` is state-like, `16|8` score-like, `24|7` age. A mature original-log counterexample jumped from 72.125 to 63.3125 m in 59.334 ms with state 1 and score 100 unchanged. Score 100 is not an accuracy guarantee.

The first two claims are directly reproducible from the bundled CAN samples; the mature counterexample is a research-workspace observation, not a new bundled fixture.

## Newer stationary-target evidence

The earlier test selected targets whose **radar range** closed at the odometer rate. This conditions away inconsistent range. A newer video/odometry test (`SCR-104`) selected stationary-target hypotheses from box-height evolution, requiring fitted target speed |u| < 0.5 m/s and standard error < 0.35 m/s. It selected 6 development, 28 city and 10 highway windows; not all had a radar association or enough scored samples. These are fitted stationary hypotheses, not surveyed truth. Slow rolling and changing apparent target size remain confounders.

The following values are imported from that test, not recomputed from the older public camera-pair snapshot. Machine-readable extract: [review_followup.json](../data/analysis/summaries/review_followup.json). Full video/window inputs and the upstream test script are not bundled, so this table is provenance-labelled evidence, not a self-contained rerun.

| held-out drive | range | paired rows / windows | vRel RMS vs stationary hypothesis | median absolute ground speed |
|---|---|---|---|---|
| B, city | 5–30 m | 934 / 14 | 0.711 m/s | 0.225 m/s |
| B, city | 30–60 m | 393 / 10 | 1.349 m/s | 0.675 m/s |
| C, highway | 5–30 m | 427 / 7 | 0.551 m/s | 0.225 m/s |
| C, highway | 30–60 m | 203 / 6 | 2.197 m/s | 1.875 m/s |

Rows above include young tracks. The diagnostic age >= 60 subset reaches RMS 0.542/0.537 m/s at 5–30 m on B/C. At 30–60 m B still has median absolute ground speed 0.825 m/s; C's settled subset is too sparse for the test's reported verdict. Far stationary validation remains unverified, not passed. Rows/windows are correlated, not independent trials.

These results weaken the old statement that stopped-target checks confirm the whole velocity decode. They leave two important alternatives: braking-related tracker/compensation lag, or targets still rolling despite the fitted stationary label. Range/time-to-stop co-vary.

**Visual review of three windows (settled leads, overlay frames plus modelV2 and odometry):**

- **Night queue at a red light (drive B), video-labelled stationary:** in the 4 s window ego travels about 29 m, but modelV2's range falls only 21 m and the radar's about 23 m. Both references say the lead was still creeping forward at roughly 1–3 m/s, and the radar's ground speed agrees in sign (+1.6 → +0.5 m/s). The video fit (u = −0.01 ± 0.29 m/s) was wrong. Box height at night did not detect the slow creep.
- **Approach to a red light (drive C):** over 2 s the radar range falls only 6.4 m while ego travels about 13.7 m. That implies about 7 m of forward motion, yet the same track's ground speed reads "stopped". modelV2's range closes at the odometer rate. This is a radar range walk on a settled lead, like brake event E4 in [05](05_validation.md#brake-events-on-drive-a-before-the-pre-registration), not evidence of a rolling car.
- **A left-lane car (drive B):** no modelV2 reference, so undecided.

So the 30–60 m failures above measure the video stationary label at least as much as the radar. The box-height fit (constant or decelerating target) cannot resolve about 1 m/s of creep while ego brakes, because camera metric scale is only known to a few percent. A stricter rule, for example requiring the target to stay stopped after ego stops, does not exclude a car that crept until just before ego stopped. The 5–30 m settled-track result is the usable output of this test; 30–60 m remains unresolved.

## Quality fields: what the follow-up did and did not find

The original linear scan excluded binary/constant codes and used a flawed ID85 projection. A later follow-up (`SCR-103`) added low-cardinality categorical tests, corrected cells and object-level future-error tests with within-track circular-shift nulls.

- `16|8` score: weak association (eta <= 0.13), not a validated velocity-quality measure.
- State 2: about 0.3% of settled camera-paired rows, with larger errors but also longer range. Most excursions remain in state 1.
- `224|7`, `240|7`, and more weakly `248|7`/`256|5`: provisional near-range variance indicators, not established 30–100 m excursion guards.
- Categorical support-message/header hits were substantially confounded by range and ego speed. They have not become transferable validity rules.
- `0x19x` selected-target summaries and multiplexed `0x23x` remain semantic clues, not independent teachers until identity, timing and units are established. A correlated source can share the same radar estimator errors.

Do not repeat a broad correlation sweep. A new test needs a specific conditional hypothesis, correct integrity boundaries, same-object association and event-held-out falsification.

## Reference and replay limits

- Image box-growth supplies independent image motion, but metric velocity uses radar distance. Range-slope and velocity may share tracker errors. Camera chain repair uses radar continuity. Agreement is therefore not three independent truths.
- Three-cornered-hat values estimate centred SD under an independence assumption, not RMSE. The legacy exported key `rms_error` is retained for provenance, but its name is wrong. The research follow-up preserves negative variance estimates and adds assumed-correlation sensitivity; assumed correlations of +/-0.3 change the estimates by about 20–30%.
- The scorecard's looser consumer thresholds were proposed after results. Original targets are: 95% range errors within max(1 m, 2%) in separate bands to 150 m; lateral p95 <= 0.5 m and >=99% side correctness outside +/-0.5 m; velocity MAE <=0.5 m/s and p95 <=1 m/s; >=99% correct physical identity over eligible 100-cycle windows; >=95% recall on predeclared high-trust targets with false-object reporting. These are research objectives, not a safety certification, and are unmet or unverified here.
- The original replay bypasses messaging health checks and reset radar export state per segment. The bundled `replay_radard.py` now carries radar-interface and consumer state across consecutive rlogs and resets only on a CAN gap > 2 s. On a two-segment highway check, the lead kept its trackId across the file boundary. The research workspace re-ran its baseline and fault replays under continuous export: baseline FCW stayed 0 on all drives; lead-track switches on drive A fell from 6 to 4 (the removed ones were artificial resets); native-only braking episodes were unchanged; the injected −6 m/s fault on drive C gave 73 FCW ticks instead of 50. The candidate-defence runs in [06](06_known_limitations.md) were not repeated.
- Preserve both first-frame and completion timestamps. The Cabana exporter plots a completed record at its first-frame time for visualization; causal replay must not make its contents available before completion. The assembler is count/start-marker based, with CRC protecting payload integrity; explicit sequence/gap validation remains a transport-hardening task.
- A separate missing-stream test (`SCR-105`) exercised upstream health/state-machine logic: radarState became invalid after 0.50–0.55 s; 5 s outages soft-disabled; stale payloads at normal cadence were not flagged. This is not validation of all CAN corruption or fault paths.
- Consumer revision `10b9e73` is not the recorded FrogPilot 0.9.7 controller. Offline plans are not exact on-car counterfactuals or closed-loop outcomes.

## Most useful next contributions

1. Stationary truth at 30–60 m needs a better stationarity label than box-height evolution. Candidates: parked roadside cars that remain in frame until passed, or queues where a static landmark (stop line, pole) shows the target not moving. The first three reviewed windows split between a creeping queue (video wrong) and a radar range walk (radar wrong); see above. Stationary ground targets identify velocity zero, not multiplicative scale.
2. Use nonzero-motion, stable-identity windows to test the velocity scale and reference frame against independently checked distance and ego motion. On curves, include rotating-frame terms: for left-positive coordinates, xdot = v_ground_x - v_ego + yaw_rate*y, subject to sensor lever-arm convention.
3. Test whether state/quality transitions predict future disagreement after matching age, range and ego motion. A confidence/existence code need not correlate linearly with signed velocity error. Do not fit category corrections to the slot index.
4. Verify any companion-message linkage before using it to arbitrate radar errors. Preserve counterexamples and report coverage, not only successful matches.

No additional route, on-car software change or instrumented second vehicle is required to start these checks. New vehicles/firmware would help test generalization, but current errors do not yet establish a hardware accuracy ceiling.
