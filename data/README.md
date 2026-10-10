# Data

## `sample/`: real CAN captures

Three short highway captures, used by the tests and figures:

| file | length | content |
|---|---|---|
| `highway_following_30s.csv.gz` | 30 s | drive A: following a lead at ~75 m (55-86 m) while a left-lane car closes from ~88 m to ~45 m |
| `highway_vrel_excursion_25s.csv.gz` | 25 s | drive A: a settled lead at 41-57 m whose over-ground speed dips ~8 m/s for ~1 s while its range opens ([docs/07](../docs/07_velocity_excursions.md)) |
| `highway_acc_anchor_24s.csv.gz` | 24 s | drive E: includes the radar's ACC target (0x235 / 0x237); at ~18 s the lead's object-list speed falls to −5.9 m/s and its range slides 46 → 33 m while the ACC target stays at −0.75 to −0.9 m/s ([docs/12](../docs/12_kalman_filter.md#the-model)) |

Format `t_s,bus,address,data_hex`, times rebased to 0. Only bus 1 0x80 / 0x81 / 0x85 / 0x86 / 0x192 (and 0x235 / 0x237 in
the drive E sample) and bus 0 0xB4 are included; no GPS, video, route or device identifier.

## `analysis/`: anonymised analysis dataset

Three drives: **A** (development, 24 min decoded, mixed), **B** (city, 40 min), **C** (highway, 24 min). Segment labels
`A00` … `C23` are one-minute files in order; `t*` columns are seconds from each segment's first record. No route or
dongle IDs, dates or GPS.

| file | rows | content |
|---|---|---|
| `slots.parquet` | 174k | every occupied 0x80 slot with age ≥ 1: decoded `x` (dRel), `y` (yRel), `vrel`, `v_ground`, `v_ego` (0xB4), `track`, `slot`, `age`, `init_template`, and every raw field (`DREL`, `YREL_LEFT`, `VLONG_OVER_GROUND`, …, `UNK_<start>_<len>`) |
| `camera_pairs.parquet` | 90k | radar tracks paired by bearing with narrow-camera YOLO boxes (radar `y` here and in `ground_contact` is lateral code / 64; multiply by 0.96 for metres): box (`x1..y2`, `h`), box-growth closing speed over 2 / 4 / 6 s (`vcam2/4/6`), 1 s range derivative (`deriv1s`), 10 s range slope, ego speed from 0xB4 / carState / GPS, lead flag |
| `ground_contact.parquet` | 50k | camera ground-contact distance (`cam_ground_x`, flat-road projection) against radar `x` |
| `lateral_pairs.parquet` | 22k | camera lateral estimates against the raw lateral code |
| `lane_cells.parquet` | 48k | camera-matched 0x85 lane-curve cell rows (cells 2/3/8/9): offset, heading, curvature codes and bit 79, camera lane slope and curvature, ego-motion offset rate; segment labels are an index within this sample |
| `standstill_codes.parquet` | 15k | `64\|10` codes while ego is stopped; includes moving targets, with a dominant low-speed peak |
| `brake_events/E*_*.csv` | | drive-A brake-event windows: replay ticks, radar lead track, camera pair |
| `fault_injection.csv` | 82 | ghost / fault scenarios through radard and the planner |
| `summary_owner_case.csv` | 476 | relative-time owner-drive O1 comparison under fused 2.0: summaries off / on, and captured vision; saved planner and lead outputs, anonymous lead T1 |
| `lead_choice_cases.csv.gz` | 500 | two road moments for [docs/00](../docs/00_start_here.md#6-choosing-which-tracks-openpilot-sees) (`case`, relative `t`): planner request and published lead (range, radar flag) under vision only, 2.1 and 2.3 (2.4 asks the same), plus the camera lead range, the radar's ACC target range and ego speed; owner drives, no identifiers |
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
expanded 700-segment inventories, 20 held-out replay routes and closed-loop drives. The full captures stay in the research workspace.

| doc | summaries |
|---|---|
| This dataset | `init_templates_dataset` (row counts and allocation-placeholder flags) |
| Docs 01-06, 13 | `decode_claim_sources` (each decode claim with its value and the research-workspace experiment or bundled file behind it) |
| Docs 00, 07, 08, 10-13 | `driving_claim_sources` (the same for the driving claims) |
| [00 Start here](../docs/00_start_here.md) | the numbers of docs 08, 11 and 12; the two road moments in `analysis/lead_choice_cases.csv.gz` |
| [01 Radar bus](../docs/01_radar_bus.md) | `radar_disable_unfiltered` (openpilot's UDS radar disable on an unfiltered car: the radar's car-bus messages before and after, bus 1 rates and record CRCs through 26 min of alpha long) |
| [02 Object list](../docs/02_object_list.md) | `stationary_listing_rule` (which new objects survive the age-5 decision), `header_allocation_count`, `prefix_alignment` (0x80 / 0x85 pairing by clock and counter) |
| [03 Slot fields](../docs/03_slot_fields.md) | `continental_field_map` (existence probability, predicted flag, sigma order), `uncertainty_code_units` (sigma units against the ACC target), `slot_camera_association` (`112\|3`, `136\|4`, `181\|1` by day and night; `200\|7`, `256\|8`, `264\|8`; class confidence; `168\|10`), `score16_countdown`, `score16_outcomes`, `startup_low5_decay`, `full_movement_code`, `attribute_recoding` (`140\|3` against `163\|3`), `midband_weight_triplet`, `weight_state128`, `weight_lateral_roles` (lane weights and state), `initial_attribute_zeros`, `velocity_heading`, `heading_component_bins`, `heading_default_state`, `heading_interpretation`, `rotating_kinematics` and `template_field_tests` (lateral speed and acceleration scales), `class5_video_review`, `decode_references` (ego-motion references: heading, lateral velocity, class kinematics, in-path prediction, event-pair context) |
| [04 Metadata record](../docs/04_metadata_record_0x85.md) | `id85_lane_curve_cells` (heading, curvature and curvature rate against camera, ego-motion and ego-lane references; prefix flag copies), `id85_lane_lateral_candidates`, `id85_parameter_presence`, `id85_direction_code_structure` |
| [05 ACC target](../docs/05_acc_target_and_support.md) | `acc_target_frames` (bit map of 0x235 / 0x237 / 0x239 / 0x23B, closures, in-path ladder, 0x190 / 0x191), `acc_summary_units` (ACC speed and distance units, summary conversions), `acc_fields`, `acc_target_arel`, `acc_target_availability`, `acc_target_choice` (release of departing cars), `acc_sender_clock`, `signal_atlas_and_acc_crosscheck`, `selected_target_descriptors`, `summary_tracks`, `summary_window_time`, `event_pair_carries`, `context_24x`, `object_stream_0x680` |
| [06 Accuracy](../docs/06_accuracy.md) | `figure_numbers` (velocity MSE, range walks; written by `tools/make_analysis_figures.py`), `camera_semantic_correction` (three-cornered hat, sizes), `far_range_camera_correction`, `far_range_distance`, `camera_identity_correction`, `review_followup` (stopped targets), `radar_only_scales`, `lane_peaks`, `lateral_units`, `encoding_calibration` |
| [07 Velocity excursions](../docs/07_velocity_excursions.md) | `excursion_sigma_scale` (error per `240\|7` code, excursion incidence), `frame_trust_classifier`, `waveform_source`, `video_truth` (optical reference), `jitter_problem_figures` (real-drive census, roughness), `jitter_source_and_interface_limit` |
| [08 openpilot integration](../docs/08_openpilot_integration.md) | `road_v21` (fused 2.1.0 on the road and issue #66), `openpilot_integration_replay`, `driver_agreement_preregistered` (the pre-registered radar-vs-vision test), `radard_vision_fusion` (the optional radard patch) |
| [10 Research directions](../docs/10_research_directions.md) | `openpilot_file_parts` (each part of the openpilot file: code lines, cost of removing it, upstream status) |
| [11 Profiles compared](../docs/11_profiles_compared.md) | `profiles_vs_vision` (every profile against vision only on the 27 replay drives) |
| [12 Kalman speed filter](../docs/12_kalman_filter.md) | `fused_filter` (parameters, ablations and combinations of fused 2.0, radard cascade, ACC weight), `hard_braking_review`, `tracker_association`, `lead_choice_guards` (the 0.4 x ACC match and the path gate; 2.3 and 2.4 replays), `oracle_reference`, `kalman_variants`, `kalman_response`, `summary_owner_case` |
| [13 Car-bus messages](../docs/13_car_bus_messages.md) | `radar_car_bus_messages`, `target_366_coding`, `target_366_coverage`, `target_366_speed_domain` |

`figure_numbers.json` is written by `tools/make_analysis_figures.py` from the bundled tables; the others are aggregates
of the research workspace's runs. Drive counts: the replays use 27 drives (20 held-out routes, 4 further drives, 3 owner
sunnypilot drives); some JSON keys still carry an older `34` label for the same set.

## `reference/slot_bit_map.json`

Per-bit statistics of the 0x80 slot (288 bits), the 0x80 header and the 0x85 record from 13 one-minute segments of
drive A: flip rates, one-rates and the automatic carry-chain field split. `tools/build_cabana_route.py` builds the
Cabana DBC's slot layout from it.
