# Data

## `sample/`: real CAN captures

Two short captures from drive A (highway), used by the tests and figures:

| file | length | content |
|---|---|---|
| `highway_following_30s.csv.gz` | 30 s | following a lead that closes from ~88 m to ~45 m; an adjacent-lane car at ~75 m |
| `highway_vrel_excursion_25s.csv.gz` | 25 s | a settled lead at 41-57 m whose over-ground speed dips ~8 m/s for ~1 s while its range opens ([docs/07](../docs/07_velocity_excursions.md)) |

Format `t_s,bus,address,data_hex`, times rebased to 0. Only bus 1 0x80 / 0x81 / 0x85 / 0x86 / 0x192 and bus 0 0xB4
are included; no GPS, video, route or device identifier.

## `analysis/`: anonymised analysis dataset

Three drives: **A** (development, 26 min, mixed), **B** (city, 43 min), **C** (highway, 24 min). Segment labels
`A00` … `C23` are one-minute files in order; `t*` columns are seconds from each segment's first record. No route or
dongle IDs, dates or GPS.

| file | rows | content |
|---|---|---|
| `slots.parquet` | 174k | every occupied 0x80 slot with age ≥ 1: decoded `x` (dRel), `y` (yRel), `vrel`, `v_ground`, `v_ego` (0xB4), `track`, `slot`, `age`, and every raw field (`DREL`, `YREL_LEFT`, `VLONG_OVER_GROUND`, …, `UNK_<start>_<len>`) |
| `camera_pairs.parquet` | 90k | radar tracks paired by bearing with narrow-camera YOLO boxes: box (`x1..y2`, `h`), box-growth closing speed over 2 / 4 / 6 s (`vcam2/4/6`), 1 s range derivative (`deriv1s`), 10 s range slope, ego speed from 0xB4 / carState / GPS, lead flag |
| `ground_contact.parquet` | 50k | camera ground-contact distance (`cam_ground_x`, flat-road projection) against radar `x` |
| `lateral_pairs.parquet` | 22k | camera lateral estimates against the raw lateral code |
| `standstill_codes.parquet` | 15k | `64\|10` codes of stopped objects while ego is stopped |
| `brake_events/E*_*.csv` | | drive-A brake-event windows: replay ticks, radar lead track, camera pair |
| `fault_injection.csv` | 81 | ghost / fault scenarios through radard and the planner |
| `stats.json`, `STATS.md` | | descriptive statistics from `tools/compute_stats.py` |

`slots.parquet` is radar-only. The camera files are references with their own limits: tracker swaps at range, hood
clipping below ~8 m, a flat-road assumption, and metric camera velocity that takes its scale from radar range.

## `analysis/summaries/`: numbers behind the docs

Aggregates from the research dataset, including the original 399-segment analysis across 24 route groups,
expanded 700-segment inventories, 20 held-out replay routes and closed-loop drives. The full captures are not bundled.

| doc | summaries |
|---|---|
| [02 Object list](../docs/02_object_list.md) | `stationary_listing_rule`, `header_allocation_count`, `prefix_alignment` |
| [03 Slot fields](../docs/03_slot_fields.md) | `midband_weight_triplet`, `weight_lateral_roles`, `weight_state128`, `attribute_recoding`, `full_movement_code`, `startup_low5_decay`, `score16_countdown`, `score16_outcomes`, `velocity_heading`, `rotating_kinematics`, `template_field_tests`, `camera_semantic_correction` (size and class associations), `class5_video_review` (candidate cyclist/person associations from a 700-segment inventory) |
| [04 Metadata record](../docs/04_metadata_record_0x85.md) | `id85_lane_lateral_candidates`, `id85_parameter_presence`, `prefix_alignment` |
| [05 ACC target](../docs/05_acc_target_and_support.md) | `signal_atlas_and_acc_crosscheck`, `acc_target_arel`, `acc_distance_increment_closure`, `event_pair_carries` (full event census, carry limits and source-verified relative-time example), `context_24x`, `selected_target_descriptors` (full descriptor lifecycle census and raw summary-word limits) |
| [06 Accuracy](../docs/06_accuracy.md) | `figure_numbers` (velocity MSE, range walks), `camera_semantic_correction` (three-cornered hat), `far_range_camera_correction`, `camera_identity_correction`, `review_followup` (stopped targets), `radar_only_scales`, `lane_peaks`, `state_space` |
| [07 Velocity excursions](../docs/07_velocity_excursions.md) | `jitter_problem_figures`, `jitter_source_and_interface_limit`, `interface_filters_preregistered`, `radard_vision_fusion`, `jitter_event_scope_audit`, `velocity_guards`, `far_settling` (selected option, replay aggregates and relative-time example), `owner_driver_review` (guard recovery limits and driver/override aggregates) |
| [08 openpilot integration](../docs/08_openpilot_integration.md) | `driver_agreement_preregistered`, `openpilot_integration_replay`, `sunnypilot_installation`, `velocity_guards`, `far_settling` |

`figure_numbers.json` is written by `tools/make_analysis_figures.py` from the bundled tables; the others are imported
from the research workspace.

## `reference/slot_bit_map.json`

Per-bit statistics of the 0x80 slot (288 bits), the 0x80 header and the 0x85 record from 13 one-minute segments of
drive A: flip rates, one-rates and the automatic carry-chain field split. `tools/build_cabana_route.py` builds the
Cabana DBC's slot layout from it.
