# 07. Velocity excursions (the jitter and false-closing issue)

The radar's velocity is its best channel ([06](06_accuracy.md)). It has one systematic flaw: on a settled track, the
velocity sometimes **drifts for 1-10 s while the track's range does not follow**. Most drifts are **false closings
beyond 40 m**. In openpilot this shows up as extra jitter in the longitudinal plan and, rarely, as a braking request
that vision would not make.

## What an excursion looks like

![excursion sample](img/vrel_excursion_sample.png)

*Bundled sample `data/sample/highway_vrel_excursion_25s.csv.gz`: ego steady at 31 m/s, lead at ~48 m slowly
opening. The lead's over-ground speed falls 33.5 → 25.0 m/s and recovers within about 1.2 s. Replayed through
openpilot's radard and planner, this produced a forward-collision warning and −3.5 m/s².*

![false closing sequence](img/shots/excursion_false_closing_sequence.jpg)

*The same event on the road camera over 4 s: the settled lead (#1, age 126) stays at 48-50 m and its box does not
grow, while its vRel swings from +2.4 to about −6 m/s and back.*

![false closing on a real drive](img/analysis/jitter_false_closing_event.png)

*A long false closing on a real drive at about 85 km/h: the track's vRel drifts to −12 m/s over about 9 s (implying
~50 m of closing) while its range stays at 85-110 m and vision holds steady.*

The shape, from labelled episodes where native vRel disagrees with both the radar's own ACC target and the vision lead:

- **Mostly false closings:** 84-88% of episodes.
- **A smooth drift:** the gap to the ACC target ramps from about −1 to −3.4 m/s over ~1.5 s and decays over ~2 s.
  Record-to-record steps stay small (1.7% exceed 2 m/s) and do not reverse (step autocorrelation −0.01).
- **Strongly range-dependent:** about 0.1 per 1,000 records below 20 m, 4 at 20-40 m and 130 at 60-80 m; incidence
  reaches about 18% of track time at 100 m. Higher above 30 m/s ego speed.
- **The whole motion state moves together:** the acceleration field `84|10` follows the drift, and the track stays in
  the measured state (state 1). The bias enters with the measurements, upstream of the object tracker, consistent with
  Doppler returns from a different scattering point or path on the target.
- **The radar's range does not follow**, but range walks by metres over the same seconds, so range alone confirms or
  refutes a drift only after 2-4 s at 60-100 m.

## How often, on real drives

![census](img/analysis/jitter_real_drive_census.png)

Four closed-loop drives with the radar feeding openpilot's radard (1.05 h, 0.31 h following a radar lead):
- radard's radar lead and the vision lead disagree on relative speed by ≥ 2 m/s for ≥ 1 s **58 times** (about once
  every 20 s of radar-lead driving): 1% of radar-lead time at 0-20 m, 20% at 40-60 m, 49% beyond 80 m;
- when the radar says "closing faster", the track's own range sides with **vision** in 22 of 33 episodes;
- when the radar says "closing slower", range sides with the **radar** in 16 of 25 (vision lagging).

![gallery](img/analysis/jitter_real_drive_gallery.png)

*Two false closings and two real closings the radar saw first. In the first second they look the same.*

## What openpilot does with it

- radard's per-track Kalman filter smooths **vRel only** and passes a drift straight into `vLeadK` and `aLeadK`
  (−3 to −5 m/s² during a drift).
- The 25% distance gate keeps the drifting track matched to the vision lead (at 110 m the gate is about 28 m wide).
- The planner projects `aLeadK` forward with a 1.5 s decay.

![roughness by state](img/analysis/jitter_roughness_by_state.png)

*20 held-out routes, 4.56 h: in steady radar-lead following, radar+vision is only +0.005 m/s² RMS rougher than
vision-only; around the moments where radar and vision disagree (20% of the time) it is +0.032 rougher, about 70% of
the extra roughness.*

## Options

![trade-off](img/analysis/jitter_tradeoff.png)

Measured on 20 held-out routes by replaying openpilot's own card → radard → plannerd and scoring against the driver:

| option | where | extra roughness removed | head start given up | radar-only brakes the driver overrode with gas |
|---|---|---|---|---|
| default `OPENPILOT_CONFIG` (with saturation guard) | interface | — | — | 0.66 / h |
| K4: `range_fusion_gain=0.1`, `vrel_smooth_far_tau_s=1.0` | interface | **about half** (−0.0053 [−0.0099, −0.0022] m/s²; fresh drives −0.0081 [−0.0155, −0.0015]) | 0.07 s | 0.44 / h |
| **`STEADY_CONFIG`** = K4 + saturation guard + 8 m/s velocity-jump guard | interface | about half, as K4 | 0.07 s | **0.22 / h** |
| far-range smoothing only (`vrel_smooth_far_tau_s=1.0`) | interface | about 29% | 0.06 s | 0.66 / h |
| ACC target's speed (0x235) as the object's vRel | interface | little; driver-agreement error −40% | 0.10-0.16 s | — |
| vision speed fused into the matched track | radard patch | driver-agreement error −0.0043 [−0.0068, −0.0018] (twice K4's −0.0021) | 0.085 s | 0.88 / h |

- **`STEADY_CONFIG` is the recommended profile** (`install.py --profile steady`). K4's range fusion and far-range
  smoothing keep most of radar's 0.15 s head start and halve the jitter. The two guards withhold invalid readings: the
  saturated velocity code 1023, and a mature track's velocity jumping more than 8 m/s from one record to the next (a
  new level that lasts 1 s is accepted under a new track ID). Together they cut hard radar-only braking requests
  (≤ −2 m/s² while vision-only asks for no more than −0.5) from 85 to 69 ticks on the held-out routes, including a
  −3.5 m/s² request from a saturated reading, and halve the gas-overridden radar-only brakes again. Lag, early
  reaction, lead switches and driver agreement are unchanged; 17 of 20 routes are identical to K4.
- **The radard patch** ([`openpilot/radard_vision_fusion.patch`](../openpilot/radard_vision_fusion.patch)) rewrites
  radard's track filter in covariance form (identical output for radar-only tracks) and fuses the vision lead's speed
  into the matched track with standard deviation `2 × vStd`. It helped most on the held-out routes; on the fresh
  drives its effect was small (−0.0005 [−0.0009, +0.0004]). The camera's lead speed is noisier than this radar's
  (median error 1.1-2.0 m/s vs 0.6-1.2 m/s at 20-120 m, judged by 4 s range slopes), so `VISION_V_STD_SCALE` of 3-4
  is the natural next setting.
- **The ACC target** (0x235) is the strongest velocity witness when present, but it covers 57% of radar-lead moments
  and 5% beyond 80 m.

## Radar-internal signals that move with an excursion

| signal | behaviour during an excursion |
|---|---|
| `240\|7` σ vx | higher (AUC 0.65 / 0.85 on discovery / confirmation labels) |
| `264` measurement state | more near-scan state 1 at ranges where far scan should also see the object; states 4-8 rise 3-6 s later |
| 0x235 ACC target | disagrees with the object's vRel (when present) |
| lane state `128\|3` | changes more often, also on real closings |

Each of these moves with excursions; none alone separates them from real closings within the first second. Combining
them, and the ideas in [10](10_research_directions.md), is where the remaining gap is.
