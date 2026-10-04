# 07. Velocity excursions (the false-closing issue)

The radar's velocity is its best channel ([06](06_accuracy.md)), with one systematic flaw: on a settled track the
velocity sometimes **drifts for 1-10 s while the range does not follow**, mostly as a **false closing beyond 40 m**.
In openpilot that shows up as extra jitter in the plan and, rarely, a braking request vision would not make. The
profiles exist to handle it; the default `fused` does so with one Kalman filter
([below](#fused-speed-filter-fused-profile)).

**In short**

- 84-88% of excursions are false closings; they ramp up over ~1.5 s and decay over ~2 s.
- Rare close in, common far out: ~0.1 per 1,000 records below 20 m, 130 at 60-80 m, ~18% of track time at 100 m.
- Their size matches the speed uncertainty the radar reports itself (`240|7`); the radar's own ACC tracker follows the
  same car without them.
- `fused` weights every reading by that uncertainty and leans on the radar's own trackers: hard radar-only braking
  117 → 30 ticks on 20 held-out routes.

## What an excursion looks like

![excursion sample](img/vrel_excursion_sample.png)

*Bundled sample `highway_vrel_excursion_25s.csv.gz`: a lead at ~48 m, slowly opening; its over-ground speed falls
33.5 → 25.0 m/s and recovers within ~1.2 s. Through openpilot's radard and planner this produced a forward-collision
warning and −3.5 m/s².*

![false closing sequence](img/shots/excursion_false_closing_sequence.jpg)

*The same event on camera: the lead stays at 48-50 m and its box does not grow, while vRel swings +2.4 → −6 → back.*

![false closing on a real drive](img/analysis/jitter_false_closing_event.png)

*A long one at ~85 km/h: vRel drifts to −12 m/s over ~9 s while the range stays at 85-110 m and vision holds steady.*

- **Smooth drift, not a jump:** the gap to the ACC target ramps from about −1 to −3.4 m/s; record-to-record steps stay
  small (1.7% exceed 2 m/s).
- **Range does not follow**, but range itself walks by metres at 60-100 m, so range alone confirms a drift only after
  2-4 s.
- **The motion state moves with it:** the acceleration field `84|10` follows the drift. The cause inside the radar
  (measurement bias, scatterer association, tracking) is open (○).

<details>
<summary>What the radar's waveform allows (why it is not a Doppler wrap)</summary>

### What the radar's waveform allows

The published ARS510 data sheet (Winner and Waldschmidt, *Automotive Radar*, 2026, Table 15.3) gives 256 ramps at
104 µs, a 19 m/s single-cycle unambiguous radial-velocity span resolved over two cycles, 0.074 m/s resolution, 0.15 m/s
separability (the step of `64|10`) and three bandwidths by ego speed (range resolution 0.4 / 0.7 / 0.98 m); generic
product values (○ for this firmware). Excursion offsets sit well inside that span (median −4.0 m/s against vision,
−3.1 below 40 m to −4.8 at 80-100 m); unwrapping by ±19 m/s changes 57 of 900 labelled samples. So an excursion is not
a full-span wrap of the published velocity (◐); it builds up over 1-2 s, which fits low-SNR measurements at range
([`waveform_source.json`](../data/analysis/summaries/waveform_source.json)). Suppressing downstream lead switches
leaves excess roughness, and the observed outputs do not locate the bias upstream of the tracker
([`excursion_mechanism_scope.json`](../data/analysis/summaries/excursion_mechanism_scope.json)).

</details>

## How often, on real drives

![census](img/analysis/jitter_real_drive_census.png)

Four closed-loop drives with the radar feeding radard (1.05 h, 0.31 h following a radar lead):

- radar and vision lead disagree by ≥ 2 m/s for ≥ 1 s **58 times** (about every 20 s of radar-lead driving): 1% of
  radar-lead time at 0-20 m, 20% at 40-60 m, 49% beyond 80 m;
- "radar closing faster": the track's own range sides with vision in 22 of 33;
- "radar closing slower": range sides with the radar in 16 of 25 (vision lagging).

![gallery](img/analysis/jitter_real_drive_gallery.png)

*Two false closings and two real closings the radar saw first. In the first second they look the same.*

### Far-range excursions match the reported velocity error scale

![excursion sigma scale](img/analysis/excursion_sigma_scale.png)

- Against the radar's own ACC target, the object-list speed error grows with the reported uncertainty `240|7`
  ([03](03_slot_fields.md#kinematics)): RMS ≈ 0.04-0.05 m/s per count (≈ 0.8 m/s at code 15, 1.4 m/s at code 30).
  Codes grow with range, so far tracks carry a 1-3 m/s error scale.
- A Gaussian with σ = 0.045 × code predicts the share of far records inside an excursion (5.1% observed vs 6.4%
  predicted; 6.9% vs 5.5% on fresh drives). The error is low-pass (~0.3 Hz), so a 1-3σ deviation lasts seconds.
- Not explained by range leakage, neighbouring objects, clutter, ego compensation, association or lifecycle flags.
- `240|7` tells **how large** far errors can be, not **when** one happens: it is a width, which is why `fused` uses it
  to weight readings rather than to gate them.

<details>
<summary>Caveats and the residual error</summary>

- 0.045 is a fitted Gaussian-equivalent, not a decoded unit: the robust (MAD) core is ~0.027 m/s per count over codes
  12-70; heavy tails (kurtosis 1.3-8) lift the RMS. Above code ~40 the error grows less than proportionally. The ACC
  target has its own error (~0.6 m/s).
- Within a range band, `240|7` separates excursion records below 40 m (AUC 0.95-0.97) but weakly beyond (0.41-0.68)
  ([`continental_field_map.json`](../data/analysis/summaries/continental_field_map.json)).
- A −0.3 m/s mean offset (native more closing than ACC) grows with range (−0.1 below 20 m, −0.6 at 80-110 m), has no
  ego-speed slope and differs by drive (std 0.3 m/s). Of 13.6k candidate signals only the object's own state explains
  part of it: `84|10` acceleration (R² 0.11), measurement state `264|8`, width `216|6`. Together the object's state
  and 3 s history predict ~41-47% of the error variance on 114 held-out drives; no single field carries it
  ([`excursion_sigma_scale.json`](../data/analysis/summaries/excursion_sigma_scale.json)).

</details>

<details>
<summary>Compared with an optical reference (camera scale change)</summary>

### Compared with an optical reference

![object-list velocity disagreement with the optical reference](img/analysis/video_truth_excursions.png)

- Reference: `−(native range + 1.52 m) × d ln(scale)/dt` from ECC registration of the lead's rear over 0.5-1 s. It
  avoids native velocity but shares native range and association; not a physical ground truth.
- 2,657 two-second windows in five 10-130 m bins: native more closing than the reference by > 2.5 m/s in
  0.2 / 2.2 / 10.6 / 15.0 / 20.9% of windows; the opposite in 0 / 0.2 / 0.6 / 2.2 / 1.4%
  ([`video_truth.json`](../data/analysis/summaries/video_truth.json)).
- A camera-veto prototype on that feed changed 2,201 of 110,332 planner ticks on four development chains with no
  scored driving improvement (hard ticks 86 → 86); it is not in any profile
  ([`camera_route_scoped_planner.json`](../data/analysis/summaries/camera_route_scoped_planner.json)).

</details>

## What openpilot does with it

- radard's per-track Kalman filter smooths **vRel only** and passes a drift into `vLeadK` and `aLeadK` (−3 to −5 m/s²).
- The 25% distance gate keeps the drifting track matched to the vision lead (at 110 m about 28 m wide).
- The planner projects `aLeadK` forward with a 1.5 s decay.

![roughness by state](img/analysis/jitter_roughness_by_state.png)

*20 held-out routes: in steady following radar+vision is only +0.005 m/s² RMS rougher than vision; around radar/vision
disagreements (20% of the time) +0.032, about 70% of the extra roughness.*

## How the filtering works, step by step

`fused` (the default) runs three shared steps and one Kalman filter per track, in
`Ars510NativeRadarInterface._payload` ([`ars510/interface.py`](../ars510/interface.py)). `raw` runs steps 0-1 only.
The earlier tuned approach (`anchor`) is summarised [below](#earlier-approach-tuned-layers).

![each layer added in turn](img/analysis/layer_staircase.png)

*Hard radar-only braking requests (planner ≤ −2 m/s² while vision-only asks ≥ −0.5) on 20 held-out routes: the tuned
layers added one at a time, and `fused` instead of them
([`layer_ablation.json`](../data/analysis/summaries/layer_ablation.json),
[`fused_filter.json`](../data/analysis/summaries/fused_filter.json)).*

### 0. The plain decode (every profile)

- **Rule:** publish from age 60 (~3.6 s); subtract 0xB4 ego speed (× 0.149/0.15); no point without a fresh ego speed;
  keep a track's ID across losses ≤ 3.5 s.
- **Why:** young tracks have unconverged range and speed ([02](02_object_list.md)); one NaN poisons radard's filter.

### 1. Saturation guard (every profile)

- **Problem:** velocity code 1023 (and 0) is an invalid sentinel that decays over ~6 records.
- **Rule:** withhold the track until the velocity is back within 5 m/s of the last good value (or 1 s); continue under
  a new ID.
- **Evidence:** one sentinel otherwise reaches the planner as −3.5 m/s²; held-out hard ticks 117 → 93.

### 2. Range fusion (`fused`, `anchor`)

- **Problem:** range walks by metres at 60-100 m (3% per frame); radard's distance and vision match jitter.
- **Rule:** predict dRel with vRel, then move 10% toward the measurement each cycle.
- **Evidence:** halves 1.5 s range walks; with far smoothing removes about half of radar's extra plan roughness; costs
  ~0.07 s of head start together with far smoothing.

### Fused speed filter (`fused` profile)

One standard Kalman filter per track on the lead's over-ground speed
([summary](../data/analysis/summaries/fused_filter.json); six real moments and the vision-only comparison in
[11](11_profiles_compared.md)). Every cycle it predicts the lead keeps its speed (allowing a lead acceleration), then
folds in each available reading weighted by its own uncertainty:

| ingredient | value | where it comes from |
|---|---|---|
| object-list speed σ | 0.045 m/s × `240\|7` (≈ 0.2 m/s at 15 m, 1.4 at 60 m, 2.7 at 100 m) | calibrated against the radar's ACC target ([above](#far-range-excursions-match-the-reported-velocity-error-scale)) |
| young-track factor | × 1.8 below age 100 | measured: young tracks err 1.4-2× more than `240\|7` says |
| ACC target speed σ, summary speed σ | 0.5 m/s each (summary up to 80 m) | the radar's own trackers |
| lead acceleration (process noise) | 1.5 m/s² | physical |
| robust update | innovations clamped at 3σ | standard; stops one-record spikes |
| first publication | speed std ≤ 0.75 m/s (and age ≥ 60) | replaces far-track settling without a range threshold |
| range | not in the filter; range fusion as before | range rate and speed disagree by 10-20% |

![profiles on the bundled samples](img/analysis/profile_comparison.png)

*All four profiles on the bundled excursions: `fused` (green) follows the radar's ACC target on drive E and keeps drive
A's lead at the speed its range trend shows.*

**What each part contributes** (34 replay drives, held-out hard ticks / radar-only target episodes):

| | hard ticks | target episodes | owner-drive episodes |
|---|---|---|---|
| tuned layers, no ACC target (`steady`) | 53 | 11 | – |
| tuned layers + ACC target (`anchor`) | 48 | 9 | 5 |
| Kalman filter on the object list alone | 48 | 8 | 4 |
| Kalman filter + ACC target + summary (`fused`) | **30** | **4** | **0** |

The filter alone matches the whole tuned stack; the radar's own trackers add the rest
([`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json)). Against `anchor`: held-out hard ticks 48 → 30, target episodes 9 → 4, owner-drive target
episodes 5 → 0. Braking onset is 0.09 s later on average, all from events where `anchor` braked early on an
over-estimated closing speed (before those driver brakes `anchor` is 0.54 m/s more closing than vision, `fused` 0.02).
Dropped variants: adapting the process noise follows far slot slides as if they were braking; without the robust
clamp a +10 m/s spike passes.

### Kalman variants tested

The single speed state of `fused` was compared with richer filters on an offline bench: every cycle of 8 drive groups,
the radar's ACC target hidden as the reference, tuned on 3 groups and scored on the rest. The best candidates were then
replayed through openpilot ([`kalman_variants.json`](../data/analysis/summaries/kalman_variants.json)).

![Kalman variants](img/analysis/kalman_variants.png)

| variant | bench | openpilot replays |
|---|---|---|
| Student-t update instead of the 3σ clamp | same as the clamp | – |
| speed + acceleration state (as radard), fed the radar's `84\|10` acceleration | worse on held-out and owner drives | – |
| noise learned from all slot fields (gradient boosting) | small gain; it relearns `240\|7`, ego speed and `84\|10` | – |
| object-list error as its own state (colored noise, τ 1.2 s), noise scaled by ego speed and `84\|10` | **15% fewer false closings**, same response to real braking | 34 drives: held-out 30 → 29 hard ticks, one far false closing held for seconds (2 → 30 on the further drives) |
| retuned `fused` constants (σ per count, ACC σ, lead accel) | – | 8 fresh drives: none better on every check |

The colored-noise filter is the textbook fix for the object list's slow, correlated errors: lag-1 autocorrelation is
0.95 per record, about 1.2 s per independent error. It rejects slow drift, but for the same reason it takes seconds to
let go of a large drift that recovers. Real driving rewards letting go quickly, so `fused` keeps one speed state.
`COLORED_CONFIG` is not in the decoder.

### Other approaches tested

None is in a profile.

| approach | result |
|---|---|
| vision speed fused into the matched track ([radard patch](../openpilot/radard_vision_fusion.patch)) | better driver agreement, small on fresh drives; needs a radard change |
| the ACC target's speed *replacing* the track's vRel | hard ticks 53 → 57, +0.145 s response: the ACC value alone lags real closings |
| smoothing weighted by `240\|7` (no fusion) | responds 62 ms earlier but 153 vs 85 hard ticks |
| camera-looming veto | no planner benefit |
| Kalman filter with maneuver adaptation or a range state | follows far slot slides / biased by the range-speed mismatch ([fused](#fused-speed-filter-fused-profile)) |

<details>
<summary>Earlier approach: tuned layers (<code>anchor</code>, <code>steady</code>)</summary>

### Earlier approach: tuned layers

Before the Kalman filter, five tuned layers each targeted one measured failure. `anchor` (steps 0-3, 5-7) is kept as a
fallback profile; `steady` (0-3, 5-6) is superseded by `fused`, which falls back to the object list alone when there is
no ACC target and does better without it (48 vs 53 hard ticks).

![one example per layer](img/analysis/layer_examples.png)

*One example per layer from the bundled samples (panels 3 and 5 synthetic), with `fused` in green
([`tools/make_profile_figures.py`](../tools/make_profile_figures.py)). On a one-record spike (panel 3) `fused` lets a
small, quickly fading part through where the jump guard blocks it.*

### 3. Far smoothing (`steady`, `anchor`)

- **Rule:** exponential smoothing of vRel, time constant 0 s below 30 m rising to 1 s at 60 m.
- **Evidence:** removes ~29% of the extra roughness for 0.06 s alone.

![roughness against head start](img/analysis/jitter_tradeoff.png)

### 4. Velocity-jump guard (option, off)

- **Rule:** withhold a record > 8 m/s from the last accepted value; a level that lasts 1 s is real (new ID).
- **Evidence:** helped before the ramp limiter existed (85 → 69 hard ticks); with it, no scored change on 34 drives,
  so it is off (`vjump_thresh_mps=8`).

### 5. Far-track settling (`steady`, `anchor`)

- **Problem:** tracks first seen beyond 70 m are often unconverged at age 60.
- **Rule:** such tracks wait until age 100 (~6 s); once published they stay eligible.
- **Evidence:** further drives 10 → 3 hard ticks; removing it raises them 1 → 9
  ([`far_settling.json`](../data/analysis/summaries/far_settling.json)).

![far-track settling example](img/analysis/far_settling.png)

### 6. Ramp limiter (`steady`, `anchor`)

- **Problem:** excursions ramp at ~+23 m/s² over ground; no car changes speed that fast.
- **Rule:** over-ground speed may move away from its 3 s average by at most +4 / −6 m/s²; moves back pass unchanged.
- **Evidence:** held-out hard ticks 69 → 53, further drives 3 → 1, no driver brake loses its early reaction
  ([`ramp_limiter.json`](../data/analysis/summaries/ramp_limiter.json)).

![ramp limiter example](img/analysis/ramp_limiter.png)

### 7. ACC anchor (`anchor`)

- **Problem:** steps 3-6 slow an excursion but cannot tell it from a real closing. The radar's own ACC target
  (0x235 / 0x237, [05](05_acc_target_and_support.md)) can: it stays consistent with range during excursions (closer to
  the range trend in 76% of disagreements) and still follows real decelerations. It is the same car: in 653
  disagreement cycles no other track was near the target
  ([`acc_target_choice.json`](../data/analysis/summaries/acc_target_choice.json)).
- **Rule:** match the ACC target to one track by position (lateral within 0.5 m, range within 12 m, age ≥ 20), keep the
  match while both persist (excursions drag the range), and clip that track's vRel to the target speed ± 3 m/s.
- **Evidence:** held-out hard ticks 53 → 48, owner drives 16 → 0, fresh drives 7 → 0; onset unchanged
  ([`acc_anchor.json`](../data/analysis/summaries/acc_anchor.json)).
- **Limits:** the target covers ~57% of radar-lead time and 5% beyond 80 m.

### Summary anchor (in `anchor`, up to 80 m)

The radar's target-range summaries (0x192 / 0x194, [05](05_acc_target_and_support.md#0x191-0x194-selected-target-summaries))
come from its internal tracker too. A summary attaches to a track when range (within 15%) and speed (within 1.5 m/s)
agree; that track's vRel is held within ±3 m/s of the summary's range slope. Against the optical reference the summary
speed is better at 40-80 m (false closings 6.5% vs 14.9% at 60-80 m), not beyond 80 m. No planner change on 34 drives
on its own ([`summary_tracks.json`](../data/analysis/summaries/summary_tracks.json)).

### Range anchor (option, off)

`acc_range_clip_m` bounds the ACC track's range by the ACC target's fine range. Held-out hard ticks 48 → 45, but
distances move by up to 12 m where fine range and object list disagree on scale, so it stays off
([`acc_fields.json`](../data/analysis/summaries/acc_fields.json)).

### What removing a layer does

From the full tuned profile, 34 replay drives ([`layer_ablation.json`](../data/analysis/summaries/layer_ablation.json)):

| removed | effect |
|---|---|
| everything (`raw` instead of `steady`) | held-out hard ticks 53 → 93, target episodes 11 → 19, lead switches +39%; onset 0.04 s earlier |
| ramp limiter | held-out hard ticks 53 → 69 |
| far smoothing (from `anchor`) | held-out 48 → 45 but further drives 1 → 9, target episodes 9 → 11 |
| far-track settling (from `anchor`) | further drives 1 → 9 |
| jump guard | no scored change: removed from the profiles |
| ACC anchor (`steady` instead of `anchor`) | held-out 48 → 53, owner 0 → 16, fresh 0 → 7 |
| far smoothing or settling, with the summary anchor on | further drives 1 → 3 / 1 → 9: summaries do not replace them |

</details>

## Radar-internal signals that move with an excursion

| signal | behaviour during an excursion |
|---|---|
| `240\|7` velocity-error scale | higher (≈ 0.045 m/s per count against the ACC target) |
| `264` measurement state | more near-scan state 1; states 4-8 rise 3-6 s later |
| 0x235 ACC target | disagrees with the object's vRel (when present) |
| lane state `128\|3` | changes more often, also on real closings |

None alone separates an excursion from a real closing within the first second ([10](10_research_directions.md)).

<details>
<summary>Earlier replay comparisons (fresh jump-guard check, sunnypilot profile comparison)</summary>

## Fresh jump-guard simplification comparison

`steady` without the 8 m/s jump guard on eight fresh routes (114 segments) through the unchanged sunnypilot radard and
planner, two publication schedules, 779,076 ticks: hard command-disagreement ticks 7 → 7, radar-only episodes 6 → 6,
all 19 driver events and 83 recorded command windows unchanged. Preregistered non-increase overlay met; strict
improvement false. With `anchor` the same holds on all 34 replay drives, so the guard is off in both
([`fresh_s4_replay.json`](../data/analysis/summaries/fresh_s4_replay.json)).

## Sunnypilot profile comparison

Owner drives through sunnypilot's original radard and planner (72 segments, 84,659 model ticks, two schedules):

| drive | `steady` episodes | `raw` episodes | `steady` + ACC clip episodes |
|---|---:|---:|---:|
| D1 | 5 | 8 | 4 |
| D2 | 0 | 2 | 0 |
| D3 (recorded radar disabled) | 0 | 0 | 0 |

An episode is ≥ 0.3 s of request ≤ −1 m/s² while the same-fork vision-only replay asks ≥ −0.3 m/s². In D2's window
`steady` and the clip reach −0.99 m/s² against −2.07 for `raw`
([`sunnypilot_profile_comparison.json`](../data/analysis/summaries/sunnypilot_profile_comparison.json)).

</details>
