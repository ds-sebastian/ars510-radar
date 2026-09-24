# 07. openpilot integration notes

Nothing here has been run in a car. All findings come from offline replay of logged drives through openpilot's unmodified `radard` and longitudinal planner (the MPC was built outside the openpilot tree). Replay is open-loop: ego motion stays as recorded. It shows what openpilot *would have requested*, not what the car would have done.

## What the stock pipeline does with radar points (important)

These properties of `radard` held at openpilot commit `10b9e73` (September 2026). Any integration has to cover them:

1. **One NaN vRel poisons a track permanently.** radard's per-track `KF1D` takes the NaN and never recovers; checked with 100 clean updates afterwards. The low-speed override path has no velocity check, so vLead became NaN on 20 ticks. aTarget differed by up to −1.6 m/s² for ~16 s. **Never publish NaN vRel.** `OPENPILOT_CONFIG` sets `drop_unresolved_vrel=True`, which withholds points until ego speed is known.
2. **No lateral gate.** If the true lead is missing from the radar list, an object in the adjacent lane at the right distance and speed becomes the lead 34–78% of the time, even at 6 m lateral offset. With the true lead present, the likelihood prefers it at ≥ 3.6 m offset.
3. **Velocity sanity is permissive:** `abs(vRel + v_ego - vision_v) < 10` **or** `vRel + v_ego > 3`. A −6 m/s vRel fault for 2 s passes straight through: −3.6 to −4.3 m/s² harder braking, and 32 FCW ticks in the historical city replay.
4. **Distance gate `max(5 m, 25% of d)`.** It rejects range walks, and a ghost at 0.6·d on highway and city. Because of the 5 m floor it accepts one in stop-and-go.
5. **Low-speed override** (v < 4 m/s): a radar-only lead with modelProb 0 is accepted. A centre ghost at 5 m was accepted 45% of the time (−2.2 m/s²).
6. **Repeated stale values are not the same as missing messages.** The original numeric-injection harness always returns true from `FakeSM.all_checks()`, so it does not exercise SubMaster health checks. A later dedicated missing-stream test invalidated radarState after 0.50–0.55 s; stale values delivered at normal cadence were not detected. See [13](13_evidence_review.md). The example interface separately flags no-record timeout.
7. **Radar use is gated on vision.** radard only matches a radar track while vision lead probability is > 0.5. In one far closing (E0), useful radar was discarded when vision dropped out.

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

- **Stock parser mismatch.** opendbc's TSS2 `RadarInterface` reads 0x180–0x19F with `toyota_tss2_adas.dbc`, which is wrong for this radar. A radar-specific interface is needed. `examples/opendbc_radar_interface.py` is a sketch; it runs against opendbc structs on the sample data and has never driven.
- **Detection.** The ARS510 answers FW query `8821F0R03100` at 0x750 sub 0x0f. The presence of 0x80 on bus 1 is another cheap signal.
- **Longitudinal control and radar silence.** The RAV4 TSS2 platforms are `RADAR_ACC`: stock ACC commands come from the radar. openpilot longitudinal on these cars is behind the alpha toggle. In current opendbc that path sends a UDS *communication control* to the radar at 0x750 to stop it transmitting.
  - On the logged drives, a FrogPilot build had openpilot longitudinal enabled, and **0x80 objects were still present on bus 1 throughout**.
  - Whether the stock alpha-long path silences bus-1 object output too has **not been checked**. Check it first. If it does, radar tracks and openpilot longitudinal are mutually exclusive on stock openpilot until that changes.
- **Ego speed.** 0x80 carries over-ground velocity. Subtract a consistent ego speed with the matching `vground_scale`.
- **Origin.** dRel is from the radar. radard adds `RADAR_TO_CAMERA = 1.52` itself, and the camera checks confirm that convention.

## Suggested path to on-road testing

1. Log-only first: decode offline, then add the interface as a **shadow** publisher (e.g. a separate `liveTracks`-like topic) with radard untouched.
2. Replay every drive through radard and the planner. Track FCW ticks and native-only braking episodes per hour as regression metrics. `tools/decode_log.py` gives you the points; the replay harness used here patched radard at runtime and is described in [09](09_testing_a_new_drive.md).
3. Before any control use, add a consumer-side defence against vRel excursions that keeps confirmed closings ([06](06_known_limitations.md)), plus a lateral gate.
4. Use it as a *second opinion*: for example, raise caution when radar shows strong closing that vision under-reads, rather than letting radar override vision outright.
