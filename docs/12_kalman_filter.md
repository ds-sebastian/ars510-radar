# 12. The Kalman speed filter

The object list's speed has slow, correlated errors at range: false closings of 1-10 s beyond about 40 m
([07](07_velocity_excursions.md)). The radar reports their size in `240|7` but does not flag them per moment. The
default `fused` profile handles them with **one Kalman filter per track** on the lead's over-ground speed. The filter
weights every reading by its own uncertainty: the object list, the radar's ACC target and its target-range summaries.
radard then runs its usual filter on what this one publishes.

Code: `Ars510NativeRadarInterface._fused_speed` in [`ars510/interface.py`](../ars510/interface.py), and the same
filter in the single-file upstream candidate [`upstream/ars510_radar.py`](../upstream/ars510_radar.py). Numbers:
[`fused_filter.json`](../data/analysis/summaries/fused_filter.json).

## The model

One state per track: the lead's speed over ground `v`, with variance `P`. Every radar cycle (`Δt` ≈ 60 ms):

```text
predict      v⁻ = v                          P⁻ = P + (a · Δt)²            a = 1.5 m/s² (lead acceleration)
for each reading z with standard deviation σ (object list first, then ACC target, then summary):
  innovation e = z − v⁻,  S = P⁻ + σ²,  e clamped to ±3·√S             (robust update)
  gain       K = P⁻ / S
  update     v = v⁻ + K·e                    P = (1 − K)·P⁻
publish      vRel = v − v_ego                 first publication once √P ≤ 0.75 m/s (and age ≥ 60)
```

| reading | σ | where the value comes from |
|---|---|---|
| object-list speed `64\|10` | 0.045 m/s × `240\|7` (× 1.8 below age 100) | `240\|7` scales with the error against the ACC target ([07](07_velocity_excursions.md#far-range-excursions-match-the-reported-velocity-error-scale)) |
| ACC target speed (0x235, + ego speed) | 0.5 m/s | the radar's own ACC tracker, for the one track it matches by position ([05](05_acc_target_and_support.md)) |
| summary speed (0x192 / 0x194 range slope) | 0.5 m/s, up to 80 m | the radar's selected-target ranges, matched by range and speed |

**The gain is not fixed.** radard's filter uses one precomputed gain for every track. Here `K` changes every cycle
with the radar's own uncertainty code and with which trackers are present. A near car with a small `240|7` is
followed almost directly. A far car with a large `240|7` moves only a few percent per reading. While the ACC target
is present, it dominates.

![the filter on one track](img/analysis/kalman_trace.png)

*Bundled drive E. Top: the object-list readings (grey) dive to −6 m/s at 18 s while the ACC target stays near
−0.7; the estimate follows the ACC target. Bottom: the gain on each reading. Each object-list reading moves the
estimate by about 5%, each ACC target reading by about 15%. The dotted line is the object-list σ from `240|7`.*

![fused: weights and publication](img/analysis/fused_how_it_works.png)

*Left: how much the filter trusts each reading by range. Middle: the share of the estimate from the radar's own
trackers. Right: a new track's speed std against age; the 0.75 m/s line is the publication gate.*

![profiles on the bundled samples](img/analysis/profile_comparison.png)

*`raw` and `fused` on the bundled excursions: `fused` (green) follows the radar's ACC target on drive E and keeps drive
A's lead at the speed its range trend shows.*

## How it fits with radard

radard runs its own per-track Kalman filter on `[vLead, aLead]` with a fixed gain and derives the lead acceleration.
This filter cleans only the speed it hands over, so radard's filter and the planner run unchanged. Lead acceleration
stays radard's job; a speed + acceleration state here did worse ([below](#kalman-variants-tested)).

## Constants and their sources

| ingredient | value | where it comes from |
|---|---|---|
| object-list speed σ | 0.045 m/s × `240\|7` (≈ 0.2 m/s at 15 m, 1.4 at 60 m, 2.7 at 100 m) | calibrated against the radar's ACC target ([07](07_velocity_excursions.md#far-range-excursions-match-the-reported-velocity-error-scale)) |
| young-track factor | × 1.8 below age 100 | measured: young tracks err 1.4-2× more than `240\|7` says |
| ACC target speed σ, summary speed σ | 0.5 m/s each (summary up to 80 m) | the radar's own trackers: the ACC target stays with the range trend in 76% of disagreements and is the same car ([`acc_target_choice.json`](../data/analysis/summaries/acc_target_choice.json)); summaries beat the object list against the camera at 40-80 m, not beyond |
| lead acceleration (process noise) | 1.5 m/s² | physical |
| robust update | innovations clamped at 3σ | standard; stops one-record spikes |
| first publication | speed std ≤ 0.75 m/s (and age ≥ 60) | replaces far-track settling without a range threshold |
| range | not in the filter; range fusion as before | range rate and speed disagree by 10-20% |

## What runs before the filter

### 0. The plain decode (every profile)

- **Rule:** publish from age 60 (~3.6 s); subtract 0xB4 ego speed (× 0.149/0.15); no point without a fresh ego speed.
  `raw` also keeps a track's ID across losses ≤ 3.5 s (relink); `fused` does not need it.
- **Why:** young tracks have unconverged range and speed ([02](02_object_list.md)); one NaN poisons radard's filter.

### 1. Saturation guard (`raw`)

- **Problem:** velocity code 1023 (and 0) is an invalid sentinel that decays over ~6 records.
- **Rule:** withhold the track until the velocity is back within 5 m/s of the last good value (or 1 s); continue under
  a new ID.
- **Evidence:** one sentinel otherwise reaches the planner as −3.5 m/s²; held-out hard ticks 117 → 93.

### 2. Range fusion (`fused`)

- **Problem:** range walks by metres at 60-100 m (3% per frame); radard's distance and vision match jitter.
- **Rule:** predict dRel with vRel, then move 10% toward the measurement each cycle.
- **Evidence:** halves 1.5 s range walks, which radard's distance and the planner otherwise pass on.

## What each part contributes

![what each part is worth](img/analysis/kalman_ablation.png)

Each part removed from `fused` on its own, 34 replay drives (hard radar-only ticks on 20 held-out routes / 4 further drives / owner drives; [`fused_filter.json`](../data/analysis/summaries/fused_filter.json)):

| `fused` without … | held-out | further | owner | verdict |
|---|---|---|---|---|
| (nothing: `fused`) | **30** | **2** | **0** | |
| the ACC target and summaries (filter on the object list alone) | 48 | 2 | 0 (4 target episodes) | needed |
| the young-track factor | 30 | 11 | 0 | needed |
| the speed-std publication gate | 30 | 8 | 0 | needed |
| the age-60 publication gate (age 6) | 31 | 12 | 0 (radar-only braking ×3) | needed |
| range fusion | 27 | 0 | 0 | braking neutral (milder radar-added episodes 1 → 3 in 4.6 h); kept for lead stability: radar ↔ vision lead switches +39% without it |
| the ego-speed alignment (× 0.149/0.15) | 31 | 2 | 0 | neutral (onset +12 ms); one measured constant |
| the track-ID relink | 30 | 2 | 0 | identical in every measure (lead switches 1770 vs 1772): removed |
| the saturation guard | identical | identical | identical | removed: the 3σ update absorbs the sentinel |

Against the earlier tuned profile: held-out hard ticks 48 → 30, target episodes 9 → 4, owner-drive target episodes
5 → 0. Braking onset is 0.09 s later on average, all from events where the tuned profile braked early on an
over-estimated closing speed (0.54 m/s more closing than vision before those driver brakes, `fused` 0.02).
Dropped variants: adapting the process noise follows far slot slides as if they were braking; without the robust
clamp a +10 m/s spike passes.

## Removing parts together

One-at-a-time removals can hide parts that only matter together, so the larger parts were also removed in combination
on the same 34 drives. The rule for "same driving as `fused`" was fixed before the results:
- held-out hard ticks ≤ 33 and further-drive hard ticks ≤ 4;
- no hard ticks and no target episodes on the owner drives;
- target episodes ≤ 5;
- lead-source switches at most +15 %;
- onset within ±0.03 s of `fused`.

![fewest lines for the same driving](img/analysis/kalman_combinations.png)

- **The track-ID relink is free:** removing it changes nothing.
- **The summaries matter only at the margin:** without them (with or without relink), one mild extra slowdown appears
  on the owner drives (−1.1 m/s² for 0.5 s at 103 m), which fails the rule.
- **Range fusion keeps the lead stable:** every version without it flips between radar and vision leads about 39 % more
  often.
- **The young-track factor and the speed-std gate cost about 5 lines** and still help in the barest version.

The smallest version with the same driving is `fused` without the relink. That is the default profile, and the
openpilot version ([`upstream/ars510_radar.py`](../upstream/ars510_radar.py), 264 lines) is exactly this profile in
one file ([`fused_filter.json`](../data/analysis/summaries/fused_filter.json) `combinations_34_drives`).

## Kalman variants tested

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
The fork build keeps it as the experimental `colored` profile (`COLORED_CONFIG`) for road tests.

## Other approaches tested

None is in a profile.

| approach | result |
|---|---|
| vision speed fused into the matched track ([radard patch](../openpilot/radard_vision_fusion.patch)) | better driver agreement, small on fresh drives; needs a radard change |
| the ACC target's speed *replacing* the track's vRel | hard ticks 53 → 57, +0.145 s response: the ACC value alone lags real closings |
| smoothing weighted by `240\|7` (no fusion) | responds 62 ms earlier but 153 vs 85 hard ticks |
| camera-looming veto | no planner benefit |
| Kalman filter with maneuver adaptation or a range state | follows far slot slides / biased by the range-speed mismatch ([fused](#the-model)) |

## Earlier approach: tuned layers (removed)

Before the Kalman filter, five tuned layers each targeted one measured failure: far smoothing, a velocity-jump guard,
far-track settling, a ramp limiter (+4 / −6 m/s²) and ±3 m/s clips to the ACC target and summaries (17 tuned
constants). The staircase below shows them added one at a time: together they took held-out hard ticks from 93 to 48,
which the Kalman filter on the object list alone matches with 3 chosen constants, and `fused` beats (30). They were
removed; per-layer numbers stay in [`layer_ablation.json`](../data/analysis/summaries/layer_ablation.json).

![each layer added in turn](img/analysis/layer_staircase.png)

*Hard radar-only braking on 20 held-out routes: the tuned layers added one at a time, and `fused` instead of them.*
