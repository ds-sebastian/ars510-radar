# 14. The radar on openpilot forks

The installer works on every fork ([08](08_openpilot_integration.md)), but a fork decides what its planner does with
a radar lead. This page reads the radard and MPC lead handling of sunnypilot, FrogPilot and StarPilot, runs their own
code on four recorded drives (two cars) and on synthetic cases, and says what the ARS510 changes on each.

Profiles: the run feeds each fork the points of `acc` (the radar's ACC target alone, the default install) and, as
research references that are not installable, `raw` (the unfiltered object-list decode) and `fused` (all tracks through
the object-list filter, version 2.6.0; [12](12_kalman_filter.md)). The radar's ACC target is also the **reference** the added
demand of the other two is measured against, so `acc` shows 0 added demand by construction and its own rows are the
reference rows.

Numbers: [`fork_lead_handling.json`](../data/analysis/summaries/fork_lead_handling.json). Tools:
[`tools/fork_lead/`](../tools/fork_lead) ([how to run them](09_tools_and_data.md#compare-forks)). Marks: ● read from the
fork's source, ◐ from the replay and synthetic runs below, which use a proxy for the planner (see [method](#method-and-limits)).

**In short**

- All three forks take the same tracks, and all three let the **camera pick the lead**: a radar track becomes the
  lead when it matches the vision lead (below 4 m/s every fork also takes a close radar track). What differs is what
  the planner then does with the track's speed and acceleration, and that one fork also accepts radar-only leads at speed.
- **sunnypilot** (openpilot's own path) hands the MPC the radar's speed and acceleration. It is the fork most exposed to
  the radar's speed errors ([07](07_velocity_excursions.md)) and the one `fused` helps most: events with a false braking
  demand of at least 1 m/s² fall from 128 (`raw`) to 1.4 (`fused`) per hour; `acc` hands it the reference point itself.
- **FrogPilot** with its default Human Following takes the radar's range and the lead's speed at the first instant; the
  vision model supplies the future. A radar speed error of 1-4 m/s adds 0.07-0.30 m/s² of demand there (◐), and its first braking
  request came at the same time as vision-only's in 26 of 30 lead-braking events checked (3 earlier, 1 later). It also takes in-lane radar-only leads.
- **StarPilot** uses the same vision-model path until a lead brakes harder than 0.5 m/s² or closes within 7 s, then
  switches to the openpilot path through two speed and acceleration filters whose state can start stale (◐). With warm
  filters it reacts to a radar speed error about 60% as much as sunnypilot; on the drives with `raw` it added about as much (115 against 128 events per hour of ≥ 1 m/s², 338
  against 323 of ≥ 0.5).
- On sunnypilot, FrogPilot with Human Following off and StarPilot, `fused` removes most of what `raw` adds (≥ 1 m/s²
  events 128 → 1.4 and 115 → 7 per hour); on FrogPilot's default path both profiles add little (12.5 and 2.1 events per hour
  against vision only). `fused` takes its speed from the radar's ACC target where the radar follows a car ([12](12_kalman_filter.md)),
  and `acc` publishes that target alone.

## What each fork does with a radar lead (●)

Sources read: sunnypilot `master` 3323aaf, FrogPilot `FrogPilot-Staging` 6976ff3 (a compiled release branch; radard and
planner are readable), StarPilot `StarPilot` 2a12dbd.

| | sunnypilot | FrogPilot | StarPilot |
|---|---|---|---|
| radard | openpilot's (its change is Hyundai-only) | openpilot's plus the rows below | openpilot's plus the rows below |
| camera confirmation of a lead | peak-held probability (0.2 s decay) > 0.5 | per-frame probability > 0.35 (setting, 0.25-0.5) | peak-held probability (0.2 s decay) > 0.35 (setting, 0.25-0.5) |
| match of a track to the vision lead | distance, lateral and speed weights; distance and speed sanity | the same | the same plus a lateral sanity check; keeps the previous track if it only just misses the gate |
| radar-only lead | ego below 4 m/s, track within ±1 m laterally and 0.75-25 m ahead | the same, plus any moving in-lane track after about 0.5 s while the camera lead is empty (the "far lead") | the same as sunnypilot, with a 3-frame persistence gate after standstill |
| lead acceleration decay (`aLeadTau`) | 1.5 s | 1.5 s | 0.6 s |
| lead path given to the MPC | openpilot's: radar `dRel`, `vLead`, `aLeadK`, decaying | Human Following on (default, model v9): radar `dRel` and `vLead` at t = 0, the model's deltas after. Off: openpilot's | the same vision-model path (radar sets the start, the model the deltas) while the lead brakes under 0.5 m/s² and its time to collision stays above 7 s; otherwise openpilot's, through `lead_v_filter` / `lead_a_filter` |
| smoothing in the planner | 0 s | 0 s | lead speed and acceleration filters: 0 s below 47 mph, 1.2 s at 65 mph and above |
| radar extras | 0 added | adjacent-lane leads (setting) and lane-change matching (default on with a radar) | adjacent-lane leads (setting), lane-change matching, a stopped-neighbour hint ("Force Stop"), a taper on its legacy path that scales down a far radar lead's deceleration (gap more than max(8 m, 0.25 s × v) beyond the desired distance, closing under 2.5 m/s), and 11 comfort caps for vision leads (bypassed for radar leads) |

## What that does with this radar (◐)

**A radar speed error, with the truth known.** A lead pace-matched to the ego car at 30 m/s; the radar's closing speed
reads too fast (a synthetic profile: it ramps up over 1.5 s, holds 1 s and decays over 2 s; the measured excursions in
[07](07_velocity_excursions.md) ramp up over about 1 s).
Extra braking demand (m/s², proxy) over the same fork fed error-free input, gap 45 m:

| error | sunnypilot | FrogPilot, Human Following off | StarPilot | FrogPilot, default |
|---|---|---|---|---|
| −1 m/s | 0.64 | 0.64 | 0.32 | 0.07 |
| −2 m/s | 1.24 | 1.24 | 0.75 | 0.15 |
| −4 m/s | 2.33 | 2.33 | 1.47 | 0.30 |

At 70 m the results are within 0.05 of these, except −1 m/s, which falls to 0.22 (0.01 on FrogPilot's default).

**On real drives** (U1, U2, O6 and O7: 56-59 min with a radar lead and an ACC target). Each fork on a profile against
the same fork given the radar's ACC target alone (the `acc` profile, 0 by construction); events per hour of extra demand
of at least 1.0 (0.5) m/s²:

| | `raw` | `fused` 2.6.0 | `acc` |
|---|---|---|---|
| sunnypilot | 128 (323) | 1.4 (5.4) | 0 (0) |
| FrogPilot, Human Following off | 128 (325) | 1.3 (5.4) | 0 (0) |
| StarPilot | 115 (338) | 7 (15) | 0 (0) |
| FrogPilot, default | 1 (6) | 0 (0) | 0 (0) |

`fused` cuts sunnypilot's and FrogPilot-off's large events about ninety-fold and StarPilot's about seventeen-fold. StarPilot's
remaining events all fall where its filtered legacy path switches in at a different moment than on the reference, with
lead speeds mostly within 0.6 m/s of the ACC target's, so they come from the fork's path switching rather than the radar's
speed. The small
FrogPilot numbers come from that path taking its deltas from the vision model, so little radar error reaches it. In 30 lead-braking events seen by the ACC target, first braking requests with `fused` come at the same time as vision-only's in 26 (FrogPilot default), 9 (sunnypilot, FrogPilot-off) and 18 (StarPilot), earlier in 3, 11 and 8, later in 1, 8 and 2, and 0, 2 and 2 are responses only the radar made. On sunnypilot's path the proxy puts the radar's response
earlier than vision's in 11 events and later in 8, while the real-planner replay in [08](08_openpilot_integration.md#radar--vision-against-vision-only-replay)
puts it earlier; the proxy models the lead path alone (jerk limits and the vision model's own acceleration forecast belong to the real planner), so its timing
is a hint (○). Against vision only, sunnypilot with `raw` adds 137 braking events of at least 1.0 per hour,
FrogPilot-off 140, StarPilot 111, FrogPilot default 12.5; with `fused` 8.6, 8.4, 10.3 and 2.1, and 5, 5, 2 and 0 per hour
are braking that vision alone would have asked for and the radar left out.

**Radar-only leads.** Of the lead time, 77-83% has a radar-sourced lead and 0.3-1.1% a radar-only one, on every fork.
FrogPilot's far-lead path takes an in-lane moving track that only the radar reports: with the scene otherwise empty it
did so after 0.5 s in the synthetic case (peak demand 0.74 m/s² for a 10 m/s slower object, 1.49 for 20 m/s slower),
while sunnypilot and StarPilot kept the vision-only lead. On the drives it produced 18 leads in 58 min with `fused` (63 with `raw`) that the other forks left to the vision-only lead (median
0.15 s, longest 0.9 s); 2 would have asked for at least 1.0 m/s².

**StarPilot's two paths.** The legacy path (openpilot's, through the filters) runs 14% of the lead time with vision
only, 21% with `raw`, 15% with `fused` and 15% with `acc`: it switches on and off 740-1,110 times an hour, and
the filters, which start at 0 and update only on that path, are more than 2 m/s from the lead's speed when it starts in
21-22% of runs (22% with vision only), so the stale start is a property of the fork. With `fused` the first 2 s of a run ask for a median +0.05 m/s² more than with the ACC target (90th
percentile +0.79, at least 1.0 in 17 of 225 runs); with `raw` +0.66 (+1.79, 208 of 755).

## What the evidence supports

- On any fork, install the default `acc` or `acc_summaries` (the two installable profiles). `acc` publishes only the
  radar's ACC target, the reference of this comparison, so the fork's lead speed is the ACC target's speed. The
  object-list filter `fused` cuts the braking demand the radar's speed errors add about ninety-fold on sunnypilot
  (128 → 1.4 events per hour against the radar's own tracker) but does not remove it, and on held-out drives it still
  passed a false closing to the planner ([11](11_profiles_compared.md)); the more of the radar's speed a fork uses, the
  more such an error costs.
- A fork that uses the radar's speed and acceleration (sunnypilot, FrogPilot with Human Following off) gets most from the
  radar and is the most sensitive to what the radar gets wrong. A fork that anchors on the vision model (FrogPilot's
  default, StarPilot's first path) is smooth because the radar contributes less: range, and the lead's speed now.
- The braking onset reported for sunnypilot ([08](08_openpilot_integration.md#radar--vision-against-vision-only-replay))
  comes from openpilot's real planner; the fork rows here use the demand proxy.

## Method and limits

- The forks' radard and `process_lead` run unmodified in a harness that replaces messaging, params and the solver
  (`tools/fork_lead/forksim.py`), per model tick (20 Hz) of recorded drives: the vision model's leads and lane lines, the
  car state, and the radar points of the profile being tested. U1 (stock ACC, 21 min) and U2 (openpilot
  longitudinal, 26 min) come from a second car; O6 and O7 are owner sunnypilot drives of 28 and 22 min ([09](09_tools_and_data.md#data-in-this-repo)).
- **Demand** is the constant deceleration that keeps the MPC's own safety distance over 10 s along the lead path a fork
  hands its MPC, with the ego started at the desired spacing, so it measures the lead path alone. It compares forks and profiles
  through radard and the lead path; the MPC, jerk limits, cruise, personalities and each fork's other features belong to
  the real planner.
- The rows above are the fork defaults; user settings change them. StarPilot's filter time runs with its model-uncertainty
  input at 0 (off). The braking-onset comparison above rests on 30 events and one proxy (○).
- The fork notes in [08](08_openpilot_integration.md#on-the-road) come from FrogPilot 0.9.7 and an early StarPilot profile;
  this page reads the commits listed above. StarPilot's legacy path extrapolates the lead's acceleration unchanged above 35 mph.
