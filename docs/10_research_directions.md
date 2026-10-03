# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **Anchor the range as well.** The `anchor` profile bounds the ACC-target track's velocity, but during an excursion
   the track's range can still slide (drive E: 46 → 33 m while the radar's ACC target stayed at 46 m). 0x237 carries a
   fine distance (0.02 m per code for changes); its absolute origin and scale need one calibration against the
   object list or a measured distance before it can bound dRel the same way.
2. **More of the lead covered by the anchor.** The radar's ACC target exists for about 57% of radar-lead time and 5%
   beyond 80 m, so far excursions still depend on the `steady` layers. Finding when and why the radar drops or
   delays its target (range, speed, curve, camera state) tells whether coverage can grow.
3. **Is the radar's ACC target camera-assisted?** The radar sends it ([05](05_acc_target_and_support.md)), but it
   receives lane-like camera data. Moments when the camera's messages to the radar go stale (glare, tunnels,
   startup), or one drive with the camera covered, show whether its velocity depends on the camera.
4. **Uncertainty units before filter tuning.** `240|7` tracks the size of the object list's disagreement with an
   optical reference ([03](03_slot_fields.md#kinematics)) but a Kalman filter weighted by it does not reproduce the
   radar's own ACC velocity, so it is not that filter's measurement variance. Independent motion is needed to give it
   physical units.
5. **Vision fusion with a softer camera weight.** The radard patch with `VISION_V_STD_SCALE` 3-4, on new drives.
6. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
7. **Simplify further.** Dropping the 8 m/s jump guard changes no scored outcome on the 34 replay drives or on the fresh
   drives under two unchanged sunnypilot schedules (hard ticks 7 → 7, episodes 6 → 6, identical responses;
   [07](07_velocity_excursions.md#fresh-jump-guard-simplification-comparison)). Closed-loop driving would show whether
   it can be removed; it stays for now as the only single-record spike guard.

## Learn from Toyota's own longitudinal control

Toyota's stock ACC on this car brakes and slows well for a lead in its own lane, but holds on to a lead that leaves
for a turning lane. Those are probably two different parts of its pipeline, and the second is not what openpilot
should copy:

- **Target choice (Toyota's weak point).** The radar picks its ACC target ([05](05_acc_target_and_support.md)) and
  keeps it until the car is clearly out of its predicted path. On the fresh drives openpilot's model moved to a new
  lead 1.5 s and more than 6 s before the radar's target did (n = 3). openpilot's model, which sees lanes, is the
  better lead chooser; the `anchor` profile keeps it in charge and never follows the radar's choice.
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
- **0x85 `64|16`: encoding and boundary reference.** Anchor the high-bit transitions and the selected boundary to
  known road geometry before calibrating an angle, offset or lookahead distance. Curvature association supplies
  a useful starting point ([04](04_metadata_record_0x85.md#road-direction-association-bits-64-79)).
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
- **More closed-loop driving** with the `anchor` profile, and a second car or driver.

## Signals that would help most

What other openpilot radar interfaces read from their radars, and what the ARS510 decode still lacks
([`opendbc/car/*/radar_interface.py`](https://github.com/commaai/opendbc/tree/master/opendbc/car)):

| what radard gets elsewhere | examples | ARS510 today | what would close the gap |
|---|---|---|---|
| per-track **measured vs predicted** state (`RadarPoint.measured`) | Toyota `VALID` + `SCORE`, Rivian `STATE` new / updated / coasting, Hyundai `STATE` | always `measured=True`; candidates `107\|1` (coasting-like), existence score `16\|8`, `109\|3` | decode which records are fresh measurements and which are coasted predictions |
| **new-track** flag | Toyota `NEW_TRACK`, Rivian new states | derived from the age field (● reliable) | none needed |
| the radar's own **relative** speed | `REL_SPEED` on Toyota, Honda, Hyundai, Chrysler | over-ground speed (`64\|10`) minus 0xB4 ego speed | a relative-speed or Doppler field would remove the ego-speed dependency and its scale/timing questions |
| relative **acceleration** | Hyundai `REL_ACCEL`, Tesla `LongAccel` | `84\|10` acceleration-like (○ scale, lags 0.5-1 s) | calibrate `84\|10` against independent motion |
| **lateral speed** | Tesla `LatSpeed` | `74\|10` (◐, 0.98 against the gyro) | already published as `yvRel` where forks carry it |
| radar **fault / blockage** status | Honda `RADAR_STATE`, Tesla `sensorBlocked` | not decoded; only "no record for 0.5 s" is reported | find the radar's blocked / misaligned / degraded bits (candidates in the 0x190-0x198 and 0x500-0x502 families) |
| measurement **uncertainty** | (rarely exposed) | `224/232/240/248\|7` family, no physical units | units would let radard weight radar against vision |
| plain **DBC** decode through `CANParser` | every upstream interface | a 742-byte record split over 106 frames: needs a small reassembler | none on the CAN side; the reassembler is ~80 lines with a CRC check |

The two that matter most for driving are the **measured / coasting state** (radard and the planner could ignore
coasted velocity, which is where excursions are suspected to come from) and a **fault / blockage status** (to report
a dirty or misaligned radar instead of silently trusting it).

## Towards an upstream (comma) interface

The integration works on every fork without changing openpilot, but upstream openpilot prefers small radar interfaces
that pass the radar's own values through and leave filtering to radard. Open work before proposing it there:

1. **Decide how much filtering an upstream version needs.** `stock` plus only the ACC anchor uses nothing but signals
   the radar provides. In replay it removes most nuisance hard braking (held-out 93 → 46 ticks, owner drives 17 → 2,
   fresh drives 16 → 2-3) but keeps stock's lead-switch roughness (2,468 vs 1,781 switches for `steady`), answers 5
   of 167 driver brakes more than 0.15 s later, and leaves 3 vs 1 hard ticks on the further drives
   ([`acc_anchor.json`](../data/analysis/summaries/acc_anchor.json)). So the anchor is the most valuable single
   piece, and the remaining work is either keeping a few of the `steady` layers or moving their job into radard
   (for example the `measured` flag below, so coasted velocity is weighted down).
2. **Decode `measured` and fault status** (above), so the interface looks like the others.
3. **Size and style.** Today: decoder ~1,000 lines including research options. An upstream port needs the
   reassembler, slot decode, the chosen profile and tests only, in opendbc's style, with fingerprint-based detection
   (`8821F0R03100`; `8821F0R01100` unconfirmed).
4. **Process replay coverage.** A route segment with the radar in openpilot's process-replay tests, and a car test
   on at least one more vehicle or firmware.
5. **Alpha longitudinal compatibility.** Confirm on a parked car that 0x80 keeps arriving after openpilot's UDS
   radar-disable request.
