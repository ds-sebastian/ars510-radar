# 05. Validation: methods and scorecard

The central worry is circularity: teacher agreement alone cannot establish that radar is an independent second opinion. The tests below use several references with different dependencies, including camera geometry, ego motion, radar range history and modelV2 comparisons. See [13](13_evidence_review.md) for corrections and newer evidence; the historical results below are not a drive-readiness certificate.

## Drives

| drive | role | driving | notes |
|---|---|---|---|
| calibration S / L | field discovery, range-zero fit | short urban / long highway | early work |
| **A** | development | ~26 min mixed | every constant and rule frozen here |
| **B** | held-out, pre-registered | ~43 min city | wet and night scenes; hilly |
| **C** | held-out, pre-registered | 24 min highway | chosen because B lacked highway far range |

B and C were held out for specified frozen tests. Later analyses, the 3.5 s relink follow-up and exploratory consumer thresholds have separate provenance; not every claim here was pre-registered. These drives are now observed evidence, not fresh holdouts for another tuning pass.

## Independent references

1. **Camera ground contact.** Narrow road camera, YOLO boxes, the log's own liveCalibration (height ≈ 1.38 m, pitch) and openpilot intrinsics. Project the box bottom (tire line) onto a flat road. This gives absolute range at 5–25 m; beyond that, road slope makes it noisy.
2. **Camera box growth (closing rate).** `v = −(range_to_camera) · d ln(h)/dt`, where `range_to_camera = dRel + 1.52 m`. Image expansion is a separate witness, but metric velocity inherits radar range error, association error and changes in apparent vehicle shape. Error independence is not established.
3. **Scale-free size ratio.** The ratio of a car's box height over 1.5 s equals the inverse range ratio. It needs no calibration at all and is used to test short-term range consistency.
4. **Ego odometry.** Wheel speed (`carState.vEgo`), GPS and gyro. They give the radar-only velocity scale, and exact vRel truth for **stopped** targets (true vRel = −v_ego).
5. **The radar's own range history.** A weak reference at far range, because range walks by metres.
6. **Three-cornered hat.** Estimates centred random-error variance only under assumed error independence. Bias is excluded; shared radar range and tracker inputs violate a simple independence argument. The shipped legacy JSON key `rms_error` is misleading: these values are conditional standard deviations, not demonstrated RMSE. Do not use them to certify accuracy.
7. **openpilot's radard + planner** (unmodified, offline replay, forced engaged). Measures what openpilot would have *done* with the points.

modelV2 was used only as a secondary comparison, and its biases are documented: it reads about 1 m/s low at highway speed, and far range disagrees with annotation by 40–96 m.

## Scorecard on held-out drives B + C

This is an **exploratory consumer-tolerance scorecard written after results were available**, not the original research acceptance gate. In particular, medians and accepted-lead statistics do not establish tail accuracy, recall or physical identity. The original targets remain unmet or unverified ([13](13_evidence_review.md)). Consumer observations motivating the proposal:
- radard associates a radar track with the vision lead only if `|dRel − d_vision| < max(5 m, 25%)`;
- it has **no lateral gate**;
- its velocity check accepts `abs(vRel + v_ego - vision_v) < 10` **or** ground speed `vRel + v_ego > 3`; it is not a strict ±10 m/s bound;
- it resets its per-track Kalman filter on a trackId change.

| field | threshold | result | verdict |
|---|---|---|---|
| **dRel** | median error ≤ max(1 m, 10%) out to 100 m; radard accepts the radar lead ≥ 85% | vs modelV2 (conservative): 0.47 / 1.69 / 3.36 / 5.65 m at 0–15 / 15–30 / 30–60 / 60–100 m, and 8.5 m at 100–150 m. radard acceptance 96 / 94 / 95 / 89% (84% at 100–150 m). Camera ground contact 5–25 m: slope 0.99, zero within 0.2 m (0.7 m on hilly B) | **pass** |
| **yRel** | ≥ 98% correct side for \|y\| > 1 m; median lateral error ≤ 0.5 m | 99.3% vs modelV2 (n = 4910); 97.9–98.3% vs camera, which has its own error; median \|dy\| 0.23 m | **pass** (camera borderline) |
| **vRel** | beats zero and range differencing in every band to 100 m; conditional SD proposal ≤ 1.0 / 1.5 / 2.0 m/s at 3–30 / 30–60 / 60–100 m; camera-contradicted braking ≤ 1 per 10 engaged hours | baselines beaten. Conditional centred SD (three-cornered hat, not RMSE): A 0.35 / 1.02 / 1.58, C 0.55 / 1.11 / 1.76, B 0.54 / 1.26 / **2.73**. Contradicted braking ≈ **10 per forced highway hour** | **fail**; absolute accuracy not established |
| **trackId** | purity ≥ 0.95 over ≥ 300 cycles for ≥ 80% of camera-checked long tracks; no duplicate IDs; no verified wrong re-link within 60 m | no duplicates; chain purity: A 90%, C 93%, B 80% within 60 m; visual review found no radar identity error within 60 m | **pass within 60 m**; beyond 60 m camera identity is too unreliable to verify |

## Detail per field

### dRel

- **Absolute scale and zero, camera ground contact at 5–25 m:**

  | drive | vehicles | slope (90% CI) | median camera − radar |
  |---|---|---|---|
  | A | 13 | 1.001 (0.951–1.024) | −0.01 m |
  | B | 30 | 0.992 (0.933–1.038) | +0.72 m (pitch/grade) |
  | C | 11 | 0.993 (0.952–1.042) | +0.22 m |

- **Far range (drive A, development, not held-out):** the narrow-camera box scale, averaged with modelV2 where they agree, puts the radar within 3.9 m median at 60–100 m (ratio 1.017, 8 vehicles) and 5.1 m at 100–150 m (only 2 vehicles). Beyond 100 m radard accepted the radar lead on 81% of frames, and the radar read about 9% shorter than modelV2. Neither reference pins far-range scale better than a few percent.
- **Short-term consistency:** see range walks in [06](06_known_limitations.md). Over 1.5 s, range change disagrees with the scale-free camera size ratio 2–4× more than integrated vRel does.

### yRel

- Sign vs camera: 99.3 / 98.3 / 97.9% (A / B / C).
- In image-column tests while stopped, the decoded left-positive sign wins 513 vs 49.
- Far objects follow road curvature with the right sign out to 150 m.
- Scale: see [02](02_object_record_0x80.md). ±10% is the honest bound.

### vRel

Camera box-growth MSE, (m/s)², all camera-paired rows:

| drive | band | native | zero | 1 s range derivative |
|---|---|---|---|---|
| A | 3–30 / 30–60 / 60–100 m | **0.24** / **1.35** / **4.55** | 2.85 / 4.81 / 10.3 | 5.85 / 16.5 / 41.4 |
| B | same | **0.68** / **3.51** / **23.7** | 5.65 / 9.73 / 34.5 | 4.27 / 17.8 / 88.5 |
| C | same | **0.37** / **1.59** / **7.13** | 4.59 / 2.72 / 13.3 | 10.5 / 22.2 / 71.9 |

Native velocity beats these baselines on the scored camera-paired samples. This supports useful information, not exact field semantics or complete object coverage. Parameter provenance must be attached to each test; later profile changes are not covered by earlier replay exports.

**Range-selected stationary-target check (conditional).** Targets were selected when decoded radar range closed at the wheel-speed odometer rate for 2.5 s. The assumed truth is −v_ego. This excludes inconsistent radar ranges by construction and cannot independently establish stationarity. The later video-selected test in [13](13_evidence_review.md) is less favourable.

| drive | tracks | band | native vRel RMS error | share of errors > 2 m/s |
|---|---|---|---|---|
| A | 1 | 5–30 m | 0.38 m/s | 0% |
| B | 10 / 6 | 5–30 / 30–60 m | 0.60 / 0.50 m/s | ≤ 0.8% |
| C | 3 | 5–30 m | 0.52 m/s | ≤ 0.8% |

The selected targets have median over-ground speed +0.08 to +0.23 m/s. This supports the zero near these conditions, not the multiplicative ground-velocity scale: zero-speed samples cannot identify that scale. Limits: 14 tracks, ego at 4–6 m/s, nothing beyond 60 m. The moving-target excursions at range ([06](06_known_limitations.md)) are not covered.

**Where native loses:** steady following at 30–100 m. There the true vRel is about 0, and native has ~1–1.5 m/s of correlated (~1 s) error, so a constant zero wins (MAE 0.51 vs 0.34 on held-out).

### trackId

- Long tracks (≥ 300 cycles ≈ 18 s): median camera purity 0.98 (B) and 1.00 (C).
- Camera-chain repair uses radar continuity and apparent size, so repaired purity is not independent physical-identity truth. Segment-local track counts and lifetimes are censored at file boundaries.
- Occlusion (camera confirms the car is still there after being hidden behind another):
  - the native ID survives 61% of the time;
  - with the re-link option, 77% (B) and 69% (C, after the gap was raised to 3.5 s).
- Why occlusions still fail (9 held-out cases): 7 are the radar itself dropping the object, never re-acquiring it within 4 s, or re-acquiring it too briefly. The ID logic is not the main limit.
- Re-link precision: 4 of 4 new re-links on highway were camera-verified as the same vehicle. The city "different vehicle" verdicts are all at 60–120 m, where camera identity is unreliable.

## Brake events on drive A (before the pre-registration)

Six driver-brake events were examined through the unmodified radard and planner (replay):

| event | what happened | radar vs vision |
|---|---|---|
| E3 (curve, 22 m/s) | real closing lead in a curve | radar saw closing 1.9 s earlier than vision (vision never below −0.27 m/s²); magnitude overstated ~50% |
| E4 (19 m/s) | real closing lead | radar closing speed agreed with the camera; plan braked 3.3 s before the driver. The last 1.5 s had a range walk (49 → 25 m) that radard's 25% gate correctly rejected |
| E0 (77–108 m) | real far closing | radar useful but late: radard discarded the radar track when vision lead probability fell below 0.5 |
| E2 (control, 30 m/s) | **velocity excursion**, no real closing | radar dipped to −2.5 m/s while camera and range said ~0 → spurious −1.9 m/s² |
| E1, E5 | not lead-driven | radar agreed with camera |

So in 3 of 6 events the radar carried real, early closing information that vision under-read by 3–4 m/s. That is the reason to keep going. It also showed the excursion failure mode, which is the reason not to switch it on.
