# 07. Velocity excursions (the false-closing issue)

The radar's velocity is its best channel ([06](06_accuracy.md)), with one systematic flaw: on a settled track the
velocity sometimes **drifts for 1-10 s while the range does not follow**, mostly as a **false closing beyond 40 m**.
In openpilot that shows up as extra jitter in the plan and, rarely, a braking request vision would not make. The
default `fused` profile handles it with one Kalman filter per track ([12](12_kalman_filter.md)).

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
  part of it: `84|10` acceleration (R² 0.11), the uncertainty code `264|8`, width `216|6`. Together the object's state
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

## How it is filtered

`fused` (the default) handles excursions with one Kalman filter per track that weights the object list, the radar's
ACC target and its summaries by their own uncertainty. The model, every constant, what each part contributes and
the variants tested are in [12 Kalman speed filter](12_kalman_filter.md).

## Radar-internal signals that move with an excursion

| signal | behaviour during an excursion |
|---|---|
| `240\|7` velocity-error scale | higher (≈ 0.045 m/s per count against the ACC target) |
| `264\|8` uncertainty code (σ ay candidate) | more samples at code 1; codes 4-8 rise 3-6 s later |
| 0x235 ACC target | disagrees with the object's vRel (when present) |
| lane state `128\|3` | changes more often, also on real closings |

None alone separates an excursion from a real closing within the first second ([10](10_research_directions.md)), and
together they give a soft prior, not a flag: a classifier on every slot field and its 1 s changes separates false-closing
frames from real closings with a cross-validated AUC of 0.78 (0.75 within one range and speed band), and catching half of
the false-closing frames flags 15 % of real closings and 10 % of the frames where the lead really brakes. The object list
carries no per-frame trust flag and no second speed; the radar's clean speeds are its ACC target, the two summaries and the
sparse 0x680 reports ([`frame_trust_classifier.json`](../data/analysis/summaries/frame_trust_classifier.json)).
