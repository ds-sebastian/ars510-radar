# 07. openpilot integration notes

Nothing here has been run in a car. All findings come from offline replay of logged drives through openpilot's unmodified `radard` and longitudinal planner (the MPC was built outside the openpilot tree). Replay is open-loop: ego motion stays as recorded. It shows what openpilot *would have requested*, not what the car would have done.

## What the stock pipeline does with radar points (important)

These properties of `radard` held at openpilot commit `10b9e73` (September 2026). Any integration has to cover them:

1. **One NaN vRel poisons a track permanently.** radard's per-track `KF1D` takes the NaN and never recovers; checked with 100 clean updates afterwards. The low-speed override path has no velocity check, so vLead became NaN on 20 ticks. aTarget differed by up to −1.6 m/s² for ~16 s. **Never publish NaN vRel.** `OPENPILOT_CONFIG` sets `drop_unresolved_vrel=True`, which withholds points until ego speed is known.
2. **No lateral gate.** If the true lead is missing from the radar list, an object in the adjacent lane at the right distance and speed becomes the lead 34–78% of the time, even at 6 m lateral offset. With the true lead present, the likelihood prefers it at ≥ 3.6 m offset.
3. **Velocity sanity is permissive:** `abs(vRel + v_ego - vision_v) < 10` **or** `vRel + v_ego > 3`. A −6 m/s vRel fault for 2 s passes straight through: −3.6 to −4.3 m/s² harder braking, and 32 FCW ticks in the historical city replay.
4. **Distance gate `max(5 m, 25% of d)`.** It rejects range walks, and a ghost at 0.6·d on highway and city. Because of the 5 m floor it accepts one in stop-and-go.
5. **Low-speed override** (v < 4 m/s): a radar-only lead with modelProb 0 is accepted. A centre ghost at 5 m was accepted 45% of the time (−2.2 m/s²).
6. **Repeated stale values are not the same as missing messages.** The original numeric-injection harness always returns true from `FakeSM.all_checks()`, so it does not exercise SubMaster health checks. A later dedicated missing-stream test used SubMaster's real alive / frequency / valid rules and the selfdrived state machine:
   - it invalidated radarState after 0.50–0.55 s, and until then radard used the last tracks as valid;
   - outages ≤ 0.4 s were never flagged;
   - 5 s outages ended in a soft-disable disengagement every time;
   - 90% record loss for 2 s invalidated, 50% did not;
   - stale values delivered at normal cadence were not detected. See [13](13_evidence_review.md). The example interface separately flags no-record timeout.
7. **Radar use is gated on vision.** radard only matches a radar track while vision lead probability is > 0.5. In one far closing (E0), useful radar was discarded when vision dropped out.
8. **Already-stopped vehicles never reach radard.** The radar deletes new stationary objects after about 0.3 s once ego is above about 2-3 m/s ([14](14_stationary_objects_and_field_roles.md)). Radar can back up vision on leads it watched slow down and stop, not on a stalled or parked car in lane.

The zero-range sentinel tracks (0 m, −12 m/s) that young tracks emit were never selected (0.75 m floor plus the distance gate). They are filtered anyway by the age gate.

## Experimental interface profile (not approved for control)

```python
from ars510 import Ars510NativeRadarInterface, OPENPILOT_CONFIG
# OPENPILOT_CONFIG = NativeInterfaceConfig(min_publish_age=60, relink_max_gap_s=3.5,
#                                          vground_scale=0.149/0.15, drop_unresolved_vrel=True)
```

| setting | why |
|---|---|
| `min_publish_age=60` | young tracks are unconverged. At 60, radard acceptance of the vision lead stays ≥ 0.92 to 100 m. In replay, the raw profile published 166 age-1 zero-range sentinels, 21 points > 200 m and 52 with \|vRel\| > 60; this profile published none |
| `relink_max_gap_s=3.5` | keeps the trackId when the radar re-initialises a car it briefly lost, so radard's Kalman filter is not reset. Rule fixed in advance; the 2.5 → 3.5 s change passed a pre-registered test |
| `vground_scale=0.149/0.15` | empirical ego-reference correction, not a recovered OEM constant. Revalidate when changing speed source; start from raw 1.0 rather than transplanting the correction |
| `drop_unresolved_vrel=True` | NaN protection (item 1 above) |

## Exploratory consumer-tolerance proposal

These are not the original research targets or sufficient safety criteria. See [13](13_evidence_review.md) for the stricter accuracy, identity and recall objectives. In the following table, the historical three-cornered-hat "RMS" figures are conditional random-error SD, not bias-inclusive RMSE.

| field | threshold |
|---|---|
| dRel | median error ≤ max(1 m, 10%) to 100 m; radard acceptance of the vision lead ≥ 85% |
| yRel | ≥ 98% correct side for \|y\| > 1 m; median lateral error ≤ 0.5 m |
| vRel | beats zero and range-derivative baselines in every band to 100 m; RMS ≤ 1.0 / 1.5 / 2.0 m/s at 3–30 / 30–60 / 60–100 m; **camera-contradicted braking ≤ 1 per 10 engaged hours** |
| trackId | purity ≥ 0.95 over ≥ 300 cycles for ≥ 80% of long tracks; no duplicate IDs; no verified wrong re-link within 60 m |

Current status against them is in [05](05_validation.md#scorecard-on-held-out-drives-b--c): vRel fails the last bar by about two orders of magnitude on highway.

## Drive-level consumer results (replay)

| metric | drive A, engaged 11.6 min | drive B, forced 41.9 min | drive C, forced 24 min |
|---|---|---|---|
| FCW ticks, radar profile | 6 (one false event) | 0 | 0 |
| FCW ticks, vision only | 0 | 0 | 0 |
| camera-contradicted native braking episodes | 1 + 1 unpaired | 0 | 4 |
| aTarget(native) − aTarget(vision), p01 | −2.39 m/s² | −0.94 | — |

"Native-only braking episode" means the radar profile plans ≤ −1 m/s² while vision-only plans ≥ −0.3. Each episode was classified from camera box growth and a 3 s box-height trend.

### Replay reproducibility limits

The upstream consumer (`10b9e73`) differs from the recorded FrogPilot 0.9.7 build; vision-only replay is not an exact reconstruction of the recorded controller. Before two brake events its aTarget differed by median 0.14–0.52 m/s². Numeric fault tests bypass messaging health checks.

Earlier versions of `replay_radard.py` built fresh radar interfaces for every segment while keeping consumer state, so track IDs restarted at each file boundary. The harness now carries interface and consumer state across consecutive rlogs and resets only on a CAN gap > 2 s.

The research workspace re-ran the baseline and fault replays under continuous export:
- the drive-level results in the table above held: baseline FCW 0, braking episodes unchanged;
- lead-track switches on drive A fell from 6 to 4.

The candidate-defence counts in [06](06_known_limitations.md) come from the older per-segment exports and were not re-run.

## Platform facts that affect integration

- **Stock parser mismatch.** opendbc's TSS2 `RadarInterface` reads 0x180–0x19F with `toyota_tss2_adas.dbc`, which is wrong for this radar. [`openpilot/`](../openpilot) has the installable integration; see below.
- **Detection needs the FW version.** The ARS510 answers FW query `8821F0R03100` at 0x750 sub 0x0f.
  - After power-up the radar sends its first 0x80 / 0x85 frame 5.83–5.92 s after first CAN (11 of 11 logged ignition starts). The target summary 0x191 comes after 0.15–0.87 s.
  - CAN fingerprinting is over by then. A rule that only looked for 0x80 on bus 1 missed the radar on every ignition start in replay.
  - The integration detects by FW, and uses bus 1 only as a fallback (for example after an openpilot restart with the radar running).
- **Longitudinal control and radar silence.** The RAV4 TSS2 platforms are `RADAR_ACC`: stock ACC commands come from the radar. openpilot longitudinal on these cars is behind the alpha toggle. In current opendbc that path sends a UDS *communication control* to the radar at 0x750 to stop it transmitting.
  - On the logged drives, a FrogPilot build had openpilot longitudinal enabled, and **0x80 objects were still present on bus 1 throughout**. But that build did not use the radar-disable path: its logged CarParams has `DISABLE_RADAR` clear, and a device sends 0x2FF on bus 0, which FrogPilot treats as a smartDSU. Current openpilot has no smartDSU path.
  - Whether the stock alpha-long path silences bus-1 object output too has **not been checked**. Check it first. If it does, radar tracks and openpilot longitudinal are mutually exclusive on stock openpilot until that changes.
- **Ego speed.** 0x80 carries over-ground velocity. Subtract a consistent ego speed with the matching `vground_scale`.
- **Origin.** dRel is from the radar. radard adds `RADAR_TO_CAMERA = 1.52` itself, and the camera checks confirm that convention.

## End-to-end replay of the installed integration (2026-09-24)

`openpilot/install.py` was installed into a copy of opendbc `4134c0d`. Then
[`process_replay_ars510.py`](../tools/openpilot_replay/process_replay_ars510.py) ran openpilot `10b9e73`'s own
process_replay (`card` → `radard` → `plannerd`) over drives A, B and C, once with stock opendbc and once patched:
- fingerprinting ran from the logged FW cache and the logged CAN, as on the car;
- alpha long was off, because in process_replay card stalls after the radar-disable routine, stock opendbc too.

Numbers: [`openpilot_integration_replay.json`](../data/analysis/summaries/openpilot_integration_replay.json)
(research-workspace run, provenance-labelled).

| | A (26 min) | B, route 1 (22 min) | B, route 2 (20 min) | C (24 min) |
|---|---|---|---|---|
| ARS510 detected, `radarUnavailable` false | yes | yes (ignition start) | yes (ignition start) | yes |
| radarTracks rate / max gap | 16.6 Hz / 0.10 s | 16.6 Hz / 0.51 s* | 16.6 Hz / 0.48 s* | 16.6 Hz / 0.09 s |
| radarTracks with an error | 0 | 13* | 17* | 0 |
| radar-matched lead (share of ticks) | 51% | 62% | 33% | 77% |
| FCW ticks, patched / stock | 8 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| braking only in patched / only in stock (episodes) | 9 / 3 | 7 / 1 | 4 / 0 | 11 / 0 |
| `RadarInterface.update()` mean / p99, desktop CPU | 8.6 / 24 µs | 9.5 / 31 µs | 9.3 / 29 µs | 9.8 / 28 µs |

\* All error messages fall in the last second of each route, when the radar stops at ignition off before logging ends. Both ignition starts produced no error: the interface reports empty, error-free tracks until the first record.

- **Same behaviour as the research interface.** The drive-A FCW is the known false event: the lead's vRel swings to
  about −6 m/s at 45–50 m while vision reads about −1 m/s, and the planner asks for −3.5 m/s². On drive C, 10 of 11
  patched-only braking episodes match the earlier camera-classified census within 1 s:
  - 3 camera-confirmed closings;
  - 5 where the radar overstated closing;
  - 1 contradicted by the camera;
  - 1 vision-led.
  The integration adds no new failure mode in replay. It carries the known vRel caveat unchanged.
- **What openpilot does with errors.** radarTracks with an error → radarState invalid → selfdrived `commIssue`,
  which applies to lateral control too. With openpilot long it also raises `radarTempUnavailable`. So a real 0x80
  pause of more than 0.5 s while driving would disengage. None occurred on these drives.
- **Seeing it.** With `--save-logs`, the harness writes replayed rlogs that openpilot's own `tools/clip/run.py`
  renders as the UI over the road video, lead chevron included. They also open in PlotJuggler. See
  [09](09_testing_a_new_drive.md).

## Does fused radar make the planner react more like the driver? (exploratory)

These are the same replays as above. Only stretches where openpilot was not controlling speed are used, so the
recorded speed is the driver's. This covers most of drive B and ~55-60% of A and C. In each case the planner is
stock openpilot's own radard and planner. "Vision-only" is this car today; "radar+vision" adds ARS510 tracks, which
radard fuses with the vision lead. Numbers:
[`driver_brake_agreement.json`](../data/analysis/summaries/driver_brake_agreement.json) (research-workspace run,
definitions fixed in the script but not pre-registered).

| driver brake presses with a vision lead (59) | vision-only | radar+vision |
|---|---|---|
| planner already asking ≤ −0.5 m/s² within 3 s before the press | 64% | 73% |
| planner asking ≤ −1.0 m/s² | 32% | 44% |
| only this planner reacted | 1 | 6 |
| median strongest request (driver median −1.32 m/s²) | −0.80 | −1.03 |
| hard driver braking (≤ −1.5, 19 presses): asked ≤ −1.0 m/s² | 42% | 63% |

- **Timing is unchanged.** When both planners reacted (37 presses), they did so at the same time: median
  difference 0.0 s; radar earlier on 8, vision earlier on 4.
- **Planner braking episodes** (≤ −1 m/s² for ≥ 0.3 s):

  | planner | episodes | driver slowed | driver pressed the gas |
  |---|---|---|---|
  | vision-only | 61 | 44 | 17 |
  | radar+vision | 75 | 53 | 22 |
  | radar-only episodes | 7 | 2 | 5 |

- **The drive-C −3.5 m/s² request** came just after openpilot longitudinal disengaged, so it is outside this
  sample. At that moment the driver was on the gas and then accelerated.

So on real slowdowns, fused radar moves openpilot toward what the driver did: more often, and closer to the
driver's deceleration, without reacting later. The price is a few extra brake requests that the driver overrode with
the gas.

The driver is a behavioural reference, not ground truth. The replay is open loop, and this is three drives by one
driver.

## Pre-registered: vision-only vs radar+vision, judged against the driver (2026-09-24)

This is the thorough version of the exploratory check above.
- **Plan:** written before scoring, with two amendments made before any held-out result.
- **Data:** 20 held-out routes, 4.56 hours with the driver controlling speed.
- **Systems:** both are stock openpilot `10b9e73`. "Vision-only" is this car today; "radar+vision" is the same code
  with the integration. Vision is the recorded model, not the newest one.
- **Numbers:** [`driver_agreement_preregistered.json`](../data/analysis/summaries/driver_agreement_preregistered.json)
  (research-workspace run, provenance-labelled).

| test | vision-only | radar+vision | outcome |
|---|---|---|---|
| P1: already asking ≤ −1 m/s² in the 3 s before the driver brakes (167 presses with a lead) | 40.1% | 44.3% | 9 vs 2 events only one system caught; Holm p 0.20: **not significant** |
| G1: when it starts braking, relative to the driver | — | **0.15 s earlier** [0.05, 0.26] | guard holds (not later) |
| P2: strongest request vs the driver's actual braking (mean error) | 0.41 | 0.41 m/s² | no difference |
| P3: moment-to-moment request vs the driver's acceleration (MAE) | 0.174 | 0.186 m/s² | **radar+vision worse**, CI [+0.007, +0.016]; worst in steady following |
| P4: overrides of openpilot long (28 with a lead): leaned the driver's way / the other way | — | 6 / 2 (20 the same) | sign p 0.29: not significant; request closer to what the driver then did |
| speed-ups (286): already asking ≥ +0.3 m/s² | 57.7% | 59.4% | no help (first request 0.04 s later) |
| hard slowdowns and stops (47): never asked ≤ −1 m/s² | 10 | 9 | no difference; already-stopped leads (7): neither missed |
| cost: radar-only brake requests per hour of driver control | — | 1.97, with the driver on the gas for 0.88/h | within the pre-set limit (≤ 2/h) |

**Pre-registered verdict: no evidence of benefit.**
- Radar reacts a little earlier and a little more often to real slowdowns, and leans toward the driver when they
  override. But the effects are too small to pass the corrected tests.
- It adds jitter: the matched radar lead's distance jumps by 10 m or more between tracks, and vRel is noisy.
- It does nothing for speeding up.
- The development drives (1.06 h) showed the same pattern.

A follow-up tested interface-only ways to reduce that jitter against the same yardstick. See
[06](06_known_limitations.md#re-test-of-interface-only-options-against-the-driver-pre-registered-2026-09-24).
- `range_fusion_gain=0.1` cuts lead flip-flopping by 28% at no measured cost.
- None of the candidates matched vision-only's moment-to-moment agreement, so the default profile is unchanged.

Limits:
- open-loop replay;
- one driver, whose driving is a behavioural reference, not ground truth;
- an old vision model;
- only 28 overrides.

## Suggested path to on-road testing

1. Log-only first: decode offline, then add the interface as a **shadow** publisher (e.g. a separate `liveTracks`-like topic) with radard untouched.
2. Replay every drive through radard and the planner. Track FCW ticks and native-only braking episodes per hour as regression metrics. `tools/decode_log.py` gives you the points; the replay harness used here patched radard at runtime and is described in [09](09_testing_a_new_drive.md).
3. Before any control use, add a consumer-side defence against vRel excursions that keeps confirmed closings ([06](06_known_limitations.md)), plus a lateral gate.
4. Use it as a *second opinion*: for example, raise caution when radar shows strong closing that vision under-reads, rather than letting radar override vision outright.
