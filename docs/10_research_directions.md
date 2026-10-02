# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **The steady profile on fresh drives and sunnypilot's planner.** The ramp limiter and far-track settling are
   scored in open-loop replay through openpilot's planner. The owner's recorded drives also replay through
   sunnypilot's own longitudinal planner, so candidates can be compared on the planner the car runs; closed-loop drives
   with the profile installed measure the braking the driver feels.
2. **A drift-mode velocity filter.** A per-track filter with a slow velocity-bias state that range observes
   explains the excursions well. Run all the time, it removes most hard radar-only requests in replay but responds
   later and changes which track radard matches to the vision lead. The promising form publishes the native velocity
   normally and switches to the bias-corrected velocity only while the range evidence says a drift is under way.
3. **Vision fusion with a softer camera weight.** The radard patch with `VISION_V_STD_SCALE` 3-4, on new drives.
4. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
5. **ACC-target clip on top of `steady`.** `acc_target_clip_mps=3` clips the ACC-target object's vRel to
   0x235 ± 3 m/s. In replay on top of the steady profile it cuts radar-only episodes 6 → 5 and paired roughness by
   0.0004 m/s² (95% interval below zero) for 0.001 s of lag, and the owner drives' hard radar-only requests go
   16 → 0 ([`ramp_limiter.json`](../data/analysis/summaries/ramp_limiter.json), `acc_clip_followup`). Fresh drives
   decide whether it joins `steady`.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **A far-range truth drive.** Following a second car that logs GPS speed at 40-120 m gives true far vRel, which
   camera and range cannot: vision fades beyond 60-80 m and range needs 3-4 s to resolve 2 m/s there. One hour settles
   the excursion mechanism, calibrates σ vx `240|7` and gives the drift-mode filter a target.
2. **The first second of an excursion.** Velocity steps of a consistent size and sign at onset would point to
   wrong-branch Doppler measurements leaking into the tracker; ordinary-sized steps point to low-SNR tracking
   ([07](07_velocity_excursions.md#what-the-radars-waveform-allows)).
3. **Ego-speed waveform modes.** The data sheet's three ego-speed bandwidths predict steps in the range noise floor
   at fixed ego speeds. Finding them, and the excursion rate in each mode, ties drift risk to a radar setting.
4. **Fresh drives with the ACC target as witness.** The 50 Hz ACC target (`0x235`) tracks the same lead with its own
   filter; its disagreement with the object list on new drives labels excursions without a camera.

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
