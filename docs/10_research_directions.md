# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **The steady profile on sunnypilot's planner and fresh drives.** The ramp limiter and far-track settling are
   scored in open-loop replay through openpilot's planner. Replaying the owner's drives through sunnypilot's own
   longitudinal planner, and closed-loop drives with the profile installed, measure the braking the driver feels.
2. **Score and σ as per-point noise.** Use the existence score `16|8` and σ vx `240|7` to set each point's
   measurement noise in a dt-aware track filter, instead of radard's fixed 20 Hz gains.
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

1. **Road geometry at onset.** Owner drives show more far-lead disagreement on grades. Host pitch and its rate of
   change (crests and sags, where the radar beam meets the road or passes over the target) are a testable onset
   feature from logged pose.
2. **Fresh drives with the ACC target as witness.** The 50 Hz ACC target (`0x235`) tracks the same lead with its own
   filter; its disagreement with the object list on new drives labels excursions without a camera.

## For the decode

- **Lateral scale and range zero from slow circles.** A stationary object moves sideways at yaw rate × (range +
  3.6 m) while the car turns. A few minutes of slow circles in an empty lot with parked cars or poles pins the
  lateral scale and the range zero from the gyro alone, no tape measure needed.
- **`272|5` under a known overhead object.** Driving under a bridge or gantry of known clearance, and past parked
  vehicles of known height, relates the code to height. Its ranking of pedestrians below cars points to a size- or
  reflectivity-like quantity.
- **0x85 `64|16`: heading ahead or offset ahead.** Both readings fit the driven path. A road with a known curvature
  change (a curve entry) separates them by where the response appears.
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
