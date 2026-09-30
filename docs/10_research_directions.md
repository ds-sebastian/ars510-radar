# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **Gradual-ramp and recovery-tail guard.** The `steady` jump guard catches sudden velocity steps. A slow ramp
   moves its accepted reference along with it, and the decaying tail is then accepted as a recovery, so far leads
   can still produce a false brake ([07](07_velocity_excursions.md)). A guard that compares a track's velocity change
   over 1-3 s with its own range change over the same window, or that rate-limits the accepted reference to plausible
   lead acceleration, targets exactly that pattern. Gate it on reaction time to real closings.
2. **Score and σ as per-point noise.** Use the existence score `16|8` and σ vx `240|7` to set each point's
   measurement noise in a dt-aware track filter, instead of radard's fixed 20 Hz gains.
3. **Vision fusion with a softer camera weight.** The radard patch with `VISION_V_STD_SCALE` 3-4, on new drives.
4. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
5. **A wider ACC-target clip.** Clip the ACC-target object's vRel to 0x235 ± 3 m/s only on gross disagreement,
   where the ACC target is right 86-90% of the time.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **Range-consistency features on the lead alone.** Excursions are defined by velocity that the track's own range
   does not follow. A causal, per-track comparison of integrated vRel against range change, tuned on the lead object
   only (where openpilot's decisions are made), is the most direct warning signal.
2. **Road geometry at onset.** Owner drives show more far-lead disagreement on grades. Host pitch and its rate of
   change (crests and sags, where the radar beam meets the road or passes over the target) are a testable onset
   feature from logged pose.
3. **Fresh drives with the ACC target as witness.** The 50 Hz ACC target (`0x235`) tracks the same lead with its own
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
- **Other cars and firmware:** does every ARS510 car use this layout? Do 0x500 / 0x502 differ per unit?
- **More closed-loop driving** with the steady profile, and a second car or driver.
