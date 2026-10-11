# 11. Profiles compared: what each does, against vision only and other radar parsers

This page compares `raw`, `fused` and `acc` (plus a diagnostic `fused` 2.0 run without the ACC target): how they
work, against **vision only** (stock openpilot on this car), on driving feel, and against openpilot's other radar
interfaces.

Numbers: [`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json),
[`fused_filter.json`](../data/analysis/summaries/fused_filter.json). Figures: `tools/make_fused_figures.py`,
`tools/make_profile_figures.py`.

## At a glance

| | `raw` | `fused` 2.0 without ACC target | `fused` | `acc` (default) |
|---|---|---|---|---|
| what it publishes | the decoded object list: validity, IDs, ego subtraction | the object list through range fusion + one Kalman speed filter | the same filter, also fusing the radar's ACC target, plus path gates and the far rule | only the radar's ACC target (0x235 / 0x237), as one point; no object list |
| filter settings | — | scalar process scale, robust update and readiness threshold | also the ACC target's weight; [definitions and evidence](12_kalman_filter.md#the-model) | none |
| code | fork build: relink and saturation guard on the shared decode ([below](#how-each-profile-works)) | fork build: speed filter and range fusion | the openpilot version is 187 code lines in all ([10](10_research_directions.md#parts-of-the-openpilot-file)) | 26 code lines and a 7-signal DBC in all ([10](10_research_directions.md#the-acc-target-alone--candidate)) |
| hard radar-only braking ticks, 20 held-out routes (while moving) | 93 | 48 | **16 (16)** | 66 (**14**) |
| braking only the radar asked for, per hour (driver on the gas) | 1.75 (0.66) | 0.88 (0.22) | **0 (0)** | **0 (0)** |
| first braking request vs vision only (148 paired driver brakes; 149 for `fused` and `acc`) | −0.15 s | −0.03 s | −0.01 s | −0.04 s |
| recommended for | research | diagnostic: the filter on the object list alone | the all-tracks alternative | everyday driving |

`raw` is the unfiltered radar decode. The `fused` 2.0 column is a diagnostic: `fused` with the ACC target ignored, which
shows the Kalman filter on its own. `acc`'s hard ticks are mostly holds at standstill (52 of 66): the stopped car 0.7-4.8 m
behind an object the camera does not report, where radard's low-speed rule keeps it stopped. The names of the earlier
tuned profiles (`anchor`, `steady`) install `fused`. The research profiles `shared_speed` / `shared_range` are not compared
here ([10](10_research_directions.md#the-acc-target-alone--candidate)).

## Why `acc` is the default

- **Equal braking, more stable leads.** Over every drive set (16.9 moving h) `acc` asks for something different from
  `fused` on 0.21 % of moving time, and every route-bootstrap difference includes zero. It has fewer lead flips (302
  against 332 per hour). On 26 owner routes held out from every replay, it brakes unnecessarily less (7.7 against
  11.4 s) and flips less, both outside chance ([10](10_research_directions.md#the-acc-target-alone--candidate)).
- **A new stationary vehicle reaches the planner at once.** `fused` publishes a track only once it is 60 radar cycles
  old (3.6 s), which shields the planner from a young track's unconverged speed. In a short city approach that can be
  the whole encounter. On U3 a pickup parked in the lane was tracked from about 30 m ahead and lost at 14 m, one cycle
  short of age 60, so `fused` never published it and drove as vision only. `acc` published it from 18.9 m, 0.6 s before
  Toyota's PCS warned, with the radar's range. Vision put the lead 3-4 m closer
  ([13](13_car_bus_messages.md#a-recorded-stock-pcs-alarm-u3);
  [`pcs_activation_u3.json`](../data/analysis/summaries/pcs_activation_u3.json), `replay_open_loop`).
- **Small and auditable.** 26 code lines and a 7-signal DBC, with no fitted constant: it passes on the radar's own decision,
  the one Toyota's ACC acts on.
- **What it gives up.** Only one radar car: the one Toyota's ACC follows. Every other car, including a second lead, comes
  from the camera. `fused` keeps every radar car and stays available as `--profile fused`.

## How each profile works

![which processing each profile applies](img/analysis/profile_layers.png)

*Each row is one processing step; coloured cells are the steps a profile runs. Line counts are source lines of the
fork build (`ars510/`); the summaries are a fork option, on in `colored`. `acc` runs none of the object-list steps: its
whole file reads the ACC target.*

- **`raw`** publishes the object list as decoded: tracks from age 60 (≈ 3.6 s, once range and speed have converged),
  the radar's own track IDs re-linked across short gaps, speed relative to the ego car, and the invalid velocity code
  withheld. Velocity excursions (1-10 s false closings beyond 40 m, [07](07_velocity_excursions.md)) reach the planner.
- **`fused`** adds range fusion and **one Kalman filter per track**
  on the lead's over-ground speed ([12](12_kalman_filter.md#the-model)). It uses the scalar Kalman equations
  with a process-noise scale of 1.5 m/s² (a lead-acceleration bound). Each reading updates it in turn, weighted by its model variance:
  object-list speed has σ = 0.045 m/s × max(`240|7`, 1), multiplied by 1.8 through age 60 and tapered to 1 at age 100.
  The matched ACC target uses σ 0.13 m/s for the one track it describes. Innovations beyond 3 innovation standard deviations are clamped there (a robust Kalman update), and
  a track is first published once its modeled speed standard deviation is at most 0.75 m/s (and age at least 60).
  That standard deviation is a readiness measure for publication. radard then runs its own Kalman filter on the
  lead; `fused` feeds it one speed per track that already combines what the radar knows.
- **`acc`** publishes only the radar's ACC target: the one car the radar's own ACC function follows, already chosen,
  converged and in path, with its fine distance (0.025 m), lateral position and closing speed. Toyota's ACC uses
  nothing else. The radar's target ID is the track ID; every other car comes from the camera through radard's usual
  vision match. Protocol only, through opendbc's CANParser and a two-message DBC: the target-present flags, `canError` when the
  ACC frames stop (CANParser's timeout), and a report every 5th update (20 Hz).

![fused: weights and publication](img/analysis/fused_how_it_works.png)

*Left: how much `fused` trusts each reading by range. Middle: the share of the estimate coming from the radar's ACC
target when it is present. Very close in, the object list dominates; from about 10 m on the ACC target does. Right:
speed standard deviation of a new track against age; the 0.75 m/s line is the publication gate, which holds young far
tracks back through the filter's own uncertainty.*

![profiles on the bundled samples](img/analysis/profile_comparison.png)

*`raw` and `fused` on the two bundled excursions (regenerated from `data/sample/`). The dashed line is the radar's ACC
target, which is exactly what `acc` publishes. Drive A has no ACC target, so there `acc` publishes nothing and radard
uses the camera lead.*

## Against vision only

Each profile was replayed on the same 27 drives through the unchanged openpilot card → radard → planner, and
judged against what the driver did, with the pre-registered definitions used for the original radar-vs-vision test
([`driver_agreement_preregistered.json`](../data/analysis/summaries/driver_agreement_preregistered.json)).
Held-out set (its historical name; the drives were used during development): 20 routes, 4.56 h with the driver controlling speed, 167 driver brake presses, 47 hard slowdowns.

![profiles against vision only](img/analysis/profiles_vs_vision.png)

| driver brake presses (167) | vision only | `raw` | `fused` 2.0 w/o ACC target | `fused` | `acc` |
|---|---|---|---|---|---|
| first request ≤ −0.5 m/s², mean vs vision (95 % CI) | — | −0.15 s [−0.26, −0.05] | −0.03 s [−0.11, +0.04] | −0.01 s [−0.06, +0.03] | −0.04 s [−0.09, +0.00] |
| median first request vs the brake press | −0.61 s | −0.87 s | −0.74 s | −0.69 s | −0.68 s |
| already asking ≤ −0.5 m/s² from 3 s before to 0.5 s after | 80.8 % | 84.4 % | 83.8 % | 82.0 % | 82.0 % |
| already asking ≤ −1.0 m/s² from 3 s before to 0.5 s after | 40.1 % | 44.3 % | 41.9 % | 44.9 % | 44.9 % |
| hard slowdowns missed (request stayed above −1 m/s², of 47) | 10 | 9 | 10 | 10 | 9 |

| over 4.56 h of driver-controlled driving (jerk, error, lead share and flips: its 2.66 h moving) | vision only | `raw` | `fused` 2.0 w/o ACC target | `fused` | `acc` |
|---|---|---|---|---|---|
| braking (≤ −1 m/s², ≥ 0.3 s) only this system asked for, per hour (driver-controlled stretches only) | 0 | 1.75 | 0.88 | 0 | 0 |
| … of which the driver was on the gas | — | 0.66 | 0.22 | 0 | 0 |
| hard radar-only braking ticks (≤ −2 m/s² while vision ≥ −0.5; while moving) | — | 93 | 48 | 16 (16) | 66 (14) |
| driver overrides (38): radar request closer / further than vision to what the driver then did | — | 7 / 2 | 6 / 1 | 7 / 0 | 7 / 0 |
| request error vs the driver's acceleration 0.5 s later (RMS) | 0.409 m/s² | 0.422 | 0.419 | 0.412 | 0.411 |
| request jerk (mean \|da/dt\|) | 1.003 | 1.029 | 1.007 | 0.993 | 0.985 |
| share of lead time on a radar lead | 0 | 86.6 % | 86.8 % | 83.1 % | 84.8 % |
| flips between a radar and a vision lead, per hour | 0 | 939 | 703 | 347 | 318 |

What the radar adds, by profile:

- **`raw` brakes earlier than vision** (0.15 s on average) and anticipates a few more driver brakes. Part of that head
  start is real (the radar sees closings through curves and before the camera's distance estimate settles); part comes
  from an over-closing bias of the unfiltered object list. The same bias causes its radar-only braking.
- **`fused` removes that over-closing bias** and, with it, all radar-only braking on the held-out drives (0 per hour; 0.22 before the far rule of 2.6, every one while the
  driver also slowed). It starts braking when vision does on average (−0.01 s, 95 % CI −0.06 … +0.03): 18 of 149 paired driver brakes
  are answered earlier than vision and 12 later, and it is already asking for ≤ −1 m/s² before 44.9% of brake presses
  (vision 40.1%). In the 4 s before driver brakes, while its lead is a radar point, it shows on average 0.31 m/s less closing than the vision lead
  (median 0.16; [`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json)).
- **The Kalman filter alone** (`fused` 2.0 without the ACC target) halves `raw`'s hard radar-only braking (93 → 48 hard ticks) with onset between
  `raw` and `fused`; the radar's ACC target supplies the rest of the drop in hard braking (`fused` 2.0 already reached 30 ticks).
- **`acc` drives like `fused` without its filter.** Braking starts 0.04 s before vision only on average (95 % CI
  −0.09 … +0.00), with the same anticipation, one hard slowdown fewer missed, no radar-only braking, the lowest jerk and
  fewer lead flips. Its extra hard ticks are holds at standstill behind objects the camera does not report; while
  moving it has 14 against `fused`'s 16. On the 4 further drives it has one hard brake (7 ticks) that `fused` does not:
  a real object braking and drifting a lane over at 82 m that radard matches to the camera's lead 27 m further on.
- **Every profile follows a radar lead about 87 % of the time a lead exists**, so radard uses the radar distance for
  those leads. In `fused` the car the radar's ACC function follows is published at the radar's
  ACC distance, which agrees with the vision lead within a metre up to 90 m and, when it was added in 2.1, cut the flips between a
  radar and a vision lead by 30 % ([12](12_kalman_filter.md#matching-the-radars-trackers-to-tracks)); other tracks keep the
  object-list range (6 cm resolution; frame-to-frame jitter about 3 % of range far out).

## Driving experience: pros and cons

| profile | pros | cons |
|---|---|---|
| vision only | smooth; braking follows the camera alone | camera distance at range; closings through curves or far away seen later than the radar sees them |
| `raw` | earliest reaction to real slowdowns (−0.15 s vs vision) | the most radar-only braking (1.75 / h, over a third with the driver on the gas): occasional sharp brakes on false closings beyond 40 m |
| `fused` | closest to vision in feel, radar-only braking gone, as early as vision on average, one speed state | the head start over vision is small on average; 187 lines with tuned gates |
| `acc` | a DBC and 26 lines, nothing tuned; uses the radar the way Toyota's ACC does; lowest jerk and fewest flips in replay; slightly earlier than vision | a fast closing beyond 60 m reaches the planner through the camera until the radar picks the car (0.8-1 s later; `fused` publishes only the ACC target there too); close cut-ins are picked after a median 0.2 s (0.3 s for a faster car) and brake as with `fused` ([10](10_research_directions.md#the-acc-target-alone--candidate)); holds at standstill behind close objects; no road miles yet |

## Assumptions and limits

- **Open-loop replay.** The recorded drives are replayed through the unchanged openpilot (or sunnypilot) radard and
  planner; the car's actual motion stays as recorded, so differences are what the planner would have asked for.
- **The driver is the reference.** "Earlier" and "anticipated" are measured against the moment the driver pressed the
  brake; braking before the driver can be right or early, which is why hard brakes are also judged one by one
  ([12](12_kalman_filter.md#what-each-part-is-worth)).
- **Vision only is stock openpilot's own lead model** on the same recorded camera frames; its lead speed is noisy and
  serves as a comparison. The radar's ACC target is the radar's own estimate (sent by the radar ◐,
  [05](05_acc_target_and_support.md)), so it shares the radar's view of the scene.
- **Scope.** One car (RAV4 2022, firmware `8821F0R03100`), 27 replay drives (20 held-out routes, 4.56 h of
  driver-controlled time; 4 further drives; 3 owner sunnypilot drives) used during development, plus 8 fresh drives.
  In the driver-brake table, at most 7 brake presses separate the columns in each row.
- **Definitions.** Hard radar-only tick: planner ≤ −2 m/s² while vision only asks ≥ −0.5. Driver-brake metrics use
  [−3, +0.5] s (anticipation), [−3, +2] s (first request) and [−3, +1] s (missed hard slowdown) around the brake press.

## Compared with the other radar interfaces in openpilot

| interface (opendbc at the openpilot used for the replays) | code lines | what it does |
|---|---|---|
| Toyota (older radars, 0x210-0x22F) | 70 | `VALID` flag plus a score / valid counter; pass-through |
| Tesla (Continental, like the ARS510) | 66 | `Tracked`; publishes `Meas` as `measured`; radar status for faults |
| Honda | 60 | range < 255; pass-through |
| Hyundai | 55 | track `STATE`; pass-through |
| Rivian | 54 | `STATE`; pass-through |
| Chrysler | 56 | pass-through |
| GM | 71 | pass-through of the radar's targets |
| Ford | 184 (272 lines in all) | clusters raw Delphi detections into tracks |
| **ARS510 `acc` profile** ([`upstream/ars510_acc_target.py`](../upstream/ars510_acc_target.py)) | 33 | the radar's ACC target as one point: target-present flags; pass-through |
| **ARS510 openpilot version** ([`upstream/ars510_radar.py`](../upstream/ars510_radar.py)) | 187 | `fused` in one file; part by part in [10](10_research_directions.md#parts-of-the-openpilot-file) |
| … transport, CRC, slot decode, track IDs, ego speed, RadarInterface wrapper | 103 | a 742-byte record from 106 CAN frames, 20 slots of bit fields |
| … ACC target decode and association | 27 | match the radar's own ACC target to one track |
| … Kalman speed filter, its young-track factor and publication gates | 29 | the filter itself |
| … range fusion, path gate, state pruning, fork compatibility | 24 | lead stability, next-lane leads, bounded state |

- The other interfaces, except Ford's, pass the radar's tracks through with validity and lifecycle checks and leave
  speed filtering to radard.
- The ARS510's `240|7` code follows the width of its far-range speed error as a continuous per-reading scale (◐), so `fused`
  weights each reading in one scalar filter ([12](12_kalman_filter.md#the-model)); the replays above are its evidence.
- Moving that weighting into radard (a per-point speed variance) would make this interface a pass-through like the
  others ([10](10_research_directions.md#towards-an-upstream-comma-interface)).
