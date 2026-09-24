# 10. Open questions and next experiments

Ordered by how much each would move openpilot integration forward.

1. **Resolve velocity interpretation, timing and quality before adding consumer defences.** Independently identified stationary approaches, ego-acceleration response and same-object companion-message checks can distinguish reference-frame/latency mistakes from tracker behaviour. The newer stationary test is less favourable, and a first visual review split its 30–60 m failures between a creeping queue (video label wrong) and a radar range walk ([13](13_evidence_review.md)). A better stationarity label is needed before that band says anything about the radar. Radar-only filters and simple vision blends failed in the tested families ([06](06_known_limitations.md)). Later consumer ideas, not the current next experiment:
   - *Camera expansion rate as a fast second witness.* In this work, box growth is what separated confirmed closings from excursions offline. An on-device equivalent could come from the vision model's lead-distance trend, or a cheap image-scale tracker on the lead box. The question is whether the model's own lead distance *trend*, not its level or velocity, is fast and unbiased enough.
   - *Asymmetric gating.* Allow radar to strengthen braking only when vision's lead distance is not clearly opening over the last ~1 s. Leave radar free to add caution when vision under-reads.
   - *Learn the excursion signature from an optional instrumented reference,* with a measured timing/error budget (see [09](09_testing_a_new_drive.md#7-optional-instrumented-reference)).
2. **Does stock openpilot's alpha-longitudinal path silence the radar's bus-1 object output?** It sends a UDS communication-control to 0x750. If it does, radar tracks and openpilot longitudinal can't coexist on stock openpilot. On the logged FrogPilot build the objects kept flowing. Check with one short drive.
3. **Lateral gate for radard.** No lateral sanity gate exists today, so an adjacent-lane object is accepted as lead when the true lead is missing. This matters for any radar, not just the ARS510.
4. **Lateral scale.** ±10% today: lane peaks give ~64 codes/m, the camera ~70. Pin it with a surveyed lateral offset (a parked car at a measured offset), or with a radar-only method that doesn't depend on assumed lane width.
5. **Range zero on a flat road with a measured gap.** Stop behind a car on level ground and measure the bumper gap with a tape. That separates the +0.7 m hilly-road reading from camera pitch.
6. **trackId beyond 60 m.** The camera identity reference fails there, so re-link precision at 60–120 m is unverified. It needs a better far identity reference (narrow camera with a better tracker, or two-car truth).
7. **What 0x85 encodes.** Clusters or detections? A second list? Pair fill counts versus scene clutter is a cheap first test.
8. **State `0|2`, score-like `16|8`, and the 0x191 descriptor tuple.** Test state transitions and future error variance after matching identity, age, range and ego motion. `2|6` is the physical slot index, not an object category; its apparent position bias was allocation confounding.
9. **0x192 as a sanity signal.** It is the radar's own smoothed target distance with a lane bin. It can't be a vRel source, but "radar ACC also has a target in my lane near this distance" might gate false leads.
10. **Other cars and firmware.** Does every ARS510 car use the same layout? Are 0x500 / 0x502 unit-specific?

## New leads from the visual tour ([11](11_visual_tour.md))

- **A track-health signal?** In the last seconds before a settled track disappears, candidate fields `256|5` (existence-like) drift down and `264|5` (uncertainty-like) drift up. In the last ~1 s, velocity jumps grow: p99 doubles, and one night track read +61 m/s before being dropped. It is exploratory and confounded by range. If it holds up range-matched and pre-registered, it would be the first radar-internal quality cue.
- **Missed motion.** Some radar-attributed disagreements are native vRel staying flat while the radar's own range and the camera both see a real change. How often does native velocity *lag* real changes, not just invent them?
- **`UNK_168_10`** takes only 0 / 768 / 1023, a flag word. 0 is a little more common on the nearest in-lane object. Object class? ACC relevance?

## Retain, but do not overclaim

- Native little-endian geometry fields and lifecycle are strong starting points; exact velocity contract and exceptional states remain open. The range zero and lateral scale have the limits in [02](02_object_record_0x80.md).
- Ground-referenced `64|10` minus ego is the leading velocity interpretation. Simple bit-step tests do not rule out state/timing/association errors.
- No usable confidence/finalised-speed/correction decoder has been established. Bounded negative searches do not prove absence.
- Tested filters did not pass the false-braking/real-closing trade-off. This is not a proof against every possible radar-only method.
