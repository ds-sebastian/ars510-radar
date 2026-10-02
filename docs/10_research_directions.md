# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **The steady profile on fresh drives.** Native STEADY, OPENPILOT and ACC-clip points compare through
   sunnypilot's original RadarD and planner under two fixed prospective schedules, with the clip passing the six
   owner subgates in both ([07](07_velocity_excursions.md#sunnypilot-profile-comparison)). Closed-loop drives with
   the profile installed measure the braking the driver feels and test transfer beyond these prior-used drives.
2. **A calibrated-variance velocity filter.** `240|7` is an error scale of about 0.05 m/s per count ([03](03_slot_fields.md#kinematics)), so a per-track filter with a slow
   bias state can weight the velocity by its measured uncertainty. With range-rate as the second measurement it removes false closings (1.4 pp overall, 15 → 11% beyond 80 m
   against the video reference) but moves about a third of real onsets by more than 0.15 s; acting only on a significant bias leaves onsets untouched and removes little.
   Range fusion plus `240|7`-driven smoothing responds 62 ms earlier than `steady` in replay but leaves more hard radar-only ticks (153 against 85 on the development chains).
3. **Vision fusion with a softer camera weight.** The radard patch with `VISION_V_STD_SCALE` 3-4, on new drives.
4. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
5. **ACC-target clip on top of `steady`.** `acc_target_clip_mps=3` clips the ACC-target object's vRel to
   0x235 ± 3 m/s. In replay on top of the steady profile it cuts radar-only episodes 6 → 5 and paired roughness by
   0.0004 m/s² (95% interval below zero) for 0.001 s of lag, and the owner drives' hard radar-only requests go
   16 → 0 ([`ramp_limiter.json`](../data/analysis/summaries/ramp_limiter.json), `acc_clip_followup`). Fresh drives
   decide whether it joins `steady`. Through sunnypilot's original consumers, D1 episodes go 5 → 4 under both
   schedules, with D2 unchanged; this is a conditional owner comparison, separate from physical velocity and full
   real-closing acceptance ([summary](../data/analysis/summaries/sunnypilot_profile_comparison.json)).
6. **ACC-velocity fusion (not in the shipped profiles).** Combining the matched ACC target's closing speed with the object-list velocity by measured inverse variance (weight 0.76-0.82
   on the ACC target) on top of `steady`: the owner drives' hard radar-only requests go 16 → 0 and target episodes 6 → 1, but on 20 held-out chains hard ticks go 53 → 57 and mean
   braking response is 0.145 s later; the ACC target is a smoother, differently timed filter and its coverage is 57% of radar-lead time. Fresh drives decide whether it is worth an
   opt-in profile ([`video_truth.json`](../data/analysis/summaries/video_truth.json)).
7. **Camera-assisted veto.** The one measured way to remove false closings without moving real onsets is to limit native closing to the camera's own velocity of the same second
   ([07](07_velocity_excursions.md#measured-against-video-truth)): a third of false closings at about 10 ms mean onset lag in offline replay. It needs a camera-side lead-velocity
   process and an input path into radard, and must be tested for lost tracks, wrong vehicles, night and rain.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **A far-range truth drive.** Following a second car that logs its own speed (a second comma device, or a 5-10 Hz GNSS logger) at 40-120 m gives the lead's true velocity.
   The video-looming reference covers 40-110 m but has few windows beyond 100 m and shares the camera with the vision model and possibly the ACC target; one hour of truth
   checks it absolutely and replaces the camera as the label source.
2. **The first second of an excursion.** Velocity steps of a consistent size and sign at onset would point to
   wrong-branch Doppler measurements leaking into the tracker; ordinary-sized steps point to low-SNR tracking
   ([07](07_velocity_excursions.md#what-the-radars-waveform-allows)).
3. **Ego-speed waveform modes.** The data sheet's three ego-speed bandwidths predict steps in the range noise floor
   at fixed ego speeds. Finding them, and the excursion rate in each mode, ties drift risk to a radar setting.
4. **Fresh drives with the ACC target as witness.** Associate the filtered 50 Hz OEM target (`0x235`) with the
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
- **More closed-loop driving** with the steady profile, and a second car or driver.
