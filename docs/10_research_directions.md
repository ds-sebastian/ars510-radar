# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **The far range of every track.** The object list reads far cars short of the radar's own ACC distance (5-8% at
   50-100 m) and the vision lead agrees with the ACC distance ([06](06_accuracy.md#distance)). `fused` takes the ACC
   distance for the car the radar follows; other tracks keep the object-list range, smoothed by range fusion. A drive
   behind a second car with a GNSS logger gives the true far distance and shows where the short reading comes from;
   until then range is smoothed separately from the speed filter (the object list's range rate and speed
   disagree by 10-20%, [12](12_kalman_filter.md#what-runs-before-and-around-the-filter)).
2. **More of the lead covered by the radar's own trackers.** The ACC target is present for 99% of radar-lead time at
   15-80 m and 66% beyond on the owner's car ([08](08_openpilot_integration.md#on-the-road)). Far leads without it depend on the object list
   and its wide error alone, which is where `fused`'s remaining mild radar-only braking comes from. Finding when and why the radar
   drops or delays its target (range, speed, curve, camera state) tells whether coverage can grow.
3. **Is the radar's ACC target camera-assisted?** The radar sends it (◐, [05](05_acc_target_and_support.md)), and it
   receives lane-like camera data. Moments when the camera's messages to the radar go stale (glare, tunnels,
   startup), or one drive with the camera covered, show whether its velocity depends on the camera.
4. **Physical units for the uncertainty fields.** `240|7`, `232|7`, `224|7` and `248|7` are scaled against the radar's ACC
   target, the radar's own estimate ([03](03_slot_fields.md#uncertainty-and-quality)). An independent reference (a second car with a GPS logger,
   or a known far target) would give them physical units and test `fused`'s weights directly.
5. **Do the weighting in radard.** A radard that accepts a per-point speed variance would let this interface pass the
   radar's values through like the other radar interfaces, and would help every radar with a reported uncertainty.
   The optional radard patch (vision fusion, `VISION_V_STD_SCALE` 2.0) is a related experiment.
6. **Use the radar's own lead acceleration.** 0x235 byte 2 (relative acceleration) tracks lead acceleration better
   than radard's derived `aLeadK` against a smoothed lead acceleration from the object-list speed (correlation 0.64 vs 0.56, RMS 0.69 vs 0.80 m/s²)
   with less wobble (0.13 vs 0.15; [`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)). radard derives `aLeadK` from vRel for every car; a fork-side radard
   change that uses the radar's `aRel` would test whether the brake-release-brake feel while following eases.
7. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) would remove the brake-then-accelerate swing.
8. **Road miles with `fused`.** The replay results ([11](11_profiles_compared.md)) need closed-loop confirmation:
   drives with flagged moments, ideally from a second car, driver or radar firmware.

## Learn from Toyota's own longitudinal control

In the owner's experience, Toyota's stock ACC on this car brakes and slows well for a lead in its own lane, and holds on to a lead that leaves for
a turning lane. Those are likely two different parts of its pipeline; openpilot can learn from the first:

- **Target choice.** The radar picks its ACC target ([05](05_acc_target_and_support.md)) and
  keeps a departing car until its centre is a median 1.64 m off-axis (middle half 0.67-2.16 m; 22 departures). Measured
  against the radar's own lane boundary from the 0x85 curve cells, the release comes when the car's centre is a median
  0.29 m inside that line (21 departures): the release is consistent with the rule "keep the target until its centre reaches my lane
  line". On two matched cut-ins on the fresh drives (inconclusive at n = 2), openpilot's model moved to the new lead first
  (1.5 s and ≥ 6 s earlier); the `fused` profile leaves the lead choice to openpilot's model, which sees lanes.
- **The signal (Toyota's strength).** The radar's ACC speed is smooth and consistent with range during excursions,
  and 0x235 also carries a filtered relative acceleration. `fused` already uses the speed as a measurement.
- **The control law (to be fitted).** How Toyota turns distance, closing speed and relative acceleration into a braking
  request shows only while Toyota's ACC is in control, which the study below records.

Proposed study:

1. **Record stock ACC.** 20-30 minutes of mixed traffic with Toyota's ACC in control and the comma device logging
   (openpilot longitudinal off). The radar's own `ACC_CONTROL` (0x343) command then appears next to its target.
2. **Fit Toyota's law.** Model the requested acceleration from the radar's ACC target (distance, closing speed,
   relative acceleration), ego speed and the following-distance setting; compare it with openpilot's planner on the
   same moments (replayed with each radar profile).
3. **Separate signal from tuning.** Replay openpilot's planner fed with the radar's ACC values for the in-lane lead,
   and Toyota's fitted law fed with openpilot's lead. If the planner with Toyota's signal already behaves like Toyota,
   the remaining gap is radar handling (this repo); otherwise it is planner tuning, which belongs in the fork's
   longitudinal settings.
4. **Within-lane decisions.** Score both on in-lane braking events (onset, peak deceleration, jerk, gap at the end)
   and on lane-change / turn-lane departures, so a Toyota-like tune keeps openpilot's lead selection.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **A far-range truth drive.** Following a second car that logs its own speed (a second comma device, or a 5-10 Hz GNSS
   logger) at 40-120 m gives the lead's true velocity. The video-looming reference covers 40-110 m, with few windows
   beyond 100 m, and shares the camera with the vision model.
2. **The first second of an excursion.** Velocity steps of a consistent size and sign at onset would point to
   wrong-branch Doppler measurements leaking into the tracker; ordinary-sized steps point to low-SNR tracking
   ([07](07_velocity_excursions.md#what-the-radars-waveform-allows)).
3. **Ego-speed waveform modes.** The handbook table's three ego-speed bandwidths predict steps in the range noise floor
   at fixed ego speeds. Finding them, and the excursion rate in each mode, ties drift risk to a radar setting.

## For the decode

- **Lateral scale and range zero from slow circles.** A stationary object moves sideways at yaw rate × (range +
  3.5 m) while the car turns. Ordinary turns past parked cars already give 69 codes per metre (65-74.5,
  [06](06_accuracy.md#lateral-position)); a few minutes of slow circles in an empty lot with parked cars or poles would
  narrow that to a per-cent and pin the range zero from the gyro alone.
- **`272|5` under a known overhead object.** Driving under a bridge or gantry of known clearance, and past parked
  vehicles of known height, relates the code to height. Its ranking of pedestrians below cars points to a size- or
  reflectivity-like quantity.
- **0x85 curve cells: units and the remaining fields.** Heading `48|16` and curvature `64|15` are bounded to
  1.6-2.2e-5 rad and 2.0-2.7e-6 1/m per code ([04](04_metadata_record_0x85.md#lane--road-boundary-curves)). A camera lane polynomial with matched timing, or a drive along a surveyed curve of known radius, pins both
  units and names the flag `79|1` and the structured fields `0|9`, `20|4`, `24|4`, `44|4` and `80|6`
  ([04](04_metadata_record_0x85.md#lane--road-boundary-curves)).
- **Class 5:** a few recorded passes of a cyclist and of a pedestrian test the bicycle reading of its size and speed.
- **0x195 `q10` with brake pressure:** the logged brake pressure or the brake-assist state next to the event code
  names the deceleration quantity.
- **The radar's ACC tracker bytes and the night light records.** Two bytes of 0x237 rise while the ACC target
  accelerates or brakes, and the camera's 0x240 / 0x244 frames carry light-source records at night
  ([05](05_acc_target_and_support.md)). A drive behind a car with known braking, and a night drive past lights at known
  positions, would name their units.
- **What the camera association changes.** `112|3` shows which objects the camera has confirmed (inside 45 m by day,
  farther at night, [03](03_slot_fields.md#camera-association)). A drive with the camera covered shows what the radar
  does differently for those objects.

## For the integration

- **Other cars and firmware:** openpilot's fingerprints list `8821F0R01100` for the RAV4 2022 platform, the only other
  `8821F0R` entry besides the documented `8821F0R03100`. One capture from such a car confirms the
  layout and adds it to `ARS510_FW_VERSIONS` (until then it is detected by the bus-1 fallback on a warm
  restart). A second unit also shows whether 0x500 / 0x502 differ per unit.
- **More closed-loop driving** with the `fused` profile (the default), and a second car or driver.

## Keeping AEB under openpilot longitudinal

On an unfiltered radar line, openpilot longitudinal switches off the radar's car-bus output, including its PCS / AEB
brake request, and the car flags the loss ([13](13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)).
Ways to keep AEB:

- **A filter in the radar's line** (smartDSU-style) drops only the radar's 0x343 and passes its AEB. This works today and
  needs hardware at the radar, because the radar's link to the gateway bypasses the comma harness.
- **Relay the radar's own decision.** A disabled radar keeps sending its short-time-to-collision event pair (◐) on bus 1 (0x195 / 0x196).
  If its brake request also appears on bus 1, openpilot can forward it as 0x283 / 0x344, keeping Toyota's decision
  logic. One recorded stock AEB activation with bus 1 logged (for example against an inflatable PCS test target on a
  closed lot) shows whether it does.
- **An openpilot AEB on 0x283 / 0x344.** This needs the actuation sequence from a recorded activation, an AEB decision in
  openpilot, and a panda safety change (0x283 is idle-only). It is a fork-level safety function.
- **Name 0x320 bit 13** (likely the brake system's missing-PCS flag, ◐) by replaying the radar's idle 0x283 / 0x344 while it is
  disabled. This shows which message the brake system checks. Show PCS as available while an AEB source is active.

## What radard gets from other radars

What other openpilot radar interfaces read from their radars, and the ARS510 counterpart
([`opendbc/car/*/radar_interface.py`](https://github.com/commaai/opendbc/tree/master/opendbc/car)):

| what radard gets elsewhere | examples | ARS510 today | what would close the gap |
|---|---|---|---|
| per-track **measured vs predicted** state (`RadarPoint.measured`) | Toyota `VALID` + `SCORE`, Rivian `STATE`, Tesla `Meas` | `107\|1` = predicted (◐) and `16\|8` = existence probability (◐); the fork build publishes `measured = not predicted`, the openpilot version `measured=True` | the openpilot version could do the same; excursions arrive on measured records, so this is hygiene |
| **new-track** flag | Toyota `NEW_TRACK`, Rivian new states | derived from the age field (●) | in place |
| the radar's own **relative** speed | `REL_SPEED` on Toyota, Honda, Hyundai, Chrysler | over-ground speed (`64\|10`) minus 0xB4 ego speed | the ACC target carries a relative speed for the followed car |
| relative **acceleration** | Hyundai `REL_ACCEL`, Tesla `LongAccel` | `84\|10` over-ground acceleration (◐, lags 0.5-1 s); the ACC target's relative acceleration (●) | calibrate `84\|10` against independent motion |
| **lateral speed** | Tesla `LatSpeed` | `74\|10` (◐, 0.147-0.155 m/s per code against the gyro, `decode_references.json`) | already published as `yvRel` where forks carry it |
| radar **fault / blockage** status | Honda `RADAR_STATE`, Tesla `sensorBlocked` | "no record for 0.5 s" is reported; candidates: Toyota's car-bus 0x411 `PCS_HUD` alerts (`PCS_DUST2` sensor blocked, `PCS_INDICATOR` = 2 fault), the camera's object-list acknowledgement (0x101 byte 0, 0x197), and a long idle run of 0x680 while driving (longest 1.0 s in 7.8 h of normal driving) | a drive with a covered or dirty radar, or in heavy rain or snow, shows which of them reacts |
| measurement **uncertainty** | (rarely exposed) | `224/232/240/248\|7` family, scaled against the radar's ACC target | physical units would let radard weight radar against vision |
| plain **DBC** decode through `CANParser` | every upstream interface | a 742-byte record split over 106 frames | a reassembler of about 80 lines (`ars510/transport.py`) and a CRC check |

The closest relative in openpilot is the Tesla Model 3's Continental radar (`tesla_radar_continental`, 66 code lines at the opendbc used for the replays):
- a pass-through of distance, relative speed and acceleration, lateral position and speed, `Tracked`, `Meas`,
  existence and obstacle probabilities, class, size and uncertainty sigmas, plus a radar status message;
- the ARS510 slot follows the same Continental pattern, which is how its existence, predicted-record and uncertainty
  fields were identified ([03](03_slot_fields.md#uncertainty-and-quality));
- the two pieces a Tesla-sized interface would add: a **fault / blockage status**, and handling of the far-range speed
  error, which `fused` does by weighting each reading by `240|7` and the radar's ACC target
  ([12](12_kalman_filter.md#the-model)).

## Towards an upstream (comma) interface

The integration installs on openpilot, sunnypilot and StarPilot as an appended hook. For upstream there is a separate, single-file
candidate: [`upstream/ars510_radar.py`](../upstream/ars510_radar.py) (223 lines, 183 of them code). It holds the reassembler, the slot
decode, track IDs, the ACC target association, the Kalman speed filter and the path gate, in opendbc's style: it passes
opendbc's ruff rules (`upstream/ruff.toml`, checked in CI) and its `ty` type check. It is the smallest version with the
same driving as the full filter: parts were removed alone and together on 27 replay drives, and every hard brake was
checked against the radar's raw range, the camera and the driver ([12](12_kalman_filter.md#removing-parts-together));
the wider ACC match and the path gate came from road drives ([12](12_kalman_filter.md#path-gate)). The ledger below
says what each line buys and which parts an upstream PR could drop. Constants are fixed in the file, it runs one
configuration, and points carry `trackId`, `dRel`, `yRel` and `vRel` (the other RadarPoint fields are deprecated
upstream). A test keeps it equal to `fused` point for point (bundled samples; on 2.4.1 also two full road drives, 200,209 points, identical; `upstream_equality_2_4_1` in
[`fused_filter.json`](../data/analysis/summaries/fused_filter.json)), and
`install.py --profile openpilot` drives it on a fork. What upstream review is likely to ask, from recent openpilot / opendbc radar PRs:

1. **A clear reason the filter belongs in the interface.** Every upstream radar interface except Ford's passes the radar's
   tracks through. The ARS510's object list has slow, correlated speed errors whose width the radar reports (`240|7`) as a
   continuous scale; the unfiltered decode asks for hard braking three times as often as `fused`
   ([`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json)). The candidate's test covers the filter
   (unfiltered, the bundled excursion dives to −6 m/s). The same weighting could live in radard instead (a per-point speed
   variance), leaving the interface a pass-through. Processing in the interface has precedent: openpilot's Ford
   interface (Delphi MRR, 272 lines, 184 of them code) clusters raw detections into tracks and associates them over time.
2. **Small, separable PRs.** Decode and points first (opendbc, decode only, tested on recorded frames), the
   filter second with before/after plots and process-replay diffs.
3. **Fleet evidence.** Replays come from one car and firmware (`8821F0R03100`), with a second car's road report on the
   same firmware. Drives on other cars, through `--profile openpilot`, are what upstream would weigh.
4. **Process replay coverage.** A route segment with the radar in openpilot's process-replay tests.
5. **Alpha longitudinal compatibility.** Covered for `8821F0R03100`: after openpilot's UDS radar-disable request the
   radar stops only its car-bus messages and keeps sending bus 1 on an unfiltered radar line
   ([01](01_radar_bus.md#openpilots-radar-disable)).

### Parts of the openpilot file

Each part of [`upstream/ars510_radar.py`](../upstream/ars510_radar.py), its code lines (no comments, docstrings or
blank lines; shared constants counted once), what removing it costs on the 27 replay drives, and its status for an
upstream PR.

| part | code lines | since | without it | for upstream |
|---|---|---|---|---|
| transport, CRC, slot decode, track IDs, ego speed, RadarInterface wrapper | 103 | 1.0 | no radar | required |
| ACC target decode and association | 27 | 2.0 (range scale 0.4 x since 2.3) | +24 unjustified hard ticks on 27 drives; with the 0.25 x scale, one road late brake -1.47 -> -2.36 m/s2 | keep |
| Kalman speed filter (one state, 240|7-weighted) | 22 | 2.0 | hard radar-only braking about 3x (raw) | keep |
| young-track factor | 3 | 2.0 | further-drive hard ticks 2 -> 11 | keep |
| speed-std publication gate | 2 | 2.0 | further-drive hard ticks 2 -> 8 | keep |
| age-60 publication gate | 2 | 1.0 | radar-only braking x3 (age 6); age 40: further-drive hard ticks 1 -> 9; age 80: more missed braking against the hindsight-lead oracle (3.3 -> 3.7 s) | keep |
| range fusion (incl. ACC distance as the followed car's range) | 9 | 2.0 (ACC distance 2.1) | braking neutral; lead flips +39 %, target episodes 4 -> 6 | keep for lead stability; droppable at that cost |
| ego-speed alignment (0.149 m/s per code instead of the DBC 0.15) | 0 | 1.x | neutral (onset +12 ms); folded into the decode factor, so it costs no line | keep (no line) |
| state pruning | 7 | 2.0 | unbounded state | required |
| path gate (yaw rate) | 6 | 2.3 (2.2 from 60 m) | back to 2.1 (removed with the 0.4 x match): held-out target episodes 3 -> 4, owner 0 -> 1, further hard ticks 1 -> 2; two road false brakes | candidate: keep, or move into radard as a lateral gate |
| fork compatibility (CP_SP argument, points assigned as a list) | 2 | 2.2 | crashes on sunnypilot | keep (harmless upstream) |

Numbers: [`openpilot_file_parts.json`](../data/analysis/summaries/openpilot_file_parts.json), with the evidence file for
each part.
