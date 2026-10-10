# 07. Velocity excursions (the false-closing issue)

The radar's velocity is its steadiest channel from record to record ([06](06_accuracy.md)), with one systematic flaw: on a settled track the
velocity sometimes **drifts for 1-10 s while the radar's ACC distance and the camera hold steady**, mostly as a **false closing beyond 40 m**.
In openpilot that shows up as extra jitter in the plan and, rarely, a braking request only the radar makes. The
default `fused` profile handles it with one Kalman filter per track ([12](12_kalman_filter.md)).

**In short**

- 80-87% of excursions are false closings ([`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)); they ramp up over about 1 s.
- Rare close in, common far out: radar and vision disagree by ≥ 2 m/s for 1% of radar-lead time at 0-20 m and 49%
  beyond 80 m ([below](#how-often-on-real-drives)).
- Their size matches the speed-error code the radar reports (`240|7`, ◐); the radar's own ACC tracker follows the
  same car smoothly.
- `fused` weights every reading by that uncertainty and leans on the radar's own ACC target: hard radar-only braking
  93 (`raw`) → 30 ticks on 20 held-out routes.

## What an excursion looks like

![excursion sample](img/vrel_excursion_sample.png)

*Bundled sample `highway_vrel_excursion_25s.csv.gz`: a lead at ~48 m, slowly opening; its over-ground speed falls
33.5 → 25.0 m/s and recovers within ~1.2 s. Through openpilot's radard and planner this produced a forward-collision
warning and −3.5 m/s².*

![false closing sequence](img/shots/excursion_false_closing_sequence.jpg)

*Four frames of the same event over 4 s: the lead sits at 41-51 m and its box keeps its size, while the radar lead's
vRel reads +2.2 to +2.5 m/s and then −2.5 m/s; its −6 m/s low falls between the frames (plot above).*

![false closing on a real drive](img/analysis/jitter_false_closing_event.png)

*A long one at ~85 km/h: vRel drifts to −12 m/s over ~9 s while the range stays at 85-110 m and vision holds steady.*

- **Smooth drift:** the gap to the ACC target builds up over about 1 s in small record-to-record steps.
- **The object-list range walks** by metres at 60-100 m and can drift with the speed (the drive-E sample slides 46 → 33 m),
  so the ACC distance and the camera are the steady references.
- **The motion state moves with it:** the acceleration field `84|10` follows the drift.

<details>
<summary>What the radar's waveform allows</summary>

### What the radar's waveform allows

A published handbook table for the ARS510 (Winner and Waldschmidt, *Automotive Radar*, 2026, Table 15.3) gives 256
ramps (104 µs repetition), a 19 m/s single-cycle unambiguous radial-velocity span resolved over two cycles, 0.074 m/s resolution, 0.15 m/s
separability (the step of `64|10`) and three bandwidths by ego speed (range resolution 0.4 / 0.7 / 0.98 m); generic
product values (○ for this firmware). Excursion offsets sit well inside that span (median −4.0 m/s against vision,
−3.1 below 40 m to −4.8 at 80-100 m); unwrapping by ±19 m/s changes 57 of 900 labelled samples. Excursions therefore
sit inside the unambiguous span (◐) and build up over about 1 s, which fits low-SNR measurements at range
([`waveform_source.json`](../data/analysis/summaries/waveform_source.json)).

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
  ([03](03_slot_fields.md#kinematics)): RMS ≈ 0.04-0.06 m/s per count (≈ 0.9 m/s at code 15, 1.2-1.3 m/s at code 30;
  [`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)).
  Codes grow with range, so far tracks carry a 1-3 m/s error scale.
- A Gaussian with σ = 0.045 × code predicts the share of far records inside an excursion (5.3% observed vs 6.5%
  predicted; 7.7% vs 5.5% on fresh drives; [`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)). The error is low-pass (~0.3 Hz), so a 1-3σ deviation lasts seconds.
- `240|7` (◐) scales with the width of far errors, which is why `fused` uses it to weight readings.

<details>
<summary>Caveats and the residual error</summary>

- 0.045 is a fitted Gaussian-equivalent: the robust (MAD) core is ~0.027 m/s per count over codes 12-70, and heavy
  tails (kurtosis 1.3-8) lift the RMS. Above code ~60 the main set's error grows faster than proportionally (figure).
- Within a range band, `240|7` separates excursion records below 40 m (AUC 0.95) and barely beyond (0.42-0.55)
  ([`continental_field_map.json`](../data/analysis/summaries/continental_field_map.json)).
- Across 13.6k candidate signals, the object's own state explains part of the object-list error: `84|10` acceleration (R² 0.11), the uncertainty code `264|8`, width `216|6`. Together the object's state
  and 3 s history predict ~37-43% of the error variance on 40 fresh one-minute segments ([`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)), spread over many fields
  ([`excursion_sigma_scale.json`](../data/analysis/summaries/excursion_sigma_scale.json)).

</details>

<details>
<summary>Compared with an optical reference (camera scale change)</summary>

### Compared with an optical reference

![object-list velocity disagreement with the optical reference](img/analysis/video_truth_excursions.png)

- Reference: `−(native range + 1.52 m) × d ln(scale)/dt` from ECC registration of the lead's rear over 0.5-1 s. It
  is independent of the radar's velocity and takes its metric scale and association from the radar's range.
- 2,657 two-second windows in five 10-130 m bins: native more closing than the reference by > 2.5 m/s in
  0.2 / 2.2 / 10.6 / 15.0 / 20.9% of windows; the opposite in 0 / 0.2 / 0.6 / 2.2 / 1.4%
  ([`video_truth.json`](../data/analysis/summaries/video_truth.json)).

</details>

## What openpilot does with it

- radard's per-track Kalman filter smooths **vRel only** and passes a drift into `vLeadK` and `aLeadK` (the bundled drive-A excursion drew a −3.5 m/s² request).
- The 25% distance gate keeps the drifting track matched to the vision lead (±28 m at 110 m).
- The planner projects `aLeadK` forward with a 1.5 s decay.

![roughness by state](img/analysis/jitter_roughness_by_state.png)

*20 held-out routes: in steady following radar+vision is only +0.005 m/s² RMS rougher than vision; around radar/vision
disagreements (20% of the time) +0.032, about 70% of the extra roughness.*

## How it is filtered

`fused` (the default) handles excursions with one Kalman filter per track that weights the object list and the radar's
ACC target by their own uncertainty. The model, every constant, what each part contributes and
the variants tested are in [12 Kalman speed filter](12_kalman_filter.md).

## Radar-internal signals that move with an excursion

| signal | behaviour during an excursion |
|---|---|
| `240\|7` velocity-error scale | higher (≈ 0.045 m/s per count against the ACC target) |
| `264\|8` uncertainty code (σ ay candidate) | more samples at code 1; codes 4-8 rise 3-6 s later |
| 0x235 ACC target | disagrees with the object's vRel (when present) |
| lane state `128\|3` | changes more often, also on real closings |

Together they give a soft prior ([10](10_research_directions.md#for-the-drift-discriminator)): a classifier on every
slot field and its 1 s changes separates false-closing frames from real closings with a cross-validated AUC of 0.78
(0.75 within one range and speed band), and catching half of the false-closing frames flags 15 % of real closings and
10 % of the frames where the lead really brakes. The radar's clean speeds come from its other tracker outputs: the ACC
target, the two summaries and the sparse 0x680 reports ([`frame_trust_classifier.json`](../data/analysis/summaries/frame_trust_classifier.json)).
