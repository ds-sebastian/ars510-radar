# 05. Validation: methods and scorecard

The central worry is circularity: teacher agreement alone cannot establish that radar is an independent second opinion. The tests below use several references with different dependencies, including camera geometry, ego motion, radar range history and modelV2 comparisons. See [13](13_evidence_review.md) for corrections and newer evidence; the historical results below are not a drive-readiness certificate.

**2026-09-28 correction:** several simplified camera-association scripts used
the wrong calibration-yaw sign. The box-growth MSE table and conditional-variance
estimates below have now been rescored with corrected pairing. Native identity
and shadow heuristics and the historical far-range calibration are also corrected;
relink and other affected statistics
still await their own reruns. Historical pass labels are not renewed validation. Full-matrix
projection and model-only comparisons are distinct.
See [the correction and its scope](13_evidence_review.md#camera-association-correction-2026-09-28).

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
| **vRel** | beats zero and range differencing in every band to 100 m; conditional SD proposal ≤ 1.0 / 1.5 / 2.0 m/s at 3–30 / 30–60 / 60–100 m; camera-contradicted braking ≤ 1 per 10 engaged hours | Two-second all-paired baselines beaten. Corrected conditional centred SD (three-cornered hat, not RMSE): A 0.35 / 1.02 / 1.60, C 0.56 / 1.14 / 1.73, B 0.56 / 1.44 / **2.90**. Historical contradicted braking ≈ **10 per forced highway hour**, still awaiting event-label correction | **fail**; absolute accuracy not established |
| **trackId** | purity ≥ 0.95 over ≥ 300 cycles for ≥ 80% of camera-checked long tracks; no duplicate IDs; no verified wrong re-link within 60 m | Corrected common chain heuristic at ≤60 m: A 21/21, B 28/36, C 28/30; no duplicate native IDs in the shadow audit | **physical identity unverified**; chain repair uses radar continuity, and relink requires a separate corrected audit |

## Detail per field

The corrected conditional-variance values above are imported SCR-215 reruns,
with the original summary reproduced before changing camera pairs. They assume
unproved error independence and exclude bias; the correction does not establish
physical accuracy. [Old/new sample counts, variances, biases and scope](../data/analysis/summaries/camera_semantic_correction.json).

### dRel

- **Absolute scale and zero, camera ground contact at 5–25 m:**

  | drive | vehicles | slope (90% CI) | median camera − radar |
  |---|---|---|---|
  | A | 13 | 1.001 (0.951–1.024) | −0.01 m |
  | B | 30 | 0.992 (0.933–1.038) | +0.72 m (pitch/grade) |
  | C | 11 | 0.993 (0.952–1.042) | +0.22 m |

- **Far range (drive A, development, not held-out), corrected SCR-219:** the agreement-selected mean of narrow-camera box scale and modelV2 gives median absolute residuals of 3.723 m at 60–100 m (ratio 1.0173; 1,609 rows, 9 native track-segments) and 5.143 m at 100–150 m (ratio 0.9787; 155 rows, 2 native track-segments). Camera-height-only residuals are larger: 4.721 and 6.899 m. The camera's scale is calibrated using radar range at 20–45 m; consensus additionally selects camera/model agreement. These are conditional comparisons, not independent absolute accuracy or a basis for adjusting radar scale. Model-only acceptance is unchanged. [Imported old/new counts and reference limits](../data/analysis/summaries/far_range_camera_correction.json).
- **Short-term consistency:** see range walks in [06](06_known_limitations.md). Over 1.5 s, range change disagrees with the scale-free camera size ratio 2–4× more than integrated vRel does.

### yRel

- Sign vs camera: 99.3 / 98.3 / 97.9% (A / B / C).
- In image-column tests while stopped, the decoded left-positive sign wins 513 vs 49.
- Far objects follow road curvature with the right sign out to 150 m.
- Scale: see [02](02_object_record_0x80.md). ±10% is the honest bound.

### vRel

Camera box-growth MSE, (m/s)², two-second reference, all eligible camera-paired
rows. **Corrected on 2026-09-28 (SCR-214)** with the original detection and
selection rules and corrected inverse yaw. The original pipeline first
reproduced its historical results. These are imported research-workspace reruns;
the public legacy camera-pair dataset is unchanged. [Scope, sample counts and
other window results](../data/analysis/summaries/camera_pair_correction.json).

| drive | band | native | zero | 1 s range derivative |
|---|---|---|---|---|
| A | 3–30 / 30–60 / 60–100 m | **0.23** / **1.38** / **4.65** | 2.35 / 4.40 / 10.6 | 5.60 / 16.5 / 42.6 |
| B | same | **0.67** / **3.91** / **24.3** | 5.79 / 10.2 / 34.2 | 4.57 / 18.2 / 85.7 |
| C | same | **0.39** / **1.63** / **7.13** | 5.09 / 2.51 / 12.0 | 10.5 / 22.1 / 72.9 |

This result does not extend to every distance/window: at 100–150 m on drive C,
native velocity still loses to zero on the two-second comparison. Two original
zero-baseline verdicts change after correction: drive B accepted leads at
100–150 m over two seconds now beat zero, while drive C all-paired rows at
60–100 m over six seconds now lose to zero.

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

SCR-216 corrects narrow-camera pairing and exposes an additional historical
chain-method inconsistency. A finite reconstruction reproduces old outputs, but
does not recover their original source versions. With one common current chain
rule and corrected yaw, the ≤60 m counts meeting chain purity ≥0.95 are A 21/21,
B 28/36 and C 28/30. These are heuristic results: chain repair uses radar
continuity and apparent size, and lifetimes are censored at segment boundaries.
They do not establish independent physical identity.

The native shadow test finds 6 / 20 / 18 post-shadow geometric camera candidates
on A / B / C. Native IDs survive more than one second afterward in 3 / 12 / 11.
The post-shadow test does not require the pre-shadow camera ID; 14 of the 44
candidates have no accepted detection with that ID. Camera retracking is possible,
but calling these all camera-confirmed same-object occlusions was unsupported.
These rates are geometric-candidate statistics, not measured physical occlusion
or identity-loss rates. Historical extra wide-camera rows are outside this audit.

A subsequent fixed visual witness check (SCR-223) selected four episodes from
three drive groups after requiring mature native survival and the pre-camera ID
among post candidates. None of the four supplied a visibility transition in its
five sampled frames: the putative target remained visibly separate from nearby
traffic. This does not rule out brief between-frame hiding or RF obstruction.
The small selected panel is not a population false-label rate. It fails the
physical-witness gate, so no candidate occlusion field was scored.
[Imported witness scope and verification](../data/analysis/summaries/occlusion_witness_gate.json).

Historical relink survival figures (77% B, 69% C), the nine-case failure analysis
and four-case highway same-vehicle review have not been rerun with corrected
associations. They remain historical observations, not renewed validation.
[Imported old/new results and limits](../data/analysis/summaries/camera_identity_correction.json).

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
