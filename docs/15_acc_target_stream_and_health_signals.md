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
