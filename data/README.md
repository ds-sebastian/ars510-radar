# Data

## `sample/`: real CAN captures

Three short highway captures, used by the tests and figures:

| file | length | content |
|---|---|---|
| `highway_following_30s.csv.gz` | 30 s | drive A: following a lead that closes from ~88 m to ~45 m; an adjacent-lane car at ~75 m |
| `highway_vrel_excursion_25s.csv.gz` | 25 s | drive A: a settled lead at 41-57 m whose over-ground speed dips ~8 m/s for ~1 s while its range opens ([docs/07](../docs/07_velocity_excursions.md)) |
| `highway_acc_anchor_24s.csv.gz` | 24 s | drive E: includes the radar's ACC target (0x235 / 0x237); at ~18 s the lead's object-list speed falls to −5.8 m/s and its range slides 46 → 33 m while the ACC target stays at −0.7 m/s ([docs/07](../docs/07_velocity_excursions.md#7-acc-anchor-anchor)) |

Format `t_s,bus,address,data_hex`, times rebased to 0. Only bus 1 0x80 / 0x81 / 0x85 / 0x86 / 0x192 (and 0x235 / 0x237 in
the drive E sample) and bus 0 0xB4 are included; no GPS, video, route or device identifier.

## `analysis/`: anonymised analysis dataset

Three drives: **A** (development, 26 min, mixed), **B** (city, 43 min), **C** (highway, 24 min). Segment labels
`A00` … `C23` are one-minute files in order; `t*` columns are seconds from each segment's first record. No route or
dongle IDs, dates or GPS.

| file | rows | content |
|---|---|---|
| `slots.parquet` | 174k | every occupied 0x80 slot with age ≥ 1: decoded `x` (dRel), `y` (yRel), `vrel`, `v_ground`, `v_ego` (0xB4), `track`, `slot`, `age`, `init_template`, and every raw field (`DREL`, `YREL_LEFT`, `VLONG_OVER_GROUND`, …, `UNK_<start>_<len>`) |
| `camera_pairs.parquet` | 90k | radar tracks paired by bearing with narrow-camera YOLO boxes: box (`x1..y2`, `h`), box-growth closing speed over 2 / 4 / 6 s (`vcam2/4/6`), 1 s range derivative (`deriv1s`), 10 s range slope, ego speed from 0xB4 / carState / GPS, lead flag |
| `ground_contact.parquet` | 50k | camera ground-contact distance (`cam_ground_x`, flat-road projection) against radar `x` |
| `lateral_pairs.parquet` | 22k | camera lateral estimates against the raw lateral code |
| `lane_cells.parquet` | 48k | camera-matched 0x85 lane-curve cell rows (cells 2/3/8/9): offset, heading, curvature codes and bit 79, camera lane slope and curvature, ego-motion offset rate; segment labels are an index within this sample |
| `standstill_codes.parquet` | 15k | `64\|10` codes while ego is stopped; includes moving targets, with a dominant low-speed peak |
| `brake_events/E*_*.csv` | | drive-A brake-event windows: replay ticks, radar lead track, camera pair |
| `fault_injection.csv` | 81 | ghost / fault scenarios through radard and the planner |
| `stats.json`, `STATS.md` | | descriptive statistics from `tools/compute_stats.py` |

`slots.parquet` is radar-only. The camera files are references with their own limits: tracker swaps at range, hood
clipping below ~8 m, a flat-road assumption, and metric camera velocity that takes its scale from radar range.

`init_template` marks **869 allocation placeholders** among the 173,691 rows: age 1 with zero length and width
codes. Their `x = 0` is a placeholder, so exclude them from position, velocity and physical-object statistics.
Keep them for raw allocation/lifecycle analysis. The decoder already withholds these rows from publication.
`tools/mark_init_templates.py` adds or refreshes this column after a dataset rebuild; the dataset counts are in
[`init_templates_dataset.json`](analysis/summaries/init_templates_dataset.json).

## `analysis/summaries/`: numbers behind the docs

Aggregates from the research dataset, including the original 399-segment analysis across 24 route groups,
expanded 700-segment inventories, 20 held-out replay routes and closed-loop drives. The full captures are not bundled.

| doc | summaries |
|---|---|
| This dataset | `init_templates_dataset` (row counts and allocation-placeholder flags) |
| [02 Object list](../docs/02_object_list.md) | `stationary_listing_rule`, `header_allocation_count`, `prefix_alignment` |
| [03 Slot fields](../docs/03_slot_fields.md) | `continental_field_map` (existence probability, predicted flag and uncertainty split against the Continental object pattern), `midband_weight_triplet`, `weight_lateral_roles`, `weight_state128`, `attribute_recoding`, `full_movement_code`, `startup_low5_decay`, `initial_attribute_zeros` (joint age-1 attribute/position template and strict age-2 exits), `score16_countdown`, `score16_outcomes`, `velocity_heading`, `heading_component_bins` (declared bin limits and original-CAN-verified angle/component updates), `heading_default_state` (conditional angular-code states, exceptions and oncoming-like resets), `heading_interpretation` (checked component-held updates and conditional ego-path criteria), `rotating_kinematics`, `template_field_tests`, `camera_semantic_correction` (size and class associations), `class5_video_review` (candidate cyclist/person associations from a 700-segment inventory), `decode_references` (ego-motion comparisons: conditional path heading, lateral velocity, class kinematics) |
| [04 Metadata record](../docs/04_metadata_record_0x85.md) | `id85_lane_lateral_candidates`, `id85_parameter_presence`, `prefix_alignment`, `decode_references` (raw-word curvature association in bits 64-79), `id85_direction_code_structure` (high-bit transitions and original-record-checked relative-time example), `id85_lane_curve_cells` (heading and curvature against camera, ego-motion and ego-lane references; prefix flag copies; fresh and independent checks) |
| [05 ACC target](../docs/05_acc_target_and_support.md) | `acc_sender_clock` (sender clock fingerprint, per-minute phase series and tail-episode range consistency), `signal_atlas_and_acc_crosscheck`, `acc_target_arel`, `acc_distance_increment_closure`, `acc_unit_conventions` (raw domains, retained conversions and relative-scale limits), `acc_target_availability` (active OEM reporting with a fresh empty native list, scope and source limits), `event_pair_carries` (full event census, carry limits and source-verified relative-time example), `context_24x`, `selected_target_descriptors` (full descriptor lifecycle census and raw summary-word limits), `decode_references` (event-pair time-to-collision context) |
| [06 Accuracy](../docs/06_accuracy.md) | `figure_numbers` (velocity MSE, range walks), `camera_semantic_correction` (three-cornered hat), `far_range_camera_correction`, `camera_identity_correction`, `review_followup` (stopped targets), `radar_only_scales`, `lane_peaks`, `state_space`, `encoding_calibration` (nominal constants, host-standstill selection, interval membership and arithmetic sensitivity) |
| [07 Velocity excursions](../docs/07_velocity_excursions.md) | `jitter_problem_figures`, `jitter_source_and_interface_limit`, `interface_filters_preregistered`, `radard_vision_fusion`, `jitter_event_scope_audit`, `velocity_guards`, `far_settling` (selected option, replay aggregates and relative-time example), `owner_driver_review` (guard recovery limits and driver/override aggregates), `ramp_limiter` (selected option, replay aggregates, per-event reactions and relative-time example), `waveform_source` (published waveform parameters and excursion offsets against the velocity span), `sunnypilot_profile_comparison` (native profiles through original consumers, both prospective schedules and owner subgates), `excursion_mechanism_scope` (object-output coupling, candidate state semantics and causal/physical-identity limits), `video_truth` (conditional optical residuals, actual scale-fit inputs, `240\|7` association, model-dependent ACC error scales, replay comparison and exploratory camera veto), `camera_route_scoped_planner` (four prior-used chains, route-scoped R0 plus camera comparison, unchanged response aggregates and unmet strict nuisance gate), `fresh_s4_replay` (eight fresh routes, preregistered jump-guard simplification overlay, both unchanged sunnypilot schedules and remaining validation limits), `acc_anchor` (ACC-anchor replay on held-out, owner, further and fresh drives), `layer_ablation` (each filter layer added and removed, with sources) |
| [08 openpilot integration](../docs/08_openpilot_integration.md) | `acc_anchor`, `driver_agreement_preregistered`, `openpilot_integration_replay`, `sunnypilot_installation`, `velocity_guards`, `far_settling`, `ramp_limiter`, `sunnypilot_profile_comparison` |

`figure_numbers.json` is written by `tools/make_analysis_figures.py` from the bundled tables; the others are imported
from the research workspace.

## `reference/slot_bit_map.json`

Per-bit statistics of the 0x80 slot (288 bits), the 0x80 header and the 0x85 record from 13 one-minute segments of
drive A: flip rates, one-rates and the automatic carry-chain field split. `tools/build_cabana_route.py` builds the
Cabana DBC's slot layout from it.
