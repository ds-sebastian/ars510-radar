# 17. Upstream proposal

The upstream opendbc proposal, its evidence and what upstream review is likely to ask. **`acc` is open upstream as
[commaai/opendbc#3860](https://github.com/commaai/opendbc/pull/3860)** (ready for review); follow it there for review
comments and merge status. It is prepared as the
[`ars510-acc`](https://github.com/commaai/opendbc/compare/master...ds-sebastian:opendbc:ars510-acc) branch on a fork of
opendbc, on top of opendbc master: the ACC target inline in the Toyota `radar_interface.py`, the DBC
`toyota_tss2_ars510.dbc`, the radar DBC for the radar-ACC platforms (RAV4 2022-25, C-HR, Yaris) in `values.py`, and
`stockFcw` from the radar's PCS alarm in `carstate.py`.

`upstream/opendbc_ars510.patch` is that branch as one patch, and `upstream/toyota_tss2_ars510.dbc` is its
DBC. It also has Toyota's carstate set `stockFcw` from the radar's PCS alarm on
the radar bus ([15](15_aeb_pcs.md#where-a-relay-stands-for-developers)). [`upstream/ars510_acc_target.py`](../upstream/ars510_acc_target.py) is the same logic as a standalone file, which the
installer's `acc` profile runs on forks. CI tests the
standalone files and checks the patch against the DBC and the standalone logic.

## Towards an upstream (comma) interface

The integration installs on openpilot, sunnypilot, StarPilot and CarrotPilot as an appended hook. The proposal for
upstream is the ACC target alone (`acc`), written the way opendbc writes radar interfaces. There is no all-tracks
proposal: an object-list interface would pass the list's speed excursions to the planner
([07](07_velocity_excursions.md); the all-tracks file that was tried is recorded [below](#parts-of-the-openpilot-file)).

| | `acc`: the ACC target alone (proposal) |
|---|---|
| files | [`upstream/ars510_acc_target.py`](../upstream/ars510_acc_target.py) + [`toyota_tss2_ars510.dbc`](../upstream/toyota_tss2_ars510.dbc), as [`opendbc_ars510.patch`](../upstream/opendbc_ars510.patch) |
| size | 45 code lines (68 in the file); reads 7 DBC signals of three messages plus their rolling counters |
| constants / state attributes / conditions / functions | 3 / 5 / 9 / 3 |
| radar available when | the car model: every radar-ACC platform (RAV4 2022 and 2023-25, C-HR, Yaris) |
| evidence | [below](#the-acc-target-alone--candidate) |

Sizes: [`acc_target_parser.json`](../data/analysis/summaries/acc_target_parser.json) (`file_size`).

The `acc` proposal, [`upstream/opendbc_ars510.patch`](../upstream/opendbc_ars510.patch), applies to opendbc master as one
commit:
- **DBC:** `opendbc/dbc/toyota_tss2_ars510.dbc` with the ACC target frames `ACC_TARGET_1`-`4` (0x235 / 0x237 / 0x239 /
  0x23B), every field documented, and the radar's other support frames for completeness: the cycle header (0x190), the
  target summaries (0x191-0x194), the event pair (0x195 / 0x196, with the fault bit), the object stream (0x680), the PCS
  alarm flag (0x100), the alive frame (0x202) and the boot bit (0x24F), confirmed and likely fields only, with approximate
  units marked. `TARGET_ID` is 6 bits (a C-HR radar numbers its tracks up to 37). Values that need more than one frame (the
  0x80 / 0x85 ISO-TP records) or a computation (a summary's speed, `LAT_DIST`'s 13th bit) are explained in comments, not
  given as signals. The interface reads seven signals; through CANParser every signal equals the reference decoder on 9,574
  frame sets, and the newer ones decode as documented on opendbc's 61 radar-ACC test-route segments.
- **`values.py`:** the radar-ACC platforms (RAV4 2022 and 2023-25, C-HR, Yaris) get `toyota_tss2_ars510` as their radar
  DBC instead of none, two lines in the TSS2 and SecOC platform configs. So the car model selects the parser.
- **`radar_interface.py`:** for radar-ACC cars the Toyota `RadarInterface` publishes the ACC target as one point, once
  per radar cycle: after the stock trigger check (0x237 updated), the radar's cycle clock (0x239 `TIMESTAMP`) must have
  advanced. The frames repeat at 50 Hz, and radard accepts `liveTracks` only at 8-24 Hz. The clock advances once per
  60 ms cycle, with or without a target, so reports go out at 16.6 Hz: empty when there is no target, nothing when the
  radar stops sending. There is no point while the frames are invalid (a stale or bad counter).
- **Lateral wrap: in the file, not in the patch.** `LAT_DIST` holds the low 12 bits of the radar's 13-bit lateral distance,
  so a target more than 20.95 m to the left reads 40.96 m too far right, and the frame's check byte then carries the hidden
  bit's term 0x14 ([05](05_acc_target_and_support.md#check-bytes)). `upstream/ars510_acc_target.py` reads the raw 0x237 frame and
  adds the 40.96 m back (12 of its 45 code lines). In opendbc that check belongs to a checksum type for this DBC, which
  CANParser selects by DBC name, rather than to the radar interface, so the patch leaves it out. The wrapped targets sit
  21-53 m to the side in turns and at junctions (14 of 320 wrapped cycles were published within 2 m of the path, at
  77-81 m). radard never took one as its lead in the recorded drives, and in the fast-suite replay the unwrap changes
  no planner tick ([`acc_lat_dist_wrap.json`](../data/analysis/summaries/acc_lat_dist_wrap.json)).
- **Tests:** none of its own, like opendbc's other radar parser merges. opendbc's generic tests cover it:
  `test_car_interfaces.py` runs every platform's `RadarInterface`, and `test_models.py` replays each platform's test route
  through it and carstate, now including the RAV4 2022, C-HR and Yaris routes. The one-report-per-radar-cycle rate
  (radard's frequency check is off in replay) and the PCS alarm are checked in this repo (`openpilot/check_integration.py`,
  `tests/test_pcs_alarm.py`).

smasher816 helped frame this approach (the ACC target inline in Toyota's `RadarInterface`, selected through the radar
DBC) and reviewed it; the DBC field names follow his.

The C-HR and Yaris radars send the same frames ([01](01_radar_bus.md#c-hr-and-yaris)), so the proposal includes them;
drives in traffic on those cars are still being collected before a pull request upstream.

With the patch, opendbc's Toyota, platform-config, DBC-parser and car-interface tests pass and its ruff rules hold.
Through opendbc's own CANParser the DBC decodes the bundled frames exactly like the reference decoder
(`tests/test_acc_target_parser.py` checks the same in CI with a minimal parser). `install.py --profile acc` installs the
standalone form (`upstream/ars510_acc_target.py`) and the DBC on a fork. Why the ACC target replaces the object list as the lead source: [the ACC target alone](#the-acc-target-alone--candidate).

What upstream review is likely to ask, from recent openpilot / opendbc radar PRs:

1. **Small, separable PRs.** The proposal is decode and one point, tested on recorded frames.
2. **Fleet evidence.** Replays come from two RAV4s on one firmware (`8821F0R03100`): the owner's, and a second
   car held out of all tuning ([11](11_profiles_compared.md#drives-held-out-from-every-choice)). Its radar unit has the same speed noise
   ([06](06_accuracy.md#velocity)). Drives on other cars and firmware are what upstream would weigh.
3. **Process replay coverage.** A route segment with the radar in openpilot's process-replay tests.
4. **Alpha longitudinal compatibility.** Covered for `8821F0R03100`: after openpilot's UDS radar-disable request the
   radar's car-bus messages stop while bus 1 keeps sending on an unfiltered radar line
   ([01](01_radar_bus.md#openpilots-radar-disable)).

### Parts of the openpilot file

The all-tracks file that was tried as an upstream candidate, `fused` in one opendbc-style file (187 code lines), is no
longer shipped: on held-out drives its speed filter still passes list-speed excursions to the planner (a −3.31 m/s²
request at 30 m/s for a list track at 54 m whose closing speed read 23.7 m/s at constant range, and 1.37 s/h more
unnecessary braking than `acc` pooled over every held-out set;
[`second_car_batch3.json`](../data/analysis/summaries/second_car_batch3.json)). The same filter stays in the `ars510`
package as `FUSED_CONFIG` for research ([12](12_kalman_filter.md)). The record of what each of its parts bought on the
27 replay drives (code lines counted as statements only; the `acc` file has 45 counted the same way):

| part | code lines | since | cost of removal | status in the file |
|---|---|---|---|---|
| transport, CRC, slot decode, track IDs, ego speed, RadarInterface wrapper | 103 | 1.0 | the car runs on vision only | required |
| ACC target decode and association | 27 | 2.0 (range scale 0.4 x since 2.3) | +24 unjustified hard ticks on 27 drives; with the 0.25 x scale, one road late brake -1.47 -> -2.36 m/s2 | keep |
| Kalman speed filter (one state, uncertainty-weighted) | 22 | 2.0 | hard radar-only ticks 48 with the filter alone against 93 for raw (20 held-out routes) | keep |
| young-track factor | 3 | 2.0 | further-drive hard ticks 2 -> 11; second car with the far rule (with the std gate): a -2.9 m/s2 brake on a young track | keep |
| speed-std publication gate | 2 | 2.0 | further-drive hard ticks 2 -> 8; second car: see the young-track factor | keep |
| age-60 publication gate | 2 | 1.0 | radar-only braking x3 (age 6); age 40: further-drive hard ticks 1 -> 9; age 80: more missed braking vs the oracle (3.3 -> 3.7 s on 2.3) | keep |
| range fusion (incl. ACC distance as the followed car's range) | 9 | 2.0 (ACC distance 2.1) | braking neutral; lead flips +39 %, target episodes 4 -> 6; second car with the far rule: braking neutral, flips +11 % | keep for lead stability; droppable at that cost |
| ego-speed alignment (0xB4 / 0.9865 = carState vEgo; DBC factor 0.15) | 0 | 2.6.1 | braking neutral (onset +12 ms); one constant where 0xB4 is read, so it costs 0 lines | keep (0 lines) |
| state pruning | 7 | 2.0 | state grows with every track id seen | required |
| path gate (yaw rate) | 6 | 2.3 (2.2 from 60 m) | back to 2.1 (removed with the 0.4 x match): held-out target episodes 3 -> 4, owner 0 -> 1, further hard ticks 1 -> 2; two road false brakes; second car with the far rule: braking neutral, flips +7 % | candidate: keep, or move into radard as a lateral gate |
| far cars: only the ACC target's track beyond 60 m | 2 | 2.6 | 2.5 over all four drive sets (16.9 moving h): oracle unnecessary braking 21.6 -> 28.5 s, lead flips 334 -> 418 /h, second car 0 -> 1 hard; with it a fast far closing waits ~1 s for the radar to make the car its ACC target | keep |
| stationary tracks path-gated close in too | 2 | 2.6 | all four drive sets: hard radar-only episodes 12 -> 8 (ticks 30 -> 16), mild 49 -> 26 with it; missed braking the same (parked cars at the curb while turning, a parked car alongside) | keep |
| fork compatibility (CP_SP argument, points assigned as a list) | 2 | 2.2 | crashes on sunnypilot | keep (harmless upstream) |

Numbers: [`openpilot_file_parts.json`](../data/analysis/summaries/openpilot_file_parts.json), with the evidence file for
each part. A future object-list proposal would start from this ledger, once excursions no longer reach the planner.

### The ACC target alone (◐ candidate)

[`upstream/ars510_acc_target.py`](../upstream/ars510_acc_target.py) publishes only the radar's ACC target
(0x235 / 0x237: distance, lateral position, closing speed, target id) as openpilot's one radar point, the way Toyota's
own ACC uses the radar ([05](05_acc_target_and_support.md)). It is a CANParser on three messages, the target-present flags and
one point: 45 code lines (68 in the file) reading 7 DBC signals, against 187 lines, 3 constants against 28, 9 conditions against 85.
The replay numbers below come from a hand-decoded version that decodes the same values (all 11,028 bundled reports
identical) and reported every fifth card update. Reporting once per radar cycle instead gives the same results on every
measure (hard 13 against 13, mild 32 against 30, unnecessary 19.3 against 19.2 s, missed 17.4 against 17.4 s; every
route-bootstrap interval includes zero; `per_cycle_reporting` in the summary). When the frames stop, this file
publishes nothing, as Toyota's other radars do. The ACC target is the output
of the radar's own internal tracker: one converged, in-path target with a fine distance and a filtered speed. The object
list is a separate, partial export that carries no range information into it
([05](05_acc_target_and_support.md#the-radars-acc-target-0x235--0x237)). Each part of the all-tracks file above
approximated a piece of that tracker's work from the object list:
- the Kalman filter and the young-track factor approximate the tracker's own speed filtering;
- the age and speed-std gates approximate "converged";
- the path gates approximate "in path";
- the far rule is the decision itself at range.

Tried and set aside: one gate-free Kalman model over every object (`shared_speed`, `shared_range`; over speed with a traffic
prior, or over range and range rate with the measured 3 % range noise) brakes hard while moving 59 and 168 times against
`fused`'s 8. Both object-list kinematic signals, speed and range, carry slow,
correlated errors that inverse-variance weighting leaves in place; the ACC target's speed follows the slope of its own
range (below), so the radar's decision carries consistent speed and range.

![the ACC target alone against 2.6](img/analysis/guide_acc_target_parser.png)

Replayed over every drive set (16.9 moving h, 62 routes, unchanged radard and planner):
- **Braking.** It asks for something different from 2.6 (> 0.3 m/s²) on 0.21 % of moving time. Every route-bootstrap
  difference to 2.6 includes zero: hard, mild, oracle unnecessary and missed braking.
- **Lead stability and onset.** Lead flips are lower (302 against 332 per hour). Braking starts 0.017 s before vision
  only on real closings (2.6: 0.010 s). The radar supplies the lead more often (88 % against 86 % of lead time),
  because the ACC target is published from the cycle it appears.
- **While moving,** it has 5 hard and 22 mild radar-only episodes against 8 and 27. Its other 8 count as hard because
  the car is stopped 0.7-4.8 m behind an object the camera leaves out of its lead list: radard's low-speed rule holds
  the car there, while vision only would ask to move off.
- **One far case:** a real object braking and drifting a lane over at 82 m, still flagged in-path by the radar. radard
  matches it to the camera's lead 27 m further on; this is the 7 hard ticks `acc` has while moving on the 4 further drives,
  where `fused` 2.6 asks −0.85 m/s² ([`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json),
  [`acc_weight.json`](../data/analysis/summaries/acc_weight.json)).
- **On Toyota's stock-ACC drives** its requests track Toyota's command as closely as 2.6's: on U1 RMS 0.249 m/s² for
  both (jerk p99 0.167 against 0.176 m/s³); on the second car's stock drive (140 s) the two differ by 0.007 m/s² RMS,
  with correlation to Toyota 0.76 for both against 0.68 for vision only. The remaining gap to Toyota is common to both files.
- **Filter-free:** the ACC target's speed follows the slope of its own distance (best lag −0.06 s, gain 1.00), and its
  fast noise (0.027 m/s on the second car, 0.025 on the owner's;
  [`second_unit_noise.json`](../data/analysis/summaries/second_unit_noise.json)) is a fifth of its 0.125 m/s code step, so a filter would add delay.
- **On drives held out from development and tuning** (44 routes of both cars, 6.46 moving h) it brakes unnecessarily no more
  than 2.6: 14.0 against 18.6 oracle seconds (−0.72 s per moving hour, route bootstrap −1.65…+0.15). Hard and mild
  radar-only braking are equal, and braking starts at least as early on real closings (vs vision).
- **Close cut-ins** (the lead jumps at least 5 m closer to within 35 m; 450 in all drives): the radar's ACC target moves
  to the cut-in car after a median 0.2 s (0.3 s for a faster car). On the 120 where that car is faster than ego, `acc` and 2.6 differ by at most 0.3 m/s² (braking below −0.5 m/s² in 28 against 27, below −1 in 14 against 14; vision only 29 / 14).
- **Over every drive** (94 routes, 21.45 moving h; it carries protocol values only, while 2.6 was tuned on most of them) it has
  fewer lead flips (−22 per moving hour, −36…−7). While moving it has 5 hard and 31 mild radar-only episodes against 8 and 36,
  28.4 against 35.0 s of unnecessary and 22.9 against 20.3 s of missed braking; the route-bootstrap intervals of those four
  differences include zero.
- **On 26 owner routes held out from every replay** (2.56 moving h):
  - unnecessary braking 7.7 against 2.6's 11.4 s, and lead flips 323 against 345 per hour (both route-bootstrap CIs
    exclude zero);
  - braking starts 0.053 s before vision only (2.6: 0.026 s);
  - hard, mild and missed braking tie within their intervals. Its one hard episode is a hold at 0.3 m/s, 1.3 m from an
    object, where the oracle asks for −2.65 m/s² too.

Each part earns its line, by what breaks when it is removed (replays of every drive set):
- **Target id as track id.** The id restarts radard's per-track filter at a target change; with a constant id the filter carries the old target's speed into the new
  one: unnecessary braking 19.2 → 37.2 s, hard episodes 13 → 16.
- **Lateral position.** At 0, radard's low-speed rule (points within 1 m of the path) takes targets that sit off the
  path: hard braking while moving 5 → 7, mild 22 → 27.
- **The radar's target-present flags.** They remove the point of an idle target; with the flags dropped it becomes a point at 0 m, which radard keeps
  switching to: lead flips 302 → 342 per hour, mild 30 → 32.
- **One report per radar cycle.** The frames repeat at 50 Hz; on the car radard accepts radarTracks at 8-24 Hz, so a report
  goes out when the radar's cycle clock (0x239) advances, every 60 ms (16.6 Hz). Replay runs radard in simulation mode,
  where the rate check is off, and gives the same results at 20 Hz and per cycle.

The hard, mild and onset numbers are independent of the oracle, whose reference lead takes its range mostly from the ACC
target and leans toward this file on unnecessary and missed seconds. Numbers:
[`acc_target_parser.json`](../data/analysis/summaries/acc_target_parser.json).

### Against vision only (what the PR adds over today)

On these cars openpilot runs vision only today. Replayed on the same 62 routes (16.9 moving h, two cars) through the
unchanged radard and planner, `acc` and `acc_summaries` cut vision only's unnecessary braking from 89.2 to 19.2 / 19.1
oracle seconds and its missed braking from 30.8 to 17.4 s:

![acc and acc_summaries against vision only](img/analysis/upstream_vs_vision.png)

The oracle builds its hindsight lead from the ACC target 96 % of the time, so it favours the radar. Three checks:

![the same comparison against three references, by drive set, and judged by the driver](img/analysis/upstream_vs_vision_checks.png)

- **Against other references** (73 routes, 18.8 moving h, route-bootstrap 95 % intervals). On the moments where the
  oracle and a camera-only hindsight lead agree within 0.5 m/s² (8.3 confident h), vision only brakes unnecessarily
  3.22 s per moving hour and `acc` 0.67: −2.55 s/h [−4.40, −1.09]. Without the 28 drives whose driving model saturates
  the camera lead's uncertainty: −2.21 s/h [−4.54, −0.48]. Against the camera-only lead alone the two tie
  (−0.07 s/h [−2.02, +2.01]); that reference shares vision only's camera, and on video the oracle was right in 6 of the
  10 episodes where the two disagree, the camera reference in 2.
- **By drive set.** The gain is largest on the 27 replay drives and the second car's drives (unnecessary + missed
  braking 8.5 → 1.4 and 10.8 → 2.3 s per moving hour). On the owner's road set (sunnypilot drives plus two second-car drives) the three tie
  (2.9 / 2.8 / 2.8 s per moving hour).
- **Judged by the driver** (the 20 held-out routes of the 27 replay drives: 4.56 h, 167 brake presses, no hindsight lead): `acc` was already asking
  ≤ −1 m/s² before 44.9 % of the driver's brake presses (vision only 40.1 %), starts braking 0.04 s earlier on average
  (95 % CI −0.09 … +0.00), asks for no braking that only the radar wanted, and in 38 driver overrides its request was
  closer to what the driver did 7 times and further 0 times ([11](11_profiles_compared.md#against-vision-only)).
  `acc_summaries` gives the same numbers.

One road moment, from an owner `acc` drive: the lead moves out and reveals a near-stopped car 56 m ahead. The ACC
target reads the slow car's speed in the cycle it switches to it; the camera lead takes another 0.45 s to fall below
5 m/s. Replayed from 7.5 s before the driver's brake press with the driver's inputs removed, `acc` asks for −1 m/s²
0.45 s sooner than vision only, peaks at −3.3 m/s² and stops 3.8 m short; vision only peaks at −3.5 m/s² and reaches the
slow car. This is one event in an open-loop camera replay (gaps good to about 1-2 m), a direction rather than a number.

![a revealed slow car: logged leads and the replayed planner](img/analysis/upstream_revealed_queue.png)

**Seeing it on a route.** Every radar-ACC car already logs these frames on bus 1, stock openpilot included; opendbc's
test routes for the RAV4 2022 (hybrid), C-HR and Yaris carry them. In Cabana, load `toyota_tss2_ars510.dbc` and plot
`ACC_TARGET_2.LONG_DIST` (0x237) against the camera's lead distance, and `ACC_TARGET_1.REL_SPEED` (0x235) for the
closing speed; `ACC_TARGET_2.PRESENT` marks when the radar follows a car, and `ACC_TARGET_1.TARGET_ID` changes at a new
target. The PR description names a public validation route driven with this interface.

Numbers: [`upstream_case.json`](../data/analysis/summaries/upstream_case.json),
[`acc_target_parser.json`](../data/analysis/summaries/acc_target_parser.json),
[`acc_summaries_40m.json`](../data/analysis/summaries/acc_summaries_40m.json),
[`profiles_vs_vision.json`](../data/analysis/summaries/profiles_vs_vision.json); event data
[`revealed_queue_case.csv.gz`](../data/analysis/revealed_queue_case.csv.gz). Figures: `tools/make_upstream_figures.py`.

## What radard gets from other radars

What other radars in openpilot send (signals in their DBCs), the ARS510 counterpart, and the data that would close each gap
([`opendbc/car/*/radar_interface.py`](https://github.com/commaai/opendbc/tree/master/opendbc/car)):

| what other radars send | examples | ARS510 today | what would close the gap |
|---|---|---|---|
| per-track **measured vs predicted** state (`RadarPoint.measured`) | Toyota `VALID` + `SCORE`, Rivian `STATE`, Tesla `Meas` | `107\|1` = predicted (◐) and `16\|8` = existence probability (◐); the fork build publishes `measured = the inverse of the predicted flag` for forks that carry the field; upstream openpilot has deprecated it | in place in the fork build; excursions arrive on measured records, so this is hygiene |
| **new-track** flag | Toyota `NEW_TRACK`, Rivian new states | derived from the age field (●) | in place |
| the radar's own **relative** speed | `REL_SPEED` on Toyota, Honda, Hyundai, Chrysler | over-ground speed (`64\|10`) minus 0xB4 ego speed | the ACC target carries a relative speed for the followed car |
| relative **acceleration** | Hyundai `REL_ACCEL`, Tesla `LongAccel` | `84\|10` over-ground acceleration (◐, lags about 0.5 s); the ACC target's relative acceleration (●) | calibrate `84\|10` against independent motion |
| **lateral speed** | Tesla `LatSpeed` | `74\|10` (◐, 0.147-0.155 m/s per code against the gyro, `decode_references.json`) | already published as `yvRel` where forks carry it |
| radar **fault / blockage** status | Honda `RADAR_STATE`, Tesla `sensorBlocked` | the interface reports `radarUnavailableTemporary` once the last record is older than 0.5 s; the radar's own fault flag 0x196 byte 1 bit 0 (◐, sets 0.3-0.4 s after the object list stops; require ≥ 2 cycles; [05](05_acc_target_and_support.md)); further candidates (○): Toyota's car-bus 0x411 `PCS_HUD` alerts (by Toyota's DBC `PCS_DUST2` sensor blocked and `PCS_INDICATOR` = 2 fault; on this radar the recorded fault code is byte 0 = 0x48, about 2 s after an object-list outage, also with a camera-side state, and never sent while openpilot disables the radar; no blockage bit has been seen), and a long idle run of 0x680 while driving (longest 1.0 s in 7.8 h of normal driving). 0x101 / 0x197 are boot flags: they did not react to any list fault | parked baseline/covered/recovery diagnostic and passive captures ([T01](16_routes_and_tests.md#t01-parked-startup-and-status)); naturally occurring warnings from ordinary drives, kept in the logs |
| measurement **uncertainty** | (rarely exposed) | `224/232/240/248\|7` family, scaled against the radar's ACC target | physical units would let radard weight radar against vision |
| plain **DBC** decode through `CANParser` | every upstream interface | a 742-byte record split over 106 frames | a reassembler of about 80 lines (`ars510/transport.py`) and a CRC check |

The closest relative in openpilot is the Tesla Model 3's Continental radar (`tesla_radar_continental`, 66 code lines at the opendbc used for the replays):
- the radar sends distance, relative speed and acceleration, lateral position and speed, `Tracked`, `Meas`, existence
  and obstacle probabilities, class, size and uncertainty sigmas; the interface publishes `dRel` / `yRel` / `vRel` of
  tracked points plus the radar status as errors;
- the ARS510 slot follows the same Continental pattern, which is how its existence, predicted-record and uncertainty
  fields were identified ([03](03_slot_fields.md#uncertainty-and-quality));
- the two pieces a Tesla-sized interface would add: a **fault / blockage status**, and handling of the far-range speed
  error, which `fused` does by weighting each reading by `240|7` and the radar's ACC target
  ([12](12_kalman_filter.md#the-model)) and `acc` by publishing the ACC target alone.

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
| **ARS510 `acc_summaries`** ([`openpilot/standalone/ars510_acc_summaries.py`](../openpilot/standalone/ars510_acc_summaries.py)) | 99 | the ACC target plus up to two other moving cars from the radar's summaries within 40 m, speed from a Kalman filter on their range |
| ARS510 all-tracks file (`fused`, not shipped) | 187 | the object list through one Kalman speed filter per track; part by part [above](#parts-of-the-openpilot-file) |

- The other interfaces, except Ford's, pass the radar's tracks through with validity and lifecycle checks and leave
  speed filtering to radard. `acc` is the same shape: a pass-through of the radar's own target.
- The ARS510's `240|7` code follows the width of its far-range speed error as a continuous per-reading scale (◐), so `fused`
  weighted each reading in one scalar filter ([12](12_kalman_filter.md#the-model)); that was not enough to keep the
  excursions out of the planner on held-out drives ([11](11_profiles_compared.md)).
- Moving that weighting into radard (a per-point speed variance) would make an object-list interface a pass-through
  like the others; replay with that design braked hard about twice as often as `fused`
  ([10, item 5](10_research_directions.md#for-a-better-ride)).
