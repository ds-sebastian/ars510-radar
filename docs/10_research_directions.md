# 10. Research directions

The open questions of the project, each written as the question and the data that would answer it, ordered by how
directly the answer improves the radar in openpilot. [16: Routes and tests](16_routes_and_tests.md) turns them into
recording procedures, physical references and hand-in checklists; begin with the smallest observable contrast before a
long session.

Two install profiles frame the questions. `acc` (the default) publishes the radar's ACC target alone; `fused` publishes
every settled track with one Kalman speed filter per track. A question says which profile it concerns when it concerns
one. The upstream proposals, the parts ledger and the evidence for the ACC target alone are in
[17: Upstream proposals](17_upstream.md); the AEB / PCS questions are in [15: AEB and PCS](15_aeb_pcs.md#open-questions).

## For a better ride

1. **The far range of every track.** *Where does the object list's short far reading come from, and what is the true
   distance?* The object list reads far cars 5-8% short of the radar's own ACC distance at 50-100 m, and the vision lead
   agrees with the ACC distance ([06](06_accuracy.md#distance)). `acc` publishes the ACC distance; `fused` takes it for the
   car the radar follows, publishes only that car beyond 60 m, and smooths the other tracks' object-list range separately
   from the speed filter (the object list's range rate and speed disagree by 10-20%,
   [12](12_kalman_filter.md#what-runs-before-and-around-the-filter)). *Data:* a drive behind a second car with a GNSS
   logger gives the true far distance ([T03/T04](16_routes_and_tests.md)).
2. **More of the lead covered by the radar's own trackers.** *When and why does the radar drop or delay its ACC target?*
   The target is present for 99% of radar-lead time at 15-80 m and 66% beyond 80 m on the owner's car
   ([08](08_openpilot_integration.md#on-the-road)). Beyond 60 m both profiles take only that target, and a fast far
   closing waits about 1 s for the radar to pick the car (0.8-1 s on the two cars measured,
   [`far_acc_only.json`](../data/analysis/summaries/far_acc_only.json)). *Data:* stock-ACC drives
   ([T08](16_routes_and_tests.md#t08-stock-acc-and-additional-target-reports)) with the target's acquisition and loss
   logged next to range, closing speed, curvature and camera state; every second of added coverage moves far leads from
   the camera to the radar.
3. **A controlled factory-camera comparison.** *What does the factory camera contribute to the ACC target's selection and
   kinematics?* The target's distance and speed hold steady where the camera's association (`112|3`) changes (steps at
   association onset: 0.06 m and −0.01 m/s), the camera's bus-1 frames arrive continuously (longest gap 0.78 s in 698
   one-minute segments), and the radar acquires far targets while the association field reads 0 (539 day acquisitions beyond 60 m, all
   with association 0; [05](05_acc_target_and_support.md),
   [`acc_target_camera.json`](../data/analysis/summaries/acc_target_camera.json)). *Data:* a paired parked or
   controlled-site intervention, clear against covered, on matched target paths
   ([T09](16_routes_and_tests.md#t09-factory-camera-dependence)); selection, kinematics and function restriction are
   compared separately, and the cover stays on only while parked.
4. **Physical units for the uncertainty fields.** *What error in m/s does one count of `240|7`, `232|7`, `224|7` and
   `248|7` stand for?* They are scaled against the radar's ACC target, the radar's own estimate
   ([03](03_slot_fields.md#uncertainty-and-quality)), and `fused` weights the object-list speed by 0.045 m/s per count of
   `240|7`. *Data:* an independent reference (a second car with a GPS logger, or a known far target; T05) gives them
   physical units and tests `fused`'s weights directly.
5. **Where the weighting lives.** *Can radard weight each radar reading by its reported variance as well as the interface
   does?* radard's per-track filter suits radars with a clean relative speed, and the ARS510's weighting lives in the
   interface. In replay (against `fused` 2.4, the version these radard variants ran against), a pass-through interface that
   hands radard each reading's variance, with radard also fusing the vision lead's speed, asks for 57 hard radar-only ticks
   on the held-out drives against `fused`'s 30; radard's vision fusion (`VISION_V_STD_SCALE` 2.0) on top of `fused` lowers
   unnecessary braking against the hindsight oracle (5.4 → 3.8 s on road drives) and raises missed braking (7.2 → 8.4 s;
   [`radard_side_options.json`](../data/analysis/summaries/radard_side_options.json)). *Data:* a radard filter designed
   for per-point variance, replayed on the same 27 drives and road drives against those numbers.
6. **Use the radar's own lead acceleration.** *How should the ACC target's relative acceleration (0x235 byte 2) reach the
   planner?* It tracks lead acceleration better than radard's derived `aLeadK` against a smoothed lead acceleration from
   the object-list speed (correlation 0.64 vs 0.56, RMS 0.69 vs 0.80 m/s², wobble 0.13 vs 0.15;
   [`acc_unit_recompute.json`](../data/analysis/summaries/acc_unit_recompute.json)). radard derives `aLeadK` from vRel for
   every car. Used as `aLeadK` for the ACC target's track (fork-side radard, replay on `fused` 2.4) it starts braking
   0.02 s earlier with 28 against 30 hard ticks, and a newly acquired target's acceleration starts near zero and replaces
   the deceleration radard has already built up, so more braking comes late on the road drives (missed braking
   7.2 → 10.8 s against the oracle, [`radard_side_options.json`](../data/analysis/summaries/radard_side_options.json)).
   *Data:* replays of a hand-over rule for newly acquired targets on those road drives.
7. **Lead acceleration in fork planners.** *Does a decaying extrapolation or an `aLeadTau` floor for radar leads remove the
   brake-then-accelerate swing?* StarPilot extrapolates `aLeadK` unchanged above 35 mph (read from its source, ○).
   *Data:* StarPilot replays with `tools/fork_lead` using each variant ([14](14_forks.md)).
8. **Road miles with `acc` and `fused`.** *Do the replay results hold in closed loop?* The replay results
   ([11](11_profiles_compared.md)) cover 16.9 moving hours on two cars; `fused` has closed-loop road drives
   ([08](08_openpilot_integration.md#on-the-road)), and closed-loop drives with `acc` are the next evidence. *Data:* drives
   with flagged moments, ideally from a second car, driver or radar firmware, with the installed profile recorded
   ([T13](16_routes_and_tests.md#t13-fresh-road-and-parser-validation)).

## Learn from Toyota's own longitudinal control

The owner's experience (○) is that Toyota's stock ACC on this car brakes and slows well for a lead in its own lane and holds on
to a lead that leaves for a turning lane. These are likely two different parts of its pipeline, and openpilot can learn
from the first:

- **Target choice.** The radar picks its ACC target ([05](05_acc_target_and_support.md)) and
  keeps a departing car until its centre is a median 1.64 m off-axis (middle half 0.67-2.16 m; 22 departures). Measured
  against the radar's own lane boundary from the 0x85 curve cells, the release comes when the car's centre is a median
  0.29 m inside that line (21 departures), which matches the rule "keep the target until its centre reaches my lane
  line" ([`acc_target_choice.json`](../data/analysis/summaries/acc_target_choice.json)). On two matched cut-ins on the
  fresh drives (n = 2, so the result is a hint), openpilot's model moved to the new lead first (1.5 s and ≥ 6 s
  earlier). `acc` hands the radar's choice to openpilot as one point and radard's camera match decides which lead the
  planner follows; `fused` publishes every track and leaves the choice to openpilot's model, which sees lanes.
- **The signal (Toyota's strength).** The radar's ACC speed is smooth and consistent with range during excursions,
  and 0x235 also carries a filtered relative acceleration. Both profiles use the speed (`acc` publishes it, `fused` takes it as a
  measurement).
- **The control law (◐, fitted on two cars).** While following, Toyota's 0x343 command is a linear law on its own ACC
  target: about 0.02 m/s² per metre of gap error, 0.25 m/s² per m/s of closing speed, and a time gap of about 1.1 s (1-bar
  setting, U1). The command trails the target through a short dead time (0.1 s), a slow first-order lag and a rate limit.
  A second car's stock drive fits once a **set-speed cap** is added: at or above the set speed Toyota holds about 0
  even with a large gap (u1 law R² −0.69 → 0.58 on the second car, U1 unchanged at 0.66). One law with that cap
  fits both cars (time gap 1.07 s). The law also explains Toyota's patience on far leads: a car closing at 3.5 m/s becomes
  the ACC target at 94 m, and Toyota holds +0.06 m/s² for 7 s. It first brakes at 66 m (about 15 s to contact) and
  reaches −0.83 m/s² at 52 m. The three recorded lead changes happened under gas override or at the set-speed cap; a lead
  change or cut-in under stock control with the driver off the gas is the data this study needs
  ([`stock_acc_law.json`](../data/analysis/summaries/stock_acc_law.json)).

Proposed study:

1. **Record stock ACC.** 20-30 minutes of mixed traffic with Toyota's ACC in control and the comma device logging
   (openpilot longitudinal off). The radar's own `ACC_CONTROL` (0x343) command then appears next to its target.
2. **Fit Toyota's law.** Model the requested acceleration from the radar's ACC target (distance, closing speed,
   relative acceleration), ego speed and the following-distance setting; compare it with openpilot's planner on the
   same moments (replayed with each radar profile).
3. **Separate signal from tuning.** Replay openpilot's planner fed with the radar's ACC values for the in-lane lead,
   and Toyota's fitted law fed with openpilot's lead. If the planner with Toyota's signal already behaves like Toyota,
   the remaining gap is radar handling (this repo); otherwise it is planner tuning, which belongs in the fork's
   longitudinal settings.
4. **Within-lane decisions.** Score both on in-lane braking events (onset, peak deceleration, jerk, gap at the end)
   and on lane-change / turn-lane departures, so a Toyota-like tune keeps openpilot's lead selection.

## For the drift discriminator

The goal: tell a velocity excursion from a real closing within about 1 s ([07](07_velocity_excursions.md)).

1. **A far-range truth drive.** *What is the lead's true velocity at 40-120 m?* A second car that logs its own speed (a
   second comma device, or a 5-10 Hz GNSS logger) gives it. The video-looming reference spans 10-130 m with 148 of its
   2,657 windows beyond 90 m, and shares the camera with the vision model
   ([`video_truth.json`](../data/analysis/summaries/video_truth.json)); a second car's own speed adds a reference
   independent of the camera.
2. **The first second of an excursion.** *Do velocity steps at onset share a size and sign?* Steps of a consistent size
   and sign indicate wrong-branch Doppler measurements leaking into the tracker; ordinary-sized steps indicate low-SNR
   tracking ([07](07_velocity_excursions.md#what-the-radars-waveform-allows)). *Data:* the 16.7 Hz records of the first
   second of logged excursions, binned by size and sign.
3. **Ego-speed waveform modes.** *Does the range noise floor step at the ego speeds where the handbook table's three
   bandwidths change?* Finding the steps, and the excursion rate in each mode, ties drift risk to a radar setting. *Data:*
   range noise and excursion rate in steady-speed stretches at several ego speeds.

## For the decode

- **Lateral frame and range zero from measured rotation.** *What are the lateral origin and scale, and the range zero?*
  Ordinary turns past parked cars give 69 codes per metre (65-74.5, [06](06_accuracy.md#lateral-position)). *Data:* slow
  turns around surveyed reflectors, with yaw and the radar-to-reference lever arm measured, separate scale from origin
  ([T07](16_routes_and_tests.md#t07-lateral-motion-heading-and-turning)); gyro closure is a consistency check, and the
  physical zero and a per-cent calibration take the surveyed reference.
- **`272|5` under a known overhead object.** *Which physical quantity is `272|5`?* Its ranking of pedestrians below cars
  points to a size- or reflectivity-like quantity. *Data:* passes under a bridge or gantry of known clearance and past
  parked vehicles of known height relate the code to height.
- **0x85 curve cells: units and the remaining fields.** *What are the units of heading and curvature, and the roles of the
  flag `79|1` and the structured fields `0|9`, `20|4`, `24|4`, `44|4` and `80|6`?* Heading `48|16` and curvature `64|15` are
  bounded to 1.6-2.2e-5 rad and 2.0-2.7e-6 1/m per code ([04](04_metadata_record_0x85.md#lane--road-boundary-curves)).
  *Data:* a camera lane polynomial with matched timing, or a drive along a surveyed curve of known radius.
- **Class 5.** *Is class 5 a cyclist?* *Data:* a few recorded passes of a cyclist and of a pedestrian test the bicycle
  reading of its size and speed.
- **0x195 `q10` with brake pressure.** *Which deceleration quantity does `q10` carry?* *Data:* the logged brake pressure or
  the brake-assist state next to the event code.
- **The radar's ACC tracker bytes and the night light records.** *What are the units of the two bytes of 0x237 that rise
  while the ACC target accelerates or brakes, and of the camera's 0x240 / 0x244 light-source records at night?*
  ([05](05_acc_target_and_support.md)). *Data:* a drive behind a car with known braking, and a night drive past lights at
  known positions.
- **What the camera association changes.** *What does `112|3` (association: inside 45 m by day, farther at night,
  [03](03_slot_fields.md#camera-association)) change in the radar's outputs?* *Data:*
  [T09](16_routes_and_tests.md#t09-factory-camera-dependence) compares matched target paths while parked; the
  observations fit every camera weight from 0 to 0.9 in exact mixture identities, so the total input weight needs the
  paired parked test
  ([`acc_camera_identifiability.json`](../data/analysis/summaries/acc_camera_identifiability.json)).

## For the integration

- **Other cars and firmware.** *Does the layout hold on other firmware?* openpilot's fingerprints list `8821F0R01100` for
  the RAV4 2022 platform, the only other `8821F0R` entry besides the documented `8821F0R03100`. *Data:* one capture from
  such a car confirms the layout and adds it to `ARS510_FW_VERSIONS` (until then the installer detects it by the bus-1
  fallback on a warm restart); a second unit also shows whether 0x500 / 0x502 differ per unit.
- **More closed-loop driving** with `acc` and `fused`, on a second car or with another driver
  (question 8 above).
