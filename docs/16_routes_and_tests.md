# 16. Routes and tests to record

This guide describes the captures that improve the ARS510 decode and its openpilot integration. Choose the
smallest session that separates your question; one route can cover several tests. Session lengths and repeat
counts below are planning suggestions; a field or profile passes validation through the checks at the end of this page.

**For most testers, start with T08 stock-ACC driving and T13 fresh road reports.** Parked diagnostics (T01/T02)
run with a maintainer-assisted read-only acquisition setup. Physical calibration comes from measured target geometry
(T03) or independently logged motion of both cars (T04).

## Choose a session

| Test | Setup / suggested time | Question it addresses |
|---|---|---|
| [T01](#t01-parked-startup-and-status) | parked, diagnostic kit; 10–15 min | startup, blockage/recovery, supported diagnostic DIDs |
| [T02](#t02-radar-reported-ego-speed) | stock/manual drive, passenger + diagnostic kit; 10–15 min | radar-reported ego speed versus B4 |
| [T03](#t03-surveyed-range-and-lateral-position) | surveyed closed site, helper; 30–60 min | distance zero/scale, lateral frame, far bias/jitter |
| [T04](#t04-independent-lead-speed-and-acceleration) | two instrumented cars, controlled site; 45–60 min | native speed, ego compensation, excursions, acceleration |
| [T05](#t05-physical-uncertainty) | repetitions of T03/T04/T07 | uncertainty units, covariance and measurement/track basis |
| [T06](#t06-identity-prediction-and-lifecycle) | parked ego, known target/occluder; 20–30 min | physical identity versus slots, prediction/reacquisition |
| [T07](#t07-lateral-motion-heading-and-turning) | surveyed target path and ego turns; 20–30 min | lateral motion/heading scale, frame and delay |
| [T08](#t08-stock-acc-and-additional-target-reports) | ordinary stock-ACC drive; 30–60 min | controller, target switches, ACC side fields, 0x366/0x680 |
| [T09](#t09-factory-camera-dependence) | parked ego, paired controlled-site conditions | factory-camera contribution to target selection/kinematics |
| [T10](#t10-class-scores-and-dimensions) | labelled/measured targets, parked ego; 30–45 min | class 5, score/probability meaning and target size |
| [T11](#t11-lanes-curves-and-five-cycle-patterns) | surveyed lanes/curves plus day/night routes | 0x85, lane/camera fields, duty pattern |
| [T12](#t12-pcs-and-event-reports) | incidental event or professional facility | warning/braking stages, 0x100/195/196/33E |
| [T13](#t13-fresh-road-and-parser-validation) | fresh ordinary drives and offline replay | installation, road behavior and transfer to other cars/forks |

### Conditions for recording

Road captures record normal driving: short gaps, cut-ins, oncoming traffic and hard braking come from traffic as it
occurs, and a passenger handles equipment and notes. Target placement, intentional occlusion and sensor-cover
conditions use a parked ego or a controlled site. Remove covers before driving away, and keep the sensor clean so a
fault reflects the condition under test. Record the actual installed profile (`acc` or `fused`) and version; raw CAN
logging works with either.

PCS/AEB is a professional test: Toyota advises leaving PCS testing to professionals
([RAV4 quick-reference guide, PCS section](https://assets.sia.toyota.com/publications/en/om-s/OM19V1QRG/pdf/OM19V1QRG.pdf)).
The recording specification and target controls are in [15](15_aeb_pcs.md#recording-pcs--aeb-events).

## What to keep

Keep complete **rlogs**, with adjacent segments before/after each event, and road video plus its frame indices
and SOF timestamps. Original full-CAN rlogs carry the evidence; qlogs, screenshots and decoded lead CSVs serve as indexes
into them. Preserve every bus/address, including lead-free periods. Particularly useful groups are:

- Radar bus: `0x80/85`, `0x100`, `0x190`–`0x196`, `0x235/237/239/23B`, `0x680`, camera/context messages.
- Car bus: `0xB4`, `0x343/344`, `0x283`, `0x320`, `0x33E/365/366/411`.
- Other log data: carParams/carState, radarState/liveTracks where present, model/planner/control outputs,
  calibration, pose/IMU, engagement, driver actions and bookmarks.

Record car/model year, radar firmware, fork/commit, parser version/profile, longitudinal mode, CAN-filter/DSU
configuration, lighting/weather and sensor condition. A filter or openpilot may replace the original radar's
car-bus output; verify what reached the log. State the logger and clock source along with the wall-clock start time.

Keep a small private session note and event table:

```text
test_id, relative_time_s, condition, target_alias, action,
dashboard_message, reference_clock, note
```

For measured geometry, record forward x, left-positive y, dimensions, measurement origin/method and error bound.
For motion, keep the original instrument export and quality flags, with time, clock mapping, position frame,
position/velocity/acceleration, yaw and their uncertainty where measured. Leave unmeasured values blank.

Two cars' wheel speeds are witnesses. Quality-qualified GNSS/Doppler or another calibrated reference for both vehicles
gives the physical truth; aim for at least 10 Hz for short excursions. Demonstrate clock offset/drift and reference
error; a sample rate or GPS wall clock describes cadence. Camera SOF, CAN receipt and radar acquisition are three
different times: decode exact video frame indices first, then read a projection offset as a delay.

## T01: parked startup and status

**Targets:** blockage/restriction DIDs `0x1033/2093`, optional voltage/temperature/angles `0x1016/1017/2009`,
and broadcast status ([13](13_car_bus_messages.md)). Catalog DID meanings are candidates (○) until read on the firmware.

1. Record a clean startup with normal full-CAN logging, beginning before radar wake-up if possible. Remain parked
   for two minutes; note ignition and dashboard messages. Power-up latency needs a logger that starts before the radar wakes.
2. Arrange the guarded read-only diagnostic kit with the maintainer before using it. The kit lives outside this repo's
   normal installer. The prepared probe takes exclusive Panda access with openpilot stopped, permits the specified
   DID reads and documented session/keepalive services, and restores no-output mode on exit. Check its on-car setup
   first and run only those reads (the kit carries read commands alone).
3. With ignition on and ego secured, collect baseline → covered → uncovered, 60 seconds each. Use a removable
   shield on a stand clear of the radar emblem, with a clean surface, held by the stand alone. Note messages and condition edges.
   If the state holds constant, record **unexercised** and stay parked.
4. Keep raw responses, negative responses/timeouts, request/response times and session mode. After a successful
   contrast, repeat the parked sequence once and verify recovery. Keep default/extended-session captures separate.

The prepared diagnostic probe saves responses and B4 (the radar CAN comes from a separate logger). A simultaneous broadcast comparison
needs a separate compatible passive logger on a shared clock; otherwise record a separate normal-logging condition
sequence and describe timing at the session level. Restart normal logging and verify recovery before normal use.
Dropped-message faults, blockage and object-list stalls are three conditions; record each as it occurs, and the car's
own events cover electrical faults.

## T02: radar-reported ego speed

**Target:** DID `0x1018` versus original `0xB4`, then an independent ego-motion reference where available.

1. Confirm the diagnostic setup can read 1018 while parked. With clear sensors, use an owner-approved stock/manual
   configuration and a passenger operating the equipment; run a Panda-owning probe with openpilot stopped.
2. Record stopped zero, several steady speeds, gentle acceleration/deceleration and stops, within site/road limits.
   Include both increasing/decreasing speeds, since speed changes identify lag. Ten minutes is a useful pilot.
3. Keep query/response latency, cadence, B4 and clock mappings. Compare offset, scale and apparent delay separately,
   including by direction of speed change. Report timing uncertainty alongside any lag.

Agreement qualifies the **reported representation**; the internal ego-speed producer, compensation path and per-object
acquisition time are measured in T04, which also calibrates native object speed.

## T03: surveyed range and lateral position

**Targets:** `32|12` zero/scale, forward versus radial range, `44|12` sign/scale, far bias and jitter ([06](06_accuracy.md)).

1. Park facing a clear measured area with one distinct rigid reflector or surveyed parked vehicle. Survey the radar/
   bumper and camera origins, target surface and height; label other plausible reflectors. Measure forward x and
   lateral y separately: tape/laser line-of-sight distance alone is radial range.
2. Pilot at 10–20 m for 20 seconds. Verify the target is reported and uniquely associated before a full grid.
   If it is suppressed or ambiguous, record that as the result.
3. If supported, use forward distances 5, 10, 20, 40, 60, 80, 100 and 120 m, as the site permits. Hold each for
   20 seconds, with three repeats in a changed visit order. At 20 and 40 m include lateral ±1.8 and ±3.5 m;
   a larger off-axis point within the observable field helps distinguish radial from forward range.
4. Photograph placements, retain measurement bounds and compare bias separately from per-frame jitter. Infer
   zero/scale with the reflecting-point uncertainty included; far geometry takes far measurements.

Code 160 is the initialization code; the measured zero comes from this survey. A surveyed vehicle position may differ from its radar scattering centre.

## T04: independent lead speed and acceleration

**Targets:** `64|10` nominal .15/510.5, empirical .149/.15 adjustment, real/false closing, `84|10` zero 511 / .04 and timing.

1. Use two cooperative instrumented vehicles on a controlled site. Record independently qualified motion of both,
   sensor origins, clock mappings and target identity. Pilot one minute of steady following before a long acquisition.
2. Cover observable near/middle/far bands, including 60–120 m, subject to safe speed/gap and site limits. Collect
   60–120 seconds steady in each band, then three gentle speed-change/recovery repetitions where practical.
3. Separate causes: lead steady/ego changes, ego approximately steady/lead changes, both steady. Include natural
   ACC-target idle spans, competing targets and switches; retain every disagreement and every dropped output.
4. Project physical motion into the declared radar axes. Compare fixed equations, zero, scale, bias, tails and delay
   separately. Relative acceleration requires the ego acceleration term and a qualified derivative/integrated reference.

An ego-only speed change separates a structurally motivated relative-speed candidate from a ground-speed
component; a broad field sweep needs a new candidate or source. Use held-out encounters
before changing constants; nominal decoding, physical calibration and parser tuning are three separate claims.

## T05: physical uncertainty

**Targets:** `224/232/240/248|7`, `256/264|8`, `200|7` ([03](03_slot_fields.md#uncertainty-and-quality)).

1. Reuse independently associated T03/T04 repetitions, plus T07 for lateral/heading support. Keep every raw code,
   saturation/default state, record clock and prediction candidate, with reference uncertainty.
2. Measure signed physical error/bias first, then conditional spread and coverage by code, range, age and maneuver.
   Hold out whole encounters/routes; repetitions are encounters, since adjacent radar samples are correlated.
3. Compare native-minus-truth, ACC-minus-truth and native-minus-ACC to expose common errors/covariance. Physical sigma
   comes from the native-minus-truth error; disagreement widths and second-difference scatter describe scatter.
4. Use T06 to examine update behavior. Observation-free intervals come from authenticated metadata or an independently
   established observation-free state; visual occlusion and `107|1` are indicators for it.

Calibration covers the exercised axes and codes; acceleration and heading units come from their own measurements.

## T06: identity, prediction and lifecycle

**Targets:** physical identity versus slot/age, `0|2`, `107|1`, bits 106/15/239, `109|3` and `14|1` ([02](02_object_list.md)).

1. Park ego and use one identifiable target on a measured path. A synchronized external view must retain its
   identity behind a known occluder; the occluder is also a possible reflector and must be labelled.
2. Capture visible tracking, 1/2/4 second occlusions and visible recovery, three repeats. Include departure followed
   by a **different** target at a similar position to distinguish persistence from reuse.
3. Add labelled stationary, same-direction and crossing cases. Oncoming examples come from normal separated-lane
   traffic or professionally arranged separated paths.
4. Annotate identity/visibility blind to the radar IDs. Analyze complete original record sequences across segment edges,
   including idle records, CRC errors and gaps. Separate allocation changes, predictions and physical motion errors.

A slot leaving the cache, an age of zero and a continuous slot age are allocation facts; physical identity comes from
the annotated external view, and trustworthy motion rests on the reference plus more than one correlated bit.

## T07: lateral motion, heading and turning

**Targets:** `44|12`, `74|10`, `96|10`, `208|6` ([03](03_slot_fields.md)).

1. With ego parked, record a target crossing a surveyed path in both directions, constant motion then gentle
   starts/stops/turns. Use several distances (e.g. 10, 20, 40 m), three repeats per direction; independently log motion.
2. Record target body orientation separately from velocity direction. Compare sign, zero, scale and delay separately.
3. Separately make slow left/right ego turns around surveyed stationary reflectors. Log yaw and the measured radar
   origin relative to the reference IMU/axle; account for rotation and lever-arm velocity.

Position derivatives carry their own uncertainty. Rotating relative-coordinate derivatives, ground components and
ACC lateral fields are three different quantities. Heading closure against native components tests heading; their
common speed scale comes from T04.

## T08: stock ACC and additional target reports

**Targets:** stock controller/selection, ACC lateral/in-path/tracker fields, 0x366/0x680 ([05](05_acc_target_and_support.md)).

1. Record 30–60 minutes with Toyota ACC available and openpilot longitudinal off, keeping normal logging. Verify
   original 0x343/344 and support reports reach the log; record any CAN filter/DSU and controller replacement.
2. Include normal following, gentle queues/stops/launches, curves, lead exits and naturally occurring switches.
   Bookmark following-distance settings, ACC use, driver interventions and warnings. Include a manual/disengaged section.
3. Keep adjacent/oncoming objects and video before/after lead departures. For metric high-code 0x366 sign/wrap,
   require independent identity/progression from T03/T04/T07; keep intervening low reports and reserved codes.
4. For 0x680 selectors/flags and ACC side fields, compare the **same identified target** across observable stationary,
   moving and lateral/path conditions. A forced stationary zero marks the stationary state; speed calibration references
   come from T04.

These selected reports are the radar's per-target outputs. Controller response/target choice, metric precision and camera
independence are three separate questions, and physical truth comes from the T03/T04 references.

## T09: factory-camera dependence

**Target:** factory-camera contribution beyond slot `112|3` association ([05](05_acc_target_and_support.md)).

1. Park on a controlled site with independent CAN logging, external video and a known target path. Identify the
   Toyota factory camera, distinct from the comma road camera; keep radar clear and controls disengaged.
2. Pilot camera clear → temporarily covered while parked → clear. Keep the ECU connected and the cover off while driving.
   Record functional output, faults/restriction and persistent track memory before comparing motion estimates.
3. If functional outputs exist in both conditions, repeat matched target paths clear–covered–covered–clear,
   acquiring fresh tracks. Compare selection separately from kinematic errors against the independent reference.

Function shutdown is evidence of dependency. The owner-car association transitions fit every camera weight from 0 to 0.9 equally
(maximum error 7e-15 on 2,501 rows; [`acc_camera_identifiability.json`](../data/analysis/summaries/acc_camera_identifiability.json)), so the camera's total
contribution comes from a professional facility test or access to the actual input channel when a parked case is unexercised.

## T10: class, scores and dimensions

**Targets:** existence `16|8`, candidate score `184|8`, class `163|3` / confidence `115|5`, length `56|7`, width `216|6`, size-like `272|5`.

1. With ego parked, independently label pedestrians, ridden bicycles, people walking bicycles, bicycles standing
   alone, motorcycles, cars and large vehicles where available. Pilot three distinct encounters per relevant category.
2. Measure dimensions and pose; capture stationary/moving and changed orientation at several ranges. These
   conditions separate measured size from templates. Labels come from the independent annotation, while the radar's
   size and speed codes are the quantities under test.
3. Include roadside/overhead and unoccupied reflectors as candidate controls, with physical path/contact geometry.
   Define what makes a control a non-obstacle (a stationary object can still be an obstacle). Keep volunteers out of any approach path ([15](15_aeb_pcs.md#recording-pcs--aeb-events)).
4. Keep early life, class changes, confidence changes, score drops and dropped outputs. Label blind to the radar
   codes. Class 5 cyclist/person hypotheses come with counterexamples as well as an overlapping projection.

A few encounters test availability. Reliability/coverage and probability calibration use a larger
independently labelled held-out set, including negative cases and reference uncertainty.

## T11: lanes, curves and five-cycle patterns

**Targets:** 0x85 curves/quality, lane weights/camera states, `168|10` / bit 183 ([04](04_metadata_record_0x85.md)).

1. Select surveyed/mapped straight and curved lanes, unequal widths, merges and marking starts/ends. Record road
   geometry/grade and uncertainty; metric lane geometry comes from the survey, with video as context.
2. Record both directions where permitted and similar day/night scenes. Bookmark normal lane changes and boundary
   visibility; preserve every cell and populated flag, alongside the ego-lane assignment.
3. Reuse T06 births/reacquisitions for duty phase across complete records, age, startup and counters. Compare
   coefficients under declared axes/polynomial convention, and lane weights against independent membership.

A repeated phase establishes schedule structure; hardware mode and payload meaning come from the lane references.
Cell roles and quality units take several lane geometries.

## T12: PCS and event reports

**Targets:** 0x100, 0x195/196, 0x33E and car-bus PCS stages. Follow the professional/passive recording specification
in [15](15_aeb_pcs.md#recording-pcs--aeb-events), including isolated target controls, synchronized reference/video, all-bus logs and driver actions.
The recorded alarm stage covers the alarm; brake stages, disabled-radar signaling and target attribution take the events
specified in [15](15_aeb_pcs.md#recording-pcs--aeb-events). Keep short-TTC states with PCS idle as controls. Brake requests come from
decoded stock events, and a replica that substitutes for a message is described as a replica.

## T13: fresh road and parser validation

1. Record the actual installed version/profile (`acc`, `fused` or another) and the [install check](../openpilot/README.md). On the first normal drive,
   verify radar-backed leads and communication health from logs; installer success and road validation are separate steps.
2. Keep fresh city/queue and highway/curve drives, ordinary night/wet conditions when encountered, lead-free
   periods and bookmarked unwanted braking, sticky/adjacent leads, far pickup, loss and recovery.
3. Assign discovery/confirmation roles before reviewing error results. Freeze proposed behavior/gates before
   confirmation; previously tuned routes count as tuning data. Keep consumers unchanged for comparisons.
4. Developers replay current baseline/candidate on identical routes, score per-event response/braking/switches,
   coverage and regressions, then confirm on the actual fork as required. Follow [09](09_tools_and_data.md#developing-and-testing-a-change).

Physical calibration, consumer replay and closed-loop road behavior are three deliverables. A field or profile
qualifies through per-event response, coverage and regressions on held-out routes.

## Which tests answer which open question

| Question | Captures |
|---|---|
| native speed, ego source, Doppler | T02 + T04, including far support |
| physical uncertainty / reported layer | T03/T04/T07 + T05 |
| longitudinal acceleration/filter/relative basis | T04 |
| distance zero, far geometry and identity | T03 + T04/T06 |
| validity, lifecycle and trustworthy motion | T06 + T04/T07 |
| status/blockage/internal diagnostics | T01/T02 |
| lateral frame, heading and delays | T03/T07 |
| additional targets, selectors and camera dependence | T04/T07/T08/T09 |
| class, probability and measured size | T10 + T03/T06 |
| lane/curve/camera/duty/event context | T11/T12 + T06 |

## Decode a pilot and share the result

On an analysis machine, [09](09_tools_and_data.md) describes log dependencies and decoding. For a pilot:

```sh
python tools/decode_log.py INPUT_LOG --profile all-tracks -o pilot_points.csv
```

Replace `INPUT_LOG` with your saved log or CAN CSV. This point CSV serves quick inspection; the complete raw
field/uncertainty surface comes from the original CAN. Keep original CAN, adjacent segments, references and video; lifecycle/record analysis
reconstructs continuous streams across segment edges.

Submit a [drive report](https://github.com/ds-sebastian/ars510-radar/issues/new?template=drive_report.yml) for road
behavior or a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new?template=research_finding.yml)
for a controlled test. Include test ID, car/firmware/configuration, conditions, times relative to the session,
intended contrast, reference accuracy, observed results including runs labelled unexercised, and whether private logs are available.

Keep route/dongle IDs, VINs, GPS, unit identifiers and identifying video out of public posts. Arrange private
transfer with the maintainer; retain original instrument exports and quality flags. Anonymous summaries and
reproduction commands belong in the repo when the result is ready.

Before promoting a conclusion, verify that the intended condition occurred, physical identity/reference timing
is adequate, gaps and dropped outputs stay visible, and conclusion-bearing numbers were checked a second way.
Report each result as supported, contradicted, inconclusive or unexercised.
