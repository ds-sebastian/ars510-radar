# 10. Research directions

The most promising next steps, ordered by how directly they would improve the radar in openpilot.

## For a better ride

1. **Lane weights inside radard's matching.** The ego-lane weight `156|4` ([03](03_slot_fields.md#lane-assignment))
   is the radar's own in-path estimate. Multiplying radard's match likelihood by it (where the weights are present,
   about 40% of lead ticks) gives radard the lateral preference it lacks.
2. **Score and σ as per-point noise.** Use the existence score `16|8` and σ vx `240|7` to set each point's
   measurement noise in a dt-aware track filter, instead of radard's fixed 20 Hz gains.
3. **Vision fusion with a softer camera weight.** The radard patch with `VISION_V_STD_SCALE` 3-4, on new drives.
4. **Lead acceleration in fork planners.** StarPilot extrapolates `aLeadK` unchanged above 35 mph; a decaying
   extrapolation or an `aLeadTau` floor for radar leads (as in stock openpilot) removes the brake-then-accelerate swing.
5. **A wider ACC-target clip.** Clip the ACC-target object's vRel to 0x235 ± 3 m/s only on gross disagreement,
   where the ACC target is right 86-90% of the time.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **Reconstruct the tracker's innovations.** The acceleration fields lag velocity like the outputs of an α-β(-γ)
   filter. Fitting that filter to (x, v, a) sequences recovers the per-cycle velocity and range innovations. A biased
   Doppler measurement should appear as a run of same-sign velocity innovations that range innovations do not share.
2. **Lane-weight dynamics at onset.** Whether drifts start when weight moves between lanes (a target near a lane
   edge, or a return from the neighbouring lane).
3. **The measurement-state field at 264.** Settled values map to range bands; near-scan-only readings at far range
   are enriched during drifts. Test it as an onset feature with its full width (`264|5` plus `269|3`).
4. **Temporal models on all raw inputs.** Sequence models over slot bits, 0x85 cells and the auxiliary frames, trained
   on range-closure labels with training-only normalisation and route-held-out evaluation.

## For the decode

- **Class 5, `136|4` and `272|5`:** confirm the class names against video at scale, the class-confidence reading and
  the height-like scale.
- **Heading `208|6` as its own state:** it differs from the instantaneous velocity angle on young and slow tracks;
  compare it with the position-track heading.
- **0x85 cells 0, 1, 4-7:** road-edge and further lane parameters ([04](04_metadata_record_0x85.md)).
- **Lateral scale and range zero:** a surveyed lateral offset and a tape-measured gap, parked (the radar lists
  never-moving objects while ego is stopped), pin the last ±10% and ±0.7 m.
- **0x191 descriptor tuple and 0x195 event codes.**

## For the integration

- **Stock openpilot alpha longitudinal:** confirm on a parked car that 0x80 keeps arriving after openpilot's UDS
  radar-disable.
- **Other cars and firmware:** does every ARS510 car use this layout? Do 0x500 / 0x502 differ per unit?
- **More closed-loop driving** with the steady profile, and a second car or driver.
