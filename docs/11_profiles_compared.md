# 11. Profiles compared: what each does, against vision only and other radar parsers

The integration ships four install profiles. This page shows how each one processes a track, what adding it to
openpilot changes compared with **vision only** (stock openpilot on this car, which has no radar leads), how that feels
from the driver's seat, the assumptions behind those numbers, and how the code compares with the other radar
interfaces in openpilot. Numbers: [`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json),
[`fused_filter.json`](../data/analysis/summaries/fused_filter.json),
[`acc_anchor.json`](../data/analysis/summaries/acc_anchor.json). Figures: `tools/make_fused_figures.py`,
`tools/make_profile_figures.py`.

## At a glance

| | `raw` | `steady` | `anchor` (default) | `fused` |
|---|---|---|---|---|
| what it adds to the decode | nothing (validity, IDs, ego subtraction) | 4 tuned guards against speed excursions | `steady` + clip to the radar's ACC target and summaries | one Kalman speed filter weighting every reading by the radar's own uncertainty |
| tuned constants beyond `raw` | — | 8 | 8 + 9 | 3 chosen, 4 measured or physical |
| code beyond the shared decode | ~60 lines | +41 | +115 | +109 (replaces `steady`'s layers) |
| hard radar-only braking ticks, 20 held-out routes | 93 | 53 | 48 | **30** |
| braking only the radar asked for, per hour (driver on the gas) | 1.75 (0.66) | 1.31 (0.22) | 1.10 (0.22) | **0.22 (0)** |
| first braking request vs vision only, 167 driver brakes | **−0.15 s** | −0.08 s | −0.08 s | +0.01 s |
| recommended for | research | cars without the ACC target on the radar bus | everyday driving today | trying the principled filter (opt-in until road-tested) |

`raw` is the unfiltered radar decode, not vision only and not stock openpilot; `stock` and `default` are its older
names.

## How each profile works

![which processing each profile applies](img/analysis/profile_layers.png)

*Each row is one processing step; coloured cells are the steps a profile runs. Line counts are non-blank, non-comment
lines in `ars510/interface.py`.*

- **`raw`** publishes the object list as decoded: tracks from age 60 (≈ 3.6 s, once range and speed have converged),
  the radar's own track IDs re-linked across short gaps, speed relative to the ego car, and the invalid velocity code
  withheld. Velocity excursions (1-10 s false closings beyond 40 m, [07](07_velocity_excursions.md)) reach the planner.
- **`steady`** adds four guards, each tuned against one failure: range fusion (predict range from speed, correct 10 %
  toward the measurement), far smoothing (speed averaged over up to 1 s beyond 30-60 m), far settling (new tracks
  beyond 70 m wait until age 100), and a ramp limiter (speed may leave its 3 s average by at most +4 / −6 m/s²).
- **`anchor`** adds the radar's own internal trackers as bounds: the track the radar reports as its ACC target
  (0x235 / 0x237) stays within ±3 m/s of the target's speed, and a track matched to the target-range summaries
  (0x192 / 0x194) stays within ±3 m/s of their range slope up to 80 m.
- **`fused`** keeps the decode and range fusion and replaces the five speed layers with **one Kalman filter per track**
  on the lead's over-ground speed ([07](07_velocity_excursions.md#fused-speed-filter-fused-profile)). It is a standard
  one-state Kalman filter: the state is the lead's speed, the motion model lets it change with a lead acceleration of
  1.5 m/s², and each available reading updates it in turn, weighted by its own variance: the object-list speed
  (σ = 0.045 m/s × the radar's `240|7` uncertainty code, × 1.8 for tracks younger than 100 frames), the ACC target
  speed (σ 0.5 m/s) and the summary speed (σ 0.5 m/s). Innovations beyond 3σ count as 3σ (a robust Kalman update), and
  a track is first published once its speed standard deviation is below 0.75 m/s. radard then runs its own Kalman
  filter on the lead; `fused` feeds it one speed per track that already combines what the radar knows.

![fused: weights and publication](img/analysis/fused_how_it_works.png)

*Left: how much `fused` trusts each reading by range. Middle: the share of the estimate coming from the radar's own
trackers when they are present. Near, the object list dominates; beyond ~40 m the ACC target and summaries do. Right:
speed standard deviation of a new track against age; the 0.75 m/s line is the publication gate, which holds young far
tracks back without a range threshold.*

![profiles on the bundled samples](img/analysis/profile_comparison.png)

*All four profiles on the two bundled excursions (regenerated from `data/sample/`).*

### `fused` in six real moments

![fused scenarios 1-3](img/analysis/fused_scenarios_a.png)
![fused scenarios 4-6](img/analysis/fused_scenarios_b.png)

*Lead closing speed (top) and planner request (bottom) under vision only, `anchor` and `fused`, through the unchanged
planner; grey dots are the raw object-list speed of the radar lead, dashed is the radar's ACC target, dotted the
summary slope where the parser would associate it. Times are relative to the moment.*

1. **False closing rejected.** The object list dives to −6 m/s; the ACC target and summary stay at −0.6. `anchor`
   brakes to −2 m/s², `fused` follows the trackers and asks for what vision asks for.
2. **Slowing lead seen early.** The ACC target shows the lead slowing before the object list does; `fused` follows it
   and answers the driver's brake 0.85 s earlier than `anchor`.
3. **Over-estimated closing.** The object list (and `anchor`, −3.8 m/s) report more closing than the ACC target's own
   range shows (≈ −1.8 m/s); `fused` stays near the ACC target and vision, so it does not brake early.
4. **Fast real closing.** All agree it is real. `fused` sits between the object list and the ACC target and brakes
   slightly less than `anchor` and vision (−2.1 vs −2.3 m/s²).
5. **Far slot slide, no ACC target.** The object list jumps to −13 … −38 m/s at 80-110 m (the radar's slot moving
   between reflectors). `anchor` dips to −1.1 m/s², `fused` to −0.6, vision stays near 0.
6. **Stopping behind a car.** Near range: the object list dominates in both profiles; `fused` hands the lead to the
   closer vision lead 0.5 s sooner, like vision.

## Against vision only

All four profiles were replayed on the same 34 drives through the unchanged openpilot card → radard → planner, and
judged against what the driver did, with the pre-registered definitions used for the original radar-vs-vision test.
Held-out set: 20 routes, 4.56 h with the driver controlling speed, 167 driver brake presses, 47 hard slowdowns.

![profiles against vision only](img/analysis/profiles_vs_vision.png)

| driver brake presses (167) | vision only | `raw` | `steady` | `anchor` | `fused` |
|---|---|---|---|---|---|
| first request ≤ −0.5 m/s², mean vs vision (95 % CI) | — | −0.15 s [−0.26, −0.05] | −0.08 s [−0.16, 0.00] | −0.08 s [−0.16, 0.00] | +0.01 s [−0.04, +0.06] |
| median first request vs the brake press | −0.61 s | −0.87 s | −0.79 s | −0.79 s | −0.67 s |
| already asking ≤ −0.5 m/s² within 3 s before | 80.8 % | 84.4 % | 83.8 % | 83.8 % | 81.4 % |
| already asking ≤ −1.0 m/s² within 3 s before | 40.1 % | 44.3 % | 44.3 % | 43.7 % | 41.9 % |
| hard slowdowns never asked ≤ −1 m/s² (of 47) | 10 | 9 | 10 | 10 | 10 |

| over 4.56 h of driver-controlled driving | vision only | `raw` | `steady` | `anchor` | `fused` |
|---|---|---|---|---|---|
| braking (≤ −1 m/s², ≥ 0.3 s) only this system asked for, per hour | 0 | 1.75 | 1.31 | 1.10 | 0.22 |
| … of which the driver was on the gas | — | 0.66 | 0.22 | 0.22 | 0 |
| hard radar-only braking ticks (≤ −2 m/s² while vision ≥ −0.5) | — | 93 | 53 | 48 | 30 |
| driver overrides (38): radar request closer / further than vision to what the driver then did | — | 7 / 2 | 8 / 2 | 8 / 2 | 5 / 0 |
| request error vs the driver's acceleration 0.5 s later (RMS) | 0.409 m/s² | 0.422 | 0.420 | 0.418 | 0.414 |
| request jerk (mean \|da/dt\|) | 1.003 m/s³ | 1.029 | 1.011 | 1.009 | 1.001 |
| share of lead time on a radar lead | 0 | 86.6 % | 86.2 % | 86.2 % | 87.1 % |

What the radar adds, by profile:

- **`raw`, `steady`, `anchor` brake earlier than vision** (0.08-0.15 s on average) and anticipate a few more driver
  brakes. Part of that head start is real (the radar sees closings through curves and before the camera's distance
  estimate settles); part comes from an over-closing bias: in the 4 s before the driver brakes, `anchor`'s lead closing
  speed is on average 0.54 m/s more closing than the vision lead's. The same bias causes their radar-only braking.
- **`fused` removes that bias** (0.02 m/s from vision on average) and, with it, almost all radar-only braking: 0.22 per
  hour, every one while the driver also slowed. Its timing is then the same as vision on average: 11 driver brakes are
  answered earlier than vision (by 0.62 s on average, 7 of them hard slowdowns) and 17 later; 14 of those 17 are
  equally late with every radar profile (the radar lead shows less closing than vision there), so they come from using
  radar at all, not from the filter.
- **Every profile follows a radar lead about 86-87 % of the time a lead exists**, so radard uses radar distance
  (6 cm resolution; frame-to-frame jitter about 3 % of range far out) rather than the camera's distance estimate.

## Driving experience: pros and cons

| profile | pros | cons |
|---|---|---|
| vision only | smooth; no radar-specific false braking | camera distance at range; no radar head start on closings through curves or far away |
| `raw` | earliest reaction to real slowdowns (−0.15 s vs vision) | the most radar-only braking (1.75 / h, a third with the driver on the gas): occasional sharp brakes for nothing beyond 40 m |
| `steady` | about half `raw`'s false braking, keeps most of the head start | still ~1.3 radar-only brakes per hour; four tuned guards with thresholds |
| `anchor` | fewest false brakes of the tuned profiles (no hard ticks on the owner drives); default and road-tested | still ~1.1 radar-only brakes per hour; reaction partly comes from over-closing; 17 tuned constants in all |
| `fused` | closest to vision in feel (lowest jerk, smallest error vs the driver), radar-only braking almost gone, closing speed unbiased, simplest speed path | braking onset the same as vision on average (no average head start); not yet road-tested; the frozen replay gates for reaction time fail because the reference profile's early reactions included the bias |

## Assumptions and limits

- **Open-loop replay.** The recorded drives are replayed through the unchanged openpilot (or sunnypilot) radard and
  planner; the car's actual motion stays as recorded, so differences are what the planner would have asked for, not
  what the car would then have done.
- **The driver is the reference, not ground truth.** "Earlier" and "anticipated" are measured against the moment the
  driver pressed the brake; a profile that brakes before the driver is not automatically right.
- **Vision only is stock openpilot's own lead model** on the same recorded camera frames; its lead speed is noisy
  and is a comparison, not truth. The radar's ACC target and summaries are the radar's own estimates (sent by the
  radar, [05](05_acc_target_and_support.md)); they are not independent of the radar.
- **Scope.** One car (RAV4 2022 / 2023, firmware `8821F0R03100`), 34 replay drives (20 held-out routes, 4.56 h of
  driver-controlled time; 4 further drives; 3 owner sunnypilot drives) used during development, plus 8 fresh drives.
  Fewer than 10 events separate several of the rows above.
- **Definitions.** Hard radar-only tick: planner ≤ −2 m/s² while vision only asks ≥ −0.5. Driver-brake metrics use
  [−3, +0.5] s (anticipation), [−3, +2] s (first request) and [−3, +1] s (missed hard slowdown) around the brake press.

## Compared with the other radar interfaces in openpilot

| interface | code lines | what it does |
|---|---|---|
| Toyota (older radars, 0x210-0x22F) | 70 | `VALID` flag plus a score / valid counter; pass-through |
| Tesla (Continental, like the ARS510) | 66 | `Tracked`; publishes `Meas` as `measured`; radar status for faults |
| Honda | 60 | range < 255; pass-through |
| Hyundai | 55 | track `STATE`; pass-through |
| Rivian | 54 | `STATE`; pass-through |
| Chrysler | 56 | pass-through |
| GM | 71 | pass-through of the radar's targets |
| Ford | 194 | clusters raw Delphi detections into tracks |
| **ARS510 shared decode** | 288 | reassembles a 742-byte record from 106 CAN frames, CRC, 20 slots of bit fields |
| ARS510 `raw` | +~60 | publication age, ID re-link, saturation guard |
| ARS510 `fused` | +~109 | `raw` + range fusion + ACC / summary association + one Kalman speed filter |

The other interfaces read radars that publish clean, validated tracks and leave all filtering to radard. The ARS510's
object list is a processed track list too, but its far-range speed has a wide error that it reports (`240|7`) without
flagging individual bad moments, so some estimation is needed before radard. `fused` keeps that to one textbook filter
whose weights come from the radar's own uncertainty fields and internal trackers. The same weighting could instead live
in radard as a per-point speed variance, which would leave this interface a pass-through like the others
([10](10_research_directions.md#towards-an-upstream-comma-interface)).
