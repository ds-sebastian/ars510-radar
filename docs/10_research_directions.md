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
5. **A wider ACC-target clip.** Clip the ACC-target object's vRel to 0x235 ± 3 m/s only on gross disagreement,
   where the ACC target is right 86-90% of the time.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **Road geometry at onset.** Owner drives show more far-lead disagreement on grades. Host pitch and its rate of
   change (crests and sags, where the radar beam meets the road or passes over the target) are a testable onset
   feature from logged pose.
2. **Fresh drives with the ACC target as witness.** The 50 Hz ACC target (`0x235`) tracks the same lead with its own
   filter; its disagreement with the object list on new drives labels excursions without a camera.

## For the decode

- **Class 5, `136|4` and `272|5`:** resolve the candidate cyclist/person associations with target association at
  scale; a measured target height or road-contact reference pins the `272` scale.
- **Heading `208|6`:** compare with independently measured target direction on turning or crossing traffic.
- **0x85 cells 0, 1, 4-7:** road-edge and further lane parameters, against measured lane geometry on roads with
  unequal lane widths ([04](04_metadata_record_0x85.md)).
- **Lateral scale and range zero:** a surveyed lateral offset and a tape-measured gap, parked (the radar lists
  never-moving objects while ego is stopped), pin the last ±10% and ±0.7 m.
- **0x191 descriptor tuple and 0x195 event codes:** associate the descriptor codes and event payloads with
  physical targets and states.

## For the integration

- **Stock openpilot alpha longitudinal:** confirm on a parked car that 0x80 keeps arriving after openpilot's UDS
  radar-disable.
- **Other cars and firmware:** openpilot's fingerprints list `8821F0R01100` for the RAV4 2022 platform, the same
  `8821F0R` series as the documented `8821F0R03100` and the only other one. One capture from such a car confirms the
  layout and adds it to `ARS510_FW_VERSIONS` (detection otherwise relies on the bus-1 fallback, which runs before
  the object list starts). A second unit also shows whether 0x500 / 0x502 differ per unit.
- **More closed-loop driving** with the steady profile, and a second car or driver.
