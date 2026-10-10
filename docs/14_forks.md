# 14. The radar on openpilot forks

The installer works on every fork ([08](08_openpilot_integration.md)), but a fork decides what its planner does with
a radar lead. This page reads the radard and MPC lead handling of sunnypilot, FrogPilot and StarPilot, runs their own
code on two recorded drives and on synthetic cases, and says what the ARS510 changes on each.

Numbers: [`fork_lead_handling.json`](../data/analysis/summaries/fork_lead_handling.json). Tools:
[`tools/fork_lead/`](../tools/fork_lead) ([how to run them](09_tools_and_data.md#compare-forks)). Marks: ● read from the
fork's source, ◐ from the replay and synthetic runs below, which use a proxy for the planner (see [method](#method-and-limits)).

**In short**

- All three forks take the same tracks, and all three still let the **camera pick the lead**: a radar track becomes the
  lead only if it matches the vision lead (below 4 m/s every fork also takes a close radar track). What differs is what
  the planner then does with the track's speed and acceleration, and that one fork also accepts radar-only leads at speed.
- **sunnypilot** (openpilot's own path) hands the MPC the radar's speed and acceleration. It is the fork most exposed to
  the radar's speed errors ([07](07_velocity_excursions.md)) and the one `fused` helps most: events with a false braking
  demand of at least 1 m/s² fall from 90 to 14 per hour.
- **FrogPilot** with its default Human Following uses the radar for range and the lead's speed at the first instant only;
  the vision model supplies the future and the radar's acceleration is ignored. It barely reacts to radar speed errors
  (◐), and its first braking request came within 0.06 s of vision-only's in all 10 lead-braking events checked. It also takes
  in-lane radar-only leads.
- **StarPilot** uses the same vision-model path until a lead brakes harder than 0.5 m/s² or closes within 7 s, then
  switches to the openpilot path through two speed and acceleration filters whose state can be stale (◐). With warm
  filters it reacts to a radar speed error about 60% as much as sunnypilot; on the drives with `raw` it added about as much (75 against 90 events per hour of ≥ 1 m/s², 328
  against 291 of ≥ 0.5).
- On sunnypilot, FrogPilot with Human Following off and StarPilot, `fused` removes most of what `raw` adds (≥ 1 m/s²
  events 90 → 14 and 75 → 4 per hour); on FrogPilot's default path both profiles add little (6.5 and 9.8 events per hour
  against vision only). The ACC target is what `fused` leans on ([12](12_kalman_filter.md)).

## What each fork does with a radar lead (●)

Sources read: sunnypilot `master` 3323aaf, FrogPilot `FrogPilot-Staging` 6976ff3 (a compiled release branch; radard and
planner are readable), StarPilot `StarPilot` 2a12dbd.

| | sunnypilot | FrogPilot | StarPilot |
|---|---|---|---|
| radard | openpilot's (its change is Hyundai-only) | openpilot's plus the rows below | openpilot's plus the rows below |
| camera confirmation of a lead | peak-held probability (0.2 s decay) > 0.5 | per-frame probability > 0.35 (setting, 0.25-0.5) | peak-held probability (0.2 s decay) > 0.35 (setting, 0.25-0.5) |
| match of a track to the vision lead | distance, lateral and speed weights; distance and speed sanity | the same | the same plus a lateral sanity check; keeps the previous track if it only just misses the gate |
| radar-only lead | ego below 4 m/s, track within ±1 m laterally and 0.75-25 m ahead | the same, plus any moving in-lane track after about 0.5 s with no camera lead (the "far lead") | the same as sunnypilot; a 3-frame persistence gate after standstill |
| lead acceleration decay (`aLeadTau`) | 1.5 s | 1.5 s | 0.6 s |
| lead path given to the MPC | openpilot's: radar `dRel`, `vLead`, `aLeadK`, decaying | Human Following on (default, model v9): radar `dRel` and `vLead` at t = 0, the model's deltas after; `aLeadK` unused. Off: openpilot's | the same vision-model path (radar sets the start, the model the deltas) while the lead brakes under 0.5 m/s² and does not close within TTC 7 s; otherwise openpilot's, through `lead_v_filter` / `lead_a_filter` |
| smoothing in the planner | none | none | lead speed and acceleration filters: 0 s below 47 mph, 1.2 s at 65 mph and above |
| radar extras | none | adjacent-lane leads (setting) and lane-change matching (default on with a radar) | adjacent-lane leads (setting), lane-change matching, a stopped-neighbour hint ("Force Stop"), and 11 vision-lead comfort caps that do not apply to radar leads |

## What that does with this radar (◐)

**A radar speed error, with the truth known.** A lead pace-matched to the ego car at 30 m/s; the radar's closing speed
reads too fast (it ramps up over 1.5 s, holds 1 s, decays over 2 s, the shape in [07](07_velocity_excursions.md)).
Extra braking demand (m/s², proxy) over the same fork without the error, gap 45 m:

| error | sunnypilot | FrogPilot, Human Following off | StarPilot | FrogPilot, default |
|---|---|---|---|---|
| −1 m/s | 0.64 | 0.64 | 0.32 | 0.07 |
| −2 m/s | 1.24 | 1.24 | 0.75 | 0.15 |
| −4 m/s | 2.33 | 2.33 | 1.47 | 0.30 |

At 70 m the results are within 0.05 of these, except −1 m/s, which falls to 0.22 (0.01 on FrogPilot's default).

**The same on real drives** (U1 and U2, 29-30 min with a radar lead and an ACC target). Each fork on a profile against
the same fork given the radar's ACC target alone; events per hour of extra demand of at least 1.0 (0.5) m/s²:

| | `raw` | `fused` |
|---|---|---|
| sunnypilot | 90 (291) | 14 (24) |
| FrogPilot, Human Following off | 90 (291) | 14 (24) |
| StarPilot | 75 (328) | 4 (33) |
| FrogPilot, default | 0 (2) | 0 (2) |

`fused` cuts sunnypilot's and FrogPilot-off's large events about six-fold and StarPilot's about eighteen-fold. The small
FrogPilot numbers come from that path discarding the radar's acceleration, so little is left to be wrong. In 10 lead-braking events seen by the ACC target its first braking request came within 0.06 s of vision-only's (StarPilot: 9 of 10, and one response only the radar made). On sunnypilot's path the proxy puts the radar's response
later than vision's in 6 of the 10, the opposite of the real-planner replay in [08](08_openpilot_integration.md#radar--vision-against-vision-only-replay);
the proxy leaves out the planner's jerk limits and the vision model's own acceleration forecast, so it cannot settle
timing (○). Against vision only, sunnypilot with `raw` adds 94 braking events of at least 1.0 per hour,
FrogPilot-off 92, StarPilot 86, FrogPilot default 6.5; with `fused` 13, 15, 10 and 10, and 7, 7, 3 and 0 per hour
are braking that vision alone would have asked for and the radar did not.

**Radar-only leads.** Of the lead time, 82-85% has a radar-sourced lead and 0.5-0.7% a radar-only one, on every fork.
FrogPilot's far-lead path takes an in-lane moving track the camera does not see: with nothing else in the scene it
did so after 0.5 s in the synthetic case (peak demand 0.74 m/s² for a 10 m/s slower object, 1.49 for 20 m/s slower),
and sunnypilot and StarPilot did not. On the drives it produced 15 leads in 37 min that no other fork took (median
0.2 s, longest 1.7 s); 4 would have asked for at least 1.0 m/s².

**StarPilot's two paths.** The legacy path (openpilot's, through the filters) runs 12% of the lead time with vision
only, 19% with `raw` and 13% with `fused` (the ACC target alone: 13%): it switches on and off 530-890 times an hour, and
the filters, which start at 0 and update only on that path, are more than 2 m/s from the lead's speed when it starts in
24-29% of runs. That happens with vision only too, so it belongs to the fork, not to
the radar. With `fused` the first 2 s of a run ask for a median +0.23 m/s² more than with the ACC target (90th
percentile +0.91, at least 1.0 in 14 of 159 runs); with `raw` +0.67 (+1.25, 74 of 392).

## What the evidence supports

- On any fork, install the default `fused`: it cuts the braking demand the radar's speed errors add about six-fold on
  sunnypilot (90 → 14 events per hour against the radar's own tracker), and the benefit grows with how much of the
  radar's speed the fork uses.
- A fork that uses the radar's speed and acceleration (sunnypilot, FrogPilot with Human Following off) gets most from the
  radar and is the most sensitive to what the radar gets wrong. A fork that anchors on the vision model (FrogPilot's
  default, StarPilot's first path) is smooth because the radar contributes less: range, and the lead's speed now.
- The earlier braking reported for sunnypilot ([08](08_openpilot_integration.md#radar--vision-against-vision-only-replay))
  comes from openpilot's real planner; the fork rows here use the demand proxy.

## Method and limits

- The forks' radard and `process_lead` run unmodified in a harness that replaces messaging, params and the solver
  (`tools/fork_lead/forksim.py`), per model tick (20 Hz) of recorded drives: the vision model's leads and lane lines, the
  car state, and the radar points of the profile being tested. U1 is a drive with stock ACC, U2 one with openpilot
  longitudinal ([09](09_tools_and_data.md#data-in-this-repo)).
- **Demand** is the constant deceleration that keeps the MPC's own safety distance over 10 s along the lead path a fork
  hands its MPC, with the ego started at the desired spacing, so it measures the lead path alone. It compares forks and profiles
  through radard and the lead path; the MPC, jerk limits, cruise, personalities and each fork's other features stay
  outside it.
- Defaults are assumed (the rows above); user settings change them. StarPilot's filter time runs with its default
  model-uncertainty input. The braking-onset comparison above rests on 10 events and one proxy (○).
- Versions move: the older fork notes in [08](08_openpilot_integration.md#on-the-road) describe earlier builds
  (FrogPilot 0.9.7, an early StarPilot profile). StarPilot's constant lead-acceleration extrapolation above 35 mph is
  still in its legacy path.
