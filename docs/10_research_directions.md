# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **Resolve the range scale, then put range in the filter.** The radar ACC target's fine range and speed agree at
   nominal units (ratio 1.007 over 3 s windows), but the object list's range changes 10-20% more than either speed
   integrates, while it matches ego speed on near-stationary targets. Until that is resolved, `fused` keeps range out
   of its Kalman filter and only smooths it with range fusion ([07](07_velocity_excursions.md#fused-speed-filter-fused-profile)).
2. **More of the lead covered by the radar's own trackers.** The ACC target exists for about 57% of radar-lead time and
   5% beyond 80 m; the summaries add far coverage up to 80 m. Far tracks with neither depend on the object list and its
   wide error alone, which is where `fused`'s remaining radar-only braking comes from. Finding when and why the radar
   drops or delays its target (range, speed, curve, camera state) tells whether coverage can grow.
3. **Is the radar's ACC target camera-assisted?** The radar sends it ([05](05_acc_target_and_support.md)), but it
   receives lane-like camera data. Moments when the camera's messages to the radar go stale (glare, tunnels,
   startup), or one drive with the camera covered, show whether its velocity depends on the camera.
4. **Physical units for the uncertainty fields.** `240|7` (speed) and `224|7` (range) are calibrated against the
   radar's ACC target, which is the radar's own estimate. An independent reference (a second car with a GPS logger,
   or a known far target) would give them physical units and test `fused`'s weights directly.
5. **Do the weighting in radard.** A radard that accepts a per-point speed variance would let this interface pass the
   radar's values through like the other radar interfaces, and would help every radar with a reported uncertainty.
   The optional radard patch (vision fusion, `VISION_V_STD_SCALE` 3-4) is a related experiment.
6. **Use the radar's own lead acceleration.** 0x235 byte 2 (relative acceleration) tracks lead acceleration better
   than radard's derived `aLeadK` against an independent reference (correlation 0.64 vs 0.56, RMS 0.68 vs 0.80 m/s²)
   and about 0.35 s earlier, with less wobble. radard ignores radar-provided `aRel` for every car; a fork-side radard
   change that uses it would test whether the brake-release-brake feel while following eases.
7. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
8. **Road miles with `fused`.** The replay results ([11](11_profiles_compared.md)) need closed-loop confirmation:
   drives with flagged moments, ideally from a second car, driver or radar firmware.

## Learn from Toyota's own longitudinal control

Toyota's stock ACC on this car brakes and slows well for a lead in its own lane, but holds on to a lead that leaves
for a turning lane. Those are probably two different parts of its pipeline, and the second is not what openpilot
should copy:

- **Target choice (Toyota's weak point).** The radar picks its ACC target ([05](05_acc_target_and_support.md)) and
  keeps a departing car until its centre is a median 1.64 m off-axis (middle half 0.67-2.16 m; 22 departures). Measured
  against the radar's own lane boundary from the 0x85 curve cells, the release comes when the car's centre is a median
  0.29 m inside that line (21 departures): the rule is "keep the target until its centre reaches my lane line". On the fresh drives openpilot's model moved to a new lead 1.5 s and more than
  6 s before the radar's target did (n = 3). openpilot's model, which sees lanes, is the
  better lead chooser; the `fused` and `anchor` profiles keep it in charge and never follow the radar's choice.
- **The signal (Toyota's strength).** The radar's ACC speed is smooth and consistent with range during excursions,
  and 0x235 also carries a filtered relative acceleration. `anchor` already uses the speed as a bound.
- **The control law (unknown).** How Toyota turns distance, closing speed and relative acceleration into a braking
  request is not visible under openpilot longitudinal.

Proposed study:

1. **Record stock ACC.** 20-30 minutes of mixed traffic with Toyota's ACC in control and the comma device logging
   (openpilot longitudinal off). The camera's `ACC_CONTROL` (0x343) command then appears next to the radar's target.
2. **Fit Toyota's law.** Model the requested acceleration from the radar's ACC target (distance, closing speed,
   relative acceleration), ego speed and the following-distance setting; compare it with openpilot's planner on the
   same moments (replayed with each radar profile).
3. **Separate signal from tuning.** Replay openpilot's planner fed with the radar's ACC values for the in-lane lead,
   and Toyota's fitted law fed with openpilot's lead. If the planner with Toyota's signal already behaves like Toyota,
   the remaining gap is radar handling (this repo); if not, it is planner tuning, which belongs in the fork's
   longitudinal settings, not the radar interface.
4. **Within-lane decisions.** Score both on in-lane braking events (onset, peak deceleration, jerk, gap at the end)
   and on lane-change / turn-lane departures, so a Toyota-like tune does not bring Toyota's sticky lead selection with it.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **A far-range truth drive.** Following a second car that logs its own speed (a second comma device, or a 5-10 Hz GNSS logger) at 40-120 m gives the lead's true velocity.
   The video-looming reference covers 40-110 m but has few windows beyond 100 m and shares the camera with the vision model and possibly the ACC target; a synchronized comparison with bounded reference accuracy, vehicle geometry and target identity
   can test it independently.
2. **The first second of an excursion.** Velocity steps of a consistent size and sign at onset would point to
   wrong-branch Doppler measurements leaking into the tracker; ordinary-sized steps point to low-SNR tracking
   ([07](07_velocity_excursions.md#what-the-radars-waveform-allows)).
3. **Ego-speed waveform modes.** The data sheet's three ego-speed bandwidths predict steps in the range noise floor
   at fixed ego speeds. Finding them, and the excursion rate in each mode, ties drift risk to a radar setting.
4. **The radar's ACC target as a reference.** Associate the radar's 50 Hz ACC target (`0x235`) with the
   native object by geometry before comparing velocity. Factory-camera dependence and independent motion
   anchors determine whether this supplies physical supervision; velocity agreement alone cannot establish it.

## For the decode

- **Lateral scale and range zero from slow circles.** A stationary object moves sideways at yaw rate × (range +
  3.6 m) while the car turns. A few minutes of slow circles in an empty lot with parked cars or poles pins the
  lateral scale and the range zero from the gyro alone, no tape measure needed.
- **`272|5` under a known overhead object.** Driving under a bridge or gantry of known clearance, and past parked
  vehicles of known height, relates the code to height. Its ranking of pedestrians below cars points to a size- or
  reflectivity-like quantity.
- **0x85 curve cells: units and the remaining fields.** Heading `48|16` and curvature `64|15` are bounded to about
  ±15 %. A camera lane polynomial with matched timing, or a drive along a surveyed curve of known radius, pins both
  units; the flag `79|1` and the fields `0|9`, `10|10`, `24|4` and `80|6` have structure but no name
  ([04](04_metadata_record_0x85.md#lane--road-boundary-curves)).
- **Class 5:** a few recorded passes of a cyclist and of a pedestrian confirm the bicycle reading of its size and
  speed.
- **0x195 `q10` with brake pressure:** the logged brake pressure or the brake-assist state next to the event code
  names the deceleration quantity. The 0x191 descriptor tuples follow speed regime; a drive through the ACC
  following-distance settings shows whether they encode a mode.

## For the integration

- **Stock openpilot alpha longitudinal:** confirm on a parked car that 0x80 keeps arriving after openpilot's UDS
  radar-disable.
- **Other cars and firmware:** openpilot's fingerprints list `8821F0R01100` for the RAV4 2022 platform, the same
  `8821F0R` series as the documented `8821F0R03100` and the only other one. One capture from such a car confirms the
  layout and adds it to `ARS510_FW_VERSIONS` (detection otherwise relies on the bus-1 fallback, which runs before
  the object list starts). A second unit also shows whether 0x500 / 0x502 differ per unit.
- **More closed-loop driving** with the `fused` profile (the default), and a second car or driver.

## Signals that would help most

What other openpilot radar interfaces read from their radars, and what the ARS510 decode still lacks
([`opendbc/car/*/radar_interface.py`](https://github.com/commaai/opendbc/tree/master/opendbc/car)):

| what radard gets elsewhere | examples | ARS510 today | what would close the gap |
|---|---|---|---|
| per-track **measured vs predicted** state (`RadarPoint.measured`) | Toyota `VALID` + `SCORE`, Rivian `STATE`, Tesla `Meas` | `107\|1` = predicted (◐) and `16\|8` = existence probability (◐) are decoded; the interface still sends `measured=True` | publish them like Tesla does; excursions occur on *measured* records, so this is hygiene, not a fix |
| **new-track** flag | Toyota `NEW_TRACK`, Rivian new states | derived from the age field (● reliable) | none needed |
| the radar's own **relative** speed | `REL_SPEED` on Toyota, Honda, Hyundai, Chrysler | over-ground speed (`64\|10`) minus 0xB4 ego speed | a relative-speed or Doppler field would remove the ego-speed dependency and its scale/timing questions |
| relative **acceleration** | Hyundai `REL_ACCEL`, Tesla `LongAccel` | `84\|10` acceleration-like (○ scale, lags 0.5-1 s) | calibrate `84\|10` against independent motion |
| **lateral speed** | Tesla `LatSpeed` | `74\|10` (◐, 0.98 against the gyro) | already published as `yvRel` where forks carry it |
| radar **fault / blockage** status | Honda `RADAR_STATE`, Tesla `sensorBlocked` | not decoded; only "no record for 0.5 s" is reported | on eight drives the radar's own slow messages change rare bits only at start-up, except 0x680 bits 18 and 57; a drive in rain, spray or with a dirty bumper decides whether either is a blockage flag |
| measurement **uncertainty** | (rarely exposed) | `224/232/240/248\|7` family, no physical units | units would let radard weight radar against vision |
| plain **DBC** decode through `CANParser` | every upstream interface | a 742-byte record split over 106 frames: needs a small reassembler | none on the CAN side; the reassembler is ~80 lines with a CRC check |

The closest relative in openpilot is the Tesla Model 3's Continental radar (`tesla_radar_continental`): an 89-line
pass-through of distance, relative speed and acceleration, lateral position and speed, `Tracked`, `Meas`, existence
and obstacle probabilities, class, size, height and four uncertainty sigmas, plus a status message (blocked,
unavailable, dynamics error). The ARS510 slot follows the same Continental pattern, which is how its existence,
predicted-record and uncertainty fields were identified ([03](03_slot_fields.md#uncertainty-and-quality)). What it
still lacks for a Tesla-sized interface is a **fault / blockage status** (to report a dirty or misaligned radar) and an
explanation of the velocity excursions, which occur on measured records with ordinary uncertainty beyond 40 m. They
are the wide far-range error that `240|7` reports, so the `fused` profile weights each reading by that uncertainty
and by the radar's internal trackers (ACC target, summaries) instead of adding tuned guards
([07](07_velocity_excursions.md#fused-speed-filter-fused-profile)).

## Towards an upstream (comma) interface

The integration works on every fork without changing openpilot, but upstream openpilot prefers small radar interfaces
that pass the radar's own values through and leave filtering to radard. Open work before proposing it there:

1. **Decide how much filtering an upstream version needs.** The `fused` profile is the candidate: the base decode,
   range fusion and one speed filter whose weights come from the radar's own uncertainty fields and internal
   trackers, about 30 lines in place of five tuned layers. In replay it brakes falsely less than `anchor` (held-out
   48 → 30 hard ticks, owner target episodes 5 → 0) with an unbiased closing speed
   ([`fused_filter.json`](../data/analysis/summaries/fused_filter.json)). It is the default; it needs more road miles, and the range/speed
   scale of the object list ([06](06_accuracy.md)) before range can join the filter. The same weighting could live
   in radard instead (per-point speed variance), which would leave the interface a pass-through like the others.
2. **Decode `measured` and fault status** (above), so the interface looks like the others.
3. **Size and style.** Today: decoder ~1,000 lines including research options. An upstream port needs the
   reassembler, slot decode, the chosen profile and tests only, in opendbc's style, with fingerprint-based detection
   (`8821F0R03100`; `8821F0R01100` unconfirmed).
4. **Process replay coverage.** A route segment with the radar in openpilot's process-replay tests, and a car test
   on at least one more vehicle or firmware.
5. **Alpha longitudinal compatibility.** Confirm on a parked car that 0x80 keeps arriving after openpilot's UDS
   radar-disable request.
