# 15. The radar's own ACC target stream, health signals, and an exhaustive signal search (2026-09-24)

This is a systematic search of every radar-bus message, every slot bit window, the record header and 0x85, for
anything that could help openpilot without changing openpilot. It covers:
- a velocity-glitch flag;
- a second witness for velocity;
- timing;
- radar health.

**Design.** A unified dataset of 399 one-minute segments (about 6.7 h). Before anything was looked at, the drives
were split into:
- **discovery:** drives A, B, C plus 10 further drives, 4.1 h;
- **confirmation:** 10 other drives.

Candidates were written down with thresholds before the confirmation drives were analysed. Numbers:
[`signal_atlas_and_acc_crosscheck.json`](../data/analysis/summaries/signal_atlas_and_acc_crosscheck.json)
(research-workspace run, provenance-labelled).

## Found and confirmed: the radar's own ACC target (0x235 / 0x237, radar bus, 50 Hz)

This radar is also the car's stock ACC controller. It publishes the target it follows at 50 Hz, three times the
object-list rate. Bit numbers below treat the frame as one big-endian integer, with bit 0 the LSB of byte 7. The same
fields are in [`ars510_radar_bus.dbc`](../dbc/ars510_radar_bus.dbc) and `ars510.support`.

| field | decode | check |
|---|---|---|
| 0x235 closing speed | (bits 29..39 − 1024) × 0.1 m/s, negative = closing (DBC `A235_ACC_TARGET_VREL`) | Pearson 0.78 / 0.82 (discovery / confirmation) with the matched object's native vRel; median bias against the vision lead 0.00 m/s |
| 0x237 lateral | bits 28..38 × 0.01667 − 16.70 m, left positive (`A237_ACC_TARGET_LAT`) | Pearson 0.80 / 0.97 |
| 0x237 coarse distance | bits 47..51 × 5.26 + 9.6 m, about 5 m steps (`A237_ACC_TARGET_DIST_COARSE`) | Pearson 0.81; enough to match the target to an object together with the lateral position |

**Overlapping legacy alias:** `A237_STATUS_MUX4` is byte 1's low nibble,
the high four bits of the retained coarse-distance code above. It is **not an
independent status/multiplexing selector**. Its old name and state enumeration
remain for compatibility only. Do not condition distance analysis on that
nibble as though it were independent of distance. This corrects the former
"persistent context states" description; it changes no decoded values or
runtime policy and does not establish an exact OEM distance scale.

### Finer Distance Code: Increment Scale, Not Absolute Range

The contiguous **BE39|13** window extends the coarse distance by eight low bits.
It is exposed as raw `A237_ACC_TARGET_DISTANCE_CODE` in the DBC and
`ars510.support.parse_acc_target_range_code()`. The default interface does not
use it. Its low byte wraps coherently at coarse-bin transitions, rather than
behaving as an unrelated state field.

A separate test used only the OEM 0x235/0x237 streams, with no modelV2,
annotation, or native-object geometry target. Fresh active pairs formed fixed
nonoverlapping 2 s windows with conservative lateral/continuity checks. The
discovery-only signed ratio of integrated 0x235 vRel to the fine-code change
was **0.0198465 m/code**. On 565 nontrivial confirmation windows across seven
contributing drives, the median was **0.0197805**, with no opposite-sign ratios.
The simple nominal **0.02 m/code** gave **0.0821 m** mean absolute increment
disagreement, versus **2.0272 m** for the quantized coarse-code changes.
These are same-OEM consistency errors, **not physical range accuracy**.

This supports `distance_change ~= 0.02 * code_change` for continuous-target
analysis, without fitting to vision. **The absolute offset is unresolved.**
Reusing the coarse decoder's +9.6 m offset worsened absolute reference agreement;
do not expose `0.02*code+9.6` as a new dRel decoder. Shared OEM filtering,
possible target changes, measurement timing, and reused confirmation routes
remain limitations. The comparison is an imported research-workspace result,
not a bundled rerun: [machine-readable scope and results](../data/analysis/summaries/acc_distance_increment_closure.json).

The next question is absolute origin and physical association, not another
velocity-smoothing threshold. No claim of a jitter fix or driving readiness
follows from this field alone.

**Where it comes from (checked, because it agrees with vision so well):**
- **Not sent by openpilot.** The frames are received on the radar's private bus (bus 1). openpilot's transmissions
  (`sendcan`) on these drives are only 0x2E4, 0x191, 0x343 and 0x412, all on bus 0, and nothing is ever sent on
  bus 1. (0x191 on bus 0 is openpilot's steering command; 0x191 on bus 1 is an unrelated radar message.)
- **Not driven by openpilot's timing.** After an ignition start, 0x235 / 0x237 appear 0.19 s after the first CAN
  frame. openpilot's first transmission comes at 4.1 s, and the object list at 5.9 s.
- **Tracks the lead, not openpilot's command.** Spearman with the lead's closing speed is 0.72 while the driver
  controls speed and 0.70 while openpilot does. With openpilot's acceleration command it is 0.01 and 0.43 (the latter
  only because openpilot brakes for closing leads).
- **Same quality whatever openpilot is doing.** When native and 0x235 differ by more than 3 m/s, vision sides with
  0x235 in 90% of cases while openpilot controls speed and 87% while the driver does.
- **Published whether or not cruise is on.** With a lead ahead, the target is present 96.6% of the time with stock
  cruise off, 100% with it on, and 99.3% with openpilot longitudinal active. Accuracy is the same in each state.
- **Camera fusion: not decidable from these logs.**
  - The decisive case is a vehicle that is already stopped when first seen. The object list drops those; a camera-fed
    target would still show them. It never occurred in 6.4 h: every stopped lead had been seen moving first.
  - In 5.4% of records the target sits on a vision-confirmed car with no radar object nearby. Those are short (median
    0.12 s) and mostly beyond 60 m, where vision distance and the coarse match are weakest, so they are not evidence
    of camera-only targets.
- **Open.** Toyota's system may fuse its factory camera into this target. If so, 0x235 is Toyota's production
  camera + radar estimate rather than raw radar. That would partly explain its agreement with openpilot's vision
  model, and it is still an independent second opinion.

**It is a second witness for velocity.** The target was matched to an object by position only. When the object
list's native vRel and 0x235 disagree by more than 3 m/s, the vision lead sides with 0x235:
- discovery: 90% (n = 715);
- confirmation: 86% (n = 421, 7 routes, route-bootstrap CI 79-99%);
- median gap to vision in those cases: 1.0 m/s for 0x235 against 3.6 m/s for native.

Through drive A's known false FCW, native vRel swung to −6 m/s while 0x235 stayed at +1.3 m/s.

**Using it: tested, not promoted.** The decoder has the option `acc_target_clip_mps` (off by default). It matches
the ACC target to an object by position (cost < 1, clear margin, age ≥ 60) and clips that object's vRel to
0x235 ± the given margin.

A pre-registered test against the driver used a ±1.0 m/s clip, the p95 of normal disagreement:
- It lowered the error against the driver and cut radar-only brake requests, from 1.97 to 1.53 per hour over all 20
  routes.
- On the confirmation routes, though, radar reacted 0.13-0.16 s later, so the guards failed.
- 0x235 is smoother than native vRel and trails it slightly at the start of real closings. A tight clip therefore
  holds back real braking too.

A wider clip that only acts on gross disagreements (for example ±3 m/s) is the obvious next variant. It needs new
drives to test fairly.

### Availability correction, not a promoted clip

The optional interface now rejects unavailable/malformed OEM frames and clears
both cached halves. On tested data, 0x235 byte 1 bit 2 is clear for the absent
state (status nibble 1); 0x237 holds bytes 2..7 at `00 3E 80 00 00 00`.
Those idle payloads still decode numerically to zero relative speed and coarse
position `(9.6, -0.03) m`. Previously they could match a real nearby object and
incorrectly clip its velocity. Both halves must refresh after target loss;
numeric diagnostic decode helpers themselves remain unchanged.

The fixed 1 m/s clip was replayed with only this correction on the same 20
chains. Original K7 and clip-off baseline each reproduced all 23,519 ticks of
one reference chain exactly. Corrected driver-agreement MAE is 0.18351 versus
0.18613 for default, but the fixed confirmation subset still fails the timing
guards: lag +0.158 s, interval [+0.052, +0.267] s, unchanged by the correction.
Thus invalid-target handling was a real bug, **not the explanation for the
clip's delayed braking**. Clipping stays disabled and unpromoted. These are
provenance-labelled research-workspace replay results, not bundled reruns or
physical velocity accuracy: [summary](../data/analysis/summaries/acc_availability_correction.json).

## Other confirmed signals

- **Object count in the record header.** 0x80 record header bits 115..118 hold the number of occupied slots (99.2%
  exact). This is a cheap integrity cross-check.
- **Readiness.** 0x101 reads 0x1D and 0x197 bit 8 is 0 during power-up. They switch to 0x11 and 1 before objects are
  listed, and stay there (100% on the confirmation drives). This matches the existing DBC notes. It is a direct "radar
  running" signal.
- **Physics consistency.** |Δv_ground/Δt over 0.5 s − accel field (`84|10`) × 0.03| is larger during velocity
  glitches (stratified AUC 0.69 discovery, 0.62 confirmation). It is moderate.

## Not confirmed, or nothing there

- **`240|7`** (the velocity-uncertainty candidate, docs/14): AUC 0.67 on discovery, 0.58 on confirmation. This
  matches its weak consumer result.
- **Timing.** The best lag between the radar's over-ground velocity and ego speed is +0.05-0.1 s, and it barely
  changes the error. 0xB4 with the 0.149/0.15 correction is the least-biased ego speed. Timing is not a lever.
- **No other slot field flags glitches.** All 1-12-bit windows were screened as levels and as 0.5 s changes.
- **Record header:** no ego speed, yaw or timestamp. 0x190 already carries a microsecond timestamp.
- **0x85:** only coarse relations to ego speed and lead distance. Still undecoded.
- **Car bus:** 0x344 is constant. The radar's own ACC command 0x343 was intercepted on these drives by a
  smartDSU-type device, so it is not observable here.
- **Rare status states.** A second 0x24D state (one ~100 s episode) and 0x101 = 0x21 (a 0.1 s blip) are too rare
  to interpret. 0x502 is uninterpreted.

## Using the ACC target as a reference: what the velocity glitches are (2026-09-24)

0x235 is not used as a radar value (see above). Here it serves as a research yardstick.
- **Clean glitch labels:** records where native vRel is more than 3 m/s from both 0x235 and the vision lead, while
  those two agree within 1.5 m/s.
- **Clean normal:** all three agree.
- Discovery: 344 glitch records (79 episodes). Confirmation: 230 (32 episodes, 7 routes).
- The candidates below were fixed before confirmation. Numbers are in the summary JSON.

**What a glitch looks like (confirmed):**
- **Mostly false closings:** 84% / 88% of episodes. Native vRel says the lead is approaching faster than it is.
- **Strongly range-dependent:** about 0.1 per 1000 records below 20 m, 4 at 20-40 m and 130 at 60-80 m (the ratio of
  the 60-80 and 20-40 m rates is 31× / 22×). The rate is also higher above 30 m/s ego speed.
- **A smooth drift, not a jump.** The native−0x235 gap ramps from about −1 to −3.4 m/s over about 1.5 s and decays
  over about 2 s. Record-to-record steps stay small; only 1.7% exceed 2 m/s. So this is not a Doppler-ambiguity
  flip.
- **The radar's whole motion state drifts.** The accel field `84|10` goes negative with it (AUC 0.22 / 0.38).
- **No discriminating exposed re-association marker in this subset.** Lateral jumps, track restarts and neighbour
  features have AUC approximately 0.5; tracks are settled (median age saturated). This does not prove physical
  identity through an excursion or exclude an unexposed internal target change.
- **The radar's own range does not follow the drift** (discovery AUC 0.76). But range noise makes this too weak to
  confirm as a flag (0.59): range walks as long as the glitch lasts.

**Fields that flag glitches (confirmed, moderate):**
- `240|7` (velocity uncertainty): AUC 0.65 / 0.85.
- `264|4` == 1: AUC 0.69 / 0.63.
  - `264|4` has 4 live bits by carry chain, not 5.
  - On young tracks it counts down with age.
  - On settled tracks, values 1-4 depend on range (4 ≈ 10 m, 3 ≈ 12 m, 1 ≈ 30 m, 2 ≈ 47 m). That fits a near-scan /
    far-scan measurement state (unconfirmed).
  - Glitches coincide with more state-1 readings, the suspected near-scan-only state, at ranges where the far scan
    should also see the object.

**Other checks:**
- **Velocity scale:** against 0x235, the native over-ground velocity has slope 0.99 / 1.02 at 40-80 m. The
  0.149/0.15 correction holds where it was least tested.

**Reading.** The glitch is the radar tracker's velocity and acceleration state drifting for a second or two on a
settled track at range, while its range measurements do not follow. It fits Doppler measurements from a different
scattering point or path feeding the tracker. It also explains the trade-off every radar-only filter hit: the only
radar-internal witness is range, and range wanders about as long as the drift lasts. The confirmed flags (`240|7`,
`264|4`, the accel field) are moderate. A combined flag is the next interface-only candidate, and it needs new drives
to test.

### Scope correction: not every braking request is this drift

The statistics above concern selected, large-disagreement samples, not all radar-led braking. Intermediate
disagreements were excluded from the clean-label classifier, and the original vision check gated range and
probability but not lateral agreement. A high classifier AUC therefore does not certify all consequential events.

A later research-workspace audit of nine frozen radar-only replay requests found four driver-on-gas and five
driver-slowed events; neither behaviour is physical truth. Two had no eligible core ACC association. Another
event had a **different signature**: six CRC-valid records with a mature slot's `64|10` at `1023` and `240|7` at
`127`, followed by recovery. The replayed lead had positive current relative speed but derived acceleration down
to **-31.54 m/s2**, with a **-3.5 m/s2** planner request. These are imported, provenance-labelled observations,
not a bundled rerun: [summary](../data/analysis/summaries/jitter_event_scope_audit.json).

This motivates testing interface-side discontinuity handling and consumer-history reset separately from slow
drift smoothing. It does **not** establish `1023` as an invalid sentinel, a physical meaning for uncertainty code
`127`, or the causal benefit of a guard. No new runtime option is promoted by this audit; openpilot remains
unchanged. Negative results for the tested smoothers are not an impossibility proof for all interface fixes.
