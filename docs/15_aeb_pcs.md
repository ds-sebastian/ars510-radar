# 15. AEB and PCS

The radar is also Toyota's pre-collision (PCS / AEB) ECU. This page collects what is known about its PCS decision, why
openpilot's radar disable takes AEB with it, how a relay of the radar's own decision would work, the open questions, and
how to record PCS events. The car-bus messages themselves, the CAN filter against the radar disable and what panda
allows are in [13](13_car_bus_messages.md).

## AEB on an unfiltered radar line

**Today:** stock AEB runs with stock ACC (openpilot lateral only, radar line unfiltered) and with openpilot longitudinal through a
radar CAN filter. With openpilot longitudinal on an unfiltered radar line, the radar is disabled and the car's PCS brake request is off; the dash
shows "Pre-Collision System Malfunction" and the PCS OFF lamp.

**Why the disable takes AEB with it.** AEB is a live request: the radar sends non-idle 0x283 / 0x344 frames at the
moment it decides to brake, and the brake system acts on them. UDS communication control (`28 01 01`) stops all of the
radar's normal car-bus messages at once, 0x283 / 0x344 included: after the request on U2 (12.50 s) the 26 min log holds 0 frames of
0x283 and 0 of 0x344 ([`radar_car_bus_messages.json`](../data/analysis/summaries/radar_car_bus_messages.json)).

**How other openpilot cars keep AEB (◐, opendbc source).** openpilot longitudinal replaces only the ACC command, and panda
forwards every other message from the camera side of the harness, so a stock AEB request in a message of its own keeps reaching
the brakes: Ford `ACCDATA_2` (panda also keeps `CmbbDeny_B_Actl` at 0), Rivian `ACM_AebRequest`, VW MQB `ACC_10` and MEB
`AWV_03`, the `FCA11` / `FCA12` of Hyundai CAN cars whose camera runs SCC, and 0x283 / 0x344 / 0x411 on Toyota TSS2 cars whose
camera sends `ACC_CONTROL`. Where openpilot switches off the ECU that runs ACC (Hyundai radar-SCC and CAN FD ADAS-ECU cars,
Toyota radar-ACC), that ECU's AEB goes with it; opendbc's `disable_ecu` says so in its docstring. On the radar-ACC RAV4 the
radar's car-bus messages reach the car on a path that bypasses the panda
([13](13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)), so panda cannot take over 0x343 alone: a CAN filter in
the radar's line does that in hardware and keeps the radar's AEB, and a relay of the radar's bus-1 decision would be the
software route ([below](#relaying-the-radars-decision--theoretical)). The route other cars use to keep stock ACC (with its
AEB) under openpilot speed control, stepping the stock set speed with emulated cruise buttons, is closed here: no raw cruise-lever
bit was found on buses 0-2 around 385 set-speed steps, 46 engagements and 67 main toggles, only its effects ([13](13_car_bus_messages.md#0x365-lead-distance-and-relative-speed-)).

## What the PCS frames can request

Panda passes 0x344 and 0x366 with any content and checks only 0x343 (`ACCEL_CMD` range) and 0x283 (bytes 0-5 zero). The brake
system reads 0x344: without it, 0x320 bit 13 sets ([13](13_car_bus_messages.md)). By their Toyota names both frames can
actuate, so AEB or relay work treats them as commands, not status
([`carbus_feedback.json`](../data/analysis/summaries/carbus_feedback.json)):

| frame | fields that request braking (Toyota names) | recorded: idle → U3 alarm | panda |
|---|---|---|---|
| 0x344 `ACC1F01` (20 Hz) | `DSS1GDRV` deceleration (0.1 m/s²), `PREFILL` / `PBPREPMP` pre-fill, `PBATRGR` / `PBRTRGR` / `IBTRGR` brake-assist triggers, `PCSABK` autobrake, `BRKHLD` hold | all 0 → 0; `PCSALM` 0 → 1, `PCSOPR` 1 throughout; fleet: `PBATRGR` in 4 events (below) | any content |
| 0x283 `DS11F01` (33 Hz) | `FORCE` (2 N), `STATE` (3 = braking), `BRAKE_STATUS`, `PCSABK2`, `PBRTRGR2` | 0 → 0; `PCSNOCHG` 0 → 1; `STATE` 4 for 0.3-2.5 s in Park ([13](13_car_bus_messages.md)) | bytes 0-5 zero |
| 0x366 `DS11D71` (5 Hz) | the reference DBC's alarm / autobrake / pre-brake request bits; on this radar those positions carry its target fields, and the PCS alarm is bit 13 | alarm bit 0 → 1 | any content |

In our 297,076 0x344 frames and in comma's public fleet logs of radar-ACC cars (7,865 one-minute segments, 108 moving hours
with the radar on, [`fleet_pcs.json`](../data/analysis/summaries/fleet_pcs.json)) the only non-zero fields are `PCSOPR`,
`PCSALM` (the alarms) and `PBATRGR`, the pre-collision brake-assist trigger (◐). `PBATRGR` came in 4 segments on 4 cars:
twice inside an alarm once the driver braked, once 0.36 s before an alarm with no pedal pressed, and once on its own for
1.9 s while the driver was braking hard behind a closing lead, with no alarm. No deceleration, pre-fill, autobrake or hold
field and no 0x283 force was set in any of these frames, so whether a non-idle 0x344 alone brakes the car is untested.

## A recorded stock PCS alarm (U3)

![U3: stock PCS alarm against the radar's bus-1 0x100](img/analysis/pcs_activation_u3.png)

U3 is a deliberate test on the second car (stock ACC, radar enabled, radar line unfiltered), approached at 7 m/s: an inflatable
decoration stood in the lane, with a pickup parked a few metres behind it. **The radar tracked the pickup.** Its only
object and its ACC target (one ID throughout) read 8 m at the stop, while the inflatable was at the bumper; the
object list held the pickup alone. The radar's **PCS alarm stage** ran from 56.151 to 56.922 s. The driver, off the gas
0.64 s before the alarm, was already braking: master-cylinder pressure rose from 0.04 s after the alarm start, the stop switch
closed at 0.11 s, and ABS was active from 0.62 to 1.26 s after it (peak 2.38 MPa); the car stopped with the inflatable at the
bumper. The radar's braking stages (0x283 `FORCE` / `STATE`, 0x344 `DSS1GDRV`, pre-fill) stayed at 0, and the brake system
reported no system braking or brake assist (0x320 `BRKON`, 0x226 `FBA`)
([`pcs_activation_u3.json`](../data/analysis/summaries/pcs_activation_u3.json), [`carbus_feedback.json`](../data/analysis/summaries/carbus_feedback.json)).

**The alarm was most likely for the pickup (◐).** At the alarm the pickup was at 14.5 m, a time to collision of 2.1 s.
- **The in-path object is a vehicle.** The pickup was the only tracked object (object-list object 2, in path,
  stationary, first seen at 29.1 m) and the ACC target.
- **The camera's logged frames held constant.** On bus 1 the camera's frames (0x101 / 0x102, 0x180, 0x197, 0x210, 0x24D,
  0x500 / 0x501) stayed constant, and 0x240-0x248 only stepped their phase counter with default daytime bodies. On the
  car side only steering messages moved: 0x191, 0x2E4 and 0x371 `LTA_RELATED`.
- **The target of the alarm** is a research question ([open questions](#open-questions),
  [recording](#recording-pcs--aeb-events)): the camera also reaches the radar over a link outside the logged buses
  ([03](03_slot_fields.md#camera-association)), and the object list shows the radar's filtered tracks, so a camera trigger on
  the inflatable and a weak radar detection of it are the two candidates.
- The 0x100 flag marks the alarm in every reading.

**Size range of radar objects.** The radar tracks pedestrians at 0.5 × 0.4 m, and its ACC target has followed stationary
objects as narrow as 23 cm while driving ([05](05_acc_target_and_support.md#class-width-and-timestamp-0x239--0x23b)). The
inflatable's empty object-list position is consistent with a weak reflection at 77 GHz (○).

| t (s) | radar bus (bus 1) | car bus (bus 0) |
|---|---|---|
| 55.09 | event pair 0x195 / 0x196 leaves idle | |
| 55.6 | ACC target appears: the parked pickup, 18.9 m, closing at 7.0 m/s | |
| **56.1506** | **0x100 byte 0 → 0x02** | **same CAN tick:** 0x283 → `… 02 8E`, 0x411 → FCW; 0x344 → `PCSALM` at its next slot (56.180) |
| 56.27 | | driver brake |
| 56.913-56.922 | 0x100 → 0 | 0x411, 0x283, 0x344 back to idle |
| 57.18 | event pair back to idle | |

**0x100 byte 0 = 0x02 is the radar's PCS alarm flag on bus 1 (●, 8 alarms on 7 cars).** It starts and ends with the car-bus
alarm, and in every stored log (1,597 rlogs, 936,440 0x100 frames, three cars) it occurs in exactly these 9 frames. The
other non-zero 0x100 is the `FF FF` first frame after power-up. The event pair fires in many drives with the PCS
outputs idle: it is the radar's threat state, and 0x100 marks the decision to warn. Numbers:
[`pcs_activation_u3.json`](../data/analysis/summaries/pcs_activation_u3.json). comma's public fleet logs hold 7 more stock
alarms (6 cars, all radar firmware 8821F0R03100). In each, 0x100 = 0x02 starts in the same CAN tick as 0x283 `PCSNOCHG` and
0x411 FCW, with 0x344 `PCSALM` within 41 ms. The event pair led the alarm by 0.02-1.27 s in 6 of them; the seventh came
during hard stock-ACC braking with the pair idle. On firmware 8821F0R01100 no alarm was recorded in 34.8 moving hours (0 of 75
comparable threat moments, P = 0.03 at the 03100 rate) with the same PCS sensitivity settings: a candidate (○) firmware
difference in alarm sensitivity ([`fleet_pcs.json`](../data/analysis/summaries/fleet_pcs.json)).

**On the car bus the radar's 0x366 target report carries the same alarm in byte 1 bit 2 (●, 8 alarms).** It is set in 5 of
547,922 0x366 frames in every stored log, all inside this alarm (56.17-56.93 s), and the radar sends an extra frame when
it sets and when it clears; the report holds the alarm's target (id 6, the pickup) throughout ([13](13_car_bus_messages.md#0x366-target-report-the-acc-target-and-other-states-),
[`car_bus_0x366_fields.json`](../data/analysis/summaries/car_bus_0x366_fields.json)). In the fleet logs it sets 20 ms after
the 0x100 onset in all 7 alarms and stays clear in the brake-assist event without an alarm.

**0x33E byte 6 bit 7 marks PCS activity (◐).** It is set in this alarm (5 of 696,137 frames), next to the radar's own time to
collision of the target: 2.19 s just before the alarm and 2.08 s in the frame that announces it, so this alarm started at a
radar TTC of about 2.1 s ([13](13_car_bus_messages.md), [`decode_round3.json`](../data/analysis/summaries/decode_round3.json),
block `car_bus_0x33e`). In the fleet logs it is set in every alarm and also with the 0x344 brake-assist trigger, once
0.36 s before an alarm and once for 1.9 s with no alarm, so it is not alarm-only.

## Relaying the radar's decision (○ theoretical)

The disable silences the radar's car-bus side. On bus 1, which the comma reads, the radar keeps sending its object
list, ACC target and threat states at full rate ([01](01_radar_bus.md#openpilots-radar-disable)). Two drives with the disable
active, U2 and opendbc's C-HR Hybrid "radar disabled" route on another radar firmware, show the radar still working (◐,
[`relay_inputs.json`](../data/analysis/summaries/relay_inputs.json)):
- **It still receives the car's yaw rate and speed.** The ego path curvature it reports in 0x195 follows yaw rate / speed with
  r 0.97 (slope 1.04-1.05), and the objects it flags stationary read 0 m/s over ground.
- **Its short time-to-collision event pair (0x195 / 0x196, [05](05_acc_target_and_support.md#0x195--0x196-event-pair)) keeps
  firing**, at 250-330 active frames per moving hour, with required decelerations down to −2.8 m/s².

So its PCS logic keeps running with only its output to the car cut. Whether its alarm stage (0x100) still fires there is not
recorded: the one comparable moment, at a time to collision of 2.2 s, lasted 0.06 s. A relay would
reconnect that output through openpilot, so Toyota's own tuned decision logic still decides when to brake.

How it would work:

1. **Listen on bus 1.** Each cycle openpilot reads the radar's PCS state from bus 1: alarm, pre-fill, brake assist,
   autonomous braking, and the requested deceleration. The alarm stage is there: 0x100 byte 0 = 0x02 matches the
   car-bus alarm to the CAN tick (U3, above). Pre-fill and braking need an activation that reaches them; the event pair
   is a threat state.
2. **Translate to the car bus.** openpilot sends the 0x283 / 0x344 / 0x411 frames the radar would have sent for that
   state. The mapping is learned from a car with a radar CAN filter, where both buses are visible at once during a stock
   activation: each bus-1 state lines up with the car-bus frames the radar sent at the same moment.
3. **Keep the streams running.**
   - **0x344 as a continuous stream** (20 Hz, idle `00 00 01 00 00 00 00 50`). The brake system checks for it: 0x320 bit 13
     sets 0.15 s after it stops ([13](13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)).
   - **0x283 idle** (33 Hz), so an activation only changes the content of a running stream.
   - The stages carry the reference names: alarm (`PCSALM`, `PCSWAR`, FCW in 0x411), brake pre-fill (`PREFILL`),
     brake assist, autonomous braking (0x283 `FORCE` and `STATE` 3, `PRECOLLISION_ACTIVE`; 0x344 `DSS1GDRV`
     deceleration).
4. **Fail safe.** If bus 1 goes stale, a record's CRC mismatches, or openpilot stops, the relay drops to idle frames, and
   the dash shows PCS off (below). The relay adds one openpilot cycle of delay (10-30 ms) to the radar's own timing.
5. **A panda safety mode that allows it.** Upstream panda passes 0x283 with bytes 0-5 zero. A fork would allow
   the radar's brake request with limits: force, duration, only while moving, and only while bus 1 is healthy.

## The dash: PCS shows what is true

The malfunction warning follows the radar's 0x411 (`PCS_HUD`) (◐): with the radar disabled and parked, a second car showing upstream
openpilot's "PCS off" 0x411 (from 0.49 s after the radar's last one) showed only the PCS OFF lamp, while O5, with nothing replacing
0x411, showed "Pre-Collision System Malfunction" after about 7 s ([13](13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)). The rule for any implementation:

| situation | dash | 0x411 |
|---|---|---|
| relay healthy (radar records arriving, openpilot running, panda in its AEB mode) | PCS on | as the radar's idle frame, `PCS_OFF` 0 |
| any part unhealthy, or the relay unvalidated | PCS off | `PCS_OFF` 1, as upstream openpilot sends today |
| openpilot stopped | malfunction | the car's own check reports it |
| the radar flags itself blocked (0x196 fault flag on ≥ 2 consecutive cycles, or its own 0x411 carries a dust or fault state) | the radar's own alert | the radar's own 0x411 bytes, forwarded unchanged; openpilot already reports the radar temporarily unavailable ([08](08_openpilot_integration.md)) |

"PCS on" also carries the radar's real alerts. By Toyota's DBC, 0x411 has a blocked-sensor bit (`PCS_DUST2`) and a fault state
(`PCS_INDICATOR` 2). `PCS_DUST2` has not appeared on the owner cars, but comma's fleet logs hold it for whole minutes on four
cars, with the radar's 0x196 fault flag held throughout ([05](05_acc_target_and_support.md#0x195--0x196-event-pair)); the covered-radar test (T01) is still what shows which state a
blinded owner radar reaches. When
its object-list output on bus 1 stops (on a second car, when the receiver stopped answering the radar's transfers),
it sets 0x411 byte 0 to `0x48` (`PCS_INDICATOR` 1 plus bit 3) 2.0-2.2 s later for 4-21 s, not latched; `0x40` for the first frames after
power-up is the lamp check ([`stock_acc_unfiltered.json`](../data/analysis/summaries/stock_acc_unfiltered.json)); a relay that always sends the idle frame would report "all clear" whatever the radar's alerts say, which is why the table forwards them. The candidate bus-1
signals for blockage and faults are listed in [17](17_upstream.md#what-radard-gets-from-other-radars); a drive
with a covered or dirty radar shows which candidate reacts, and "PCS on" reports a blinded radar from that point.

## Where a relay stands (for developers)

| relay stage | radar bus (input) | car bus (output) | status |
|---|---|---|---|
| idle link | records arriving | idle 0x283 (33 Hz) and 0x344 (20 Hz), continuous | ● recorded (O5) |
| alarm / FCW | 0x100 byte 0 = 0x02 (radar enabled) | 0x283 `PCSNOCHG`, 0x344 `PCSALM`, 0x411 FCW | ● 8 alarms (U3 and 7 in the fleet logs); the 0x100 flag of a disabled radar is a recording to make |
| pre-fill, brake assist | none found (only the event pair was active) | 0x344 `PBATRGR` with 0x33E byte 6 bit 7 (fleet, 4 events); pre-fill not set in any recorded frame | ◐ brake-assist trigger on the car bus |
| autonomous braking | to record | 0x283 `FORCE` / `STATE` 3, 0x344 `DSS1GDRV`: values and sequence to record | ○ |

What this means for a build today:

- **A braking relay waits for recordings** of the frames that make the brake system act and of the radar-bus values
  that announce them. Any build sends recorded brake requests only.
- **A warning-only relay duplicates openpilot's warning.** openpilot already shows a forward-collision warning and sends
  FCW in 0x411 under alpha long; a relay would swap in Toyota's decision for openpilot's. The alarm-stage frames (0x344
  `PCSALM`, 0x283 `PCSNOCHG`) may also prime brake assist in the brake system, so their effect is the first thing to
  record.
- **0x283 has a low-speed state the relay must also carry.** In Park with a stationary object 2-3 m ahead the radar has sent
  `STATE` 4 with no force for 0.3-2.5 s (five times, three cars; its meaning is open). Upstream panda lets openpilot send 0x283
  only with bytes 0-5 zero, so even this frame needs the relay's own panda rule.
- **A passive watcher is the safe first build.** Read 0x100 on bus 1 while the radar is disabled, log it, and raise
  openpilot's existing FCW alert when it fires. It stays read-only on the car bus and tests the signal on
  real drives.

## Open questions

*Can a relay bring the radar's AEB back under openpilot longitudinal?* On an unfiltered radar line, openpilot longitudinal
disables the radar and its AEB. The disabled radar keeps assessing threats on bus 1, and openpilot would pass its brake
decision to the car as 0x283 / 0x344, keep 0x344 running for the brake system's link check, and show PCS on the dash only
while the relay is healthy. How it would work, and what is needed first, are above
([relay](#relaying-the-radars-decision--theoretical), [stages](#where-a-relay-stands-for-developers)); the first item is one recorded stock AEB activation with bus 0 and
bus 1 logged ([recordings](#recordings-that-settle-the-open-stages)).

*What does the radar's PCS alarm react to, and from what size of object?* U3's alarm came with a parked pickup tracked at
14.5 m and an inflatable at the bumper that left the object list empty at its position
([above](#a-recorded-stock-pcs-alarm-u3)). The radar tracks pedestrians at 0.5 × 0.4 m, so the
camera's link and a weak 77 GHz reflection are the two candidates. *Data:* a recorded series of alarms on radar-reflective
soft targets of graded size with separately characterised target controls ([recording](#recording-pcs--aeb-events)).

## Recordings that settle the open stages

The professional / passive recording specification, target controls and required logs are [below](#recording-pcs--aeb-events).
These are facility-managed engineering tasks.

1. **The alarm with the radar disabled:** a facility-managed comparison with the radar's car-bus output disabled and
   bus 1 logged. A repeated 0x100 alarm association qualifies that signalling path. Ordinary driving can also settle it:
   the fleet logs hold 2.4 moving hours with the radar disabled and no alarm, but at the stock rate on firmware 03100
   (0.098 alarms per moving hour) that is expected (0.08 alarms). About 30 moving hours (15-76) of disabled driving on
   that firmware, with bus 1 logged, would show whether the alarm survives the disable.
2. **A stock activation that reaches braking**, with bus 0 and bus 1 logged, a validated soft target, independent
   actuator / driver-action labels, and the radar enabled. Bus 0 gives the braking sequence in 0x283 / 0x344; bus 1 shows
   which radar-bus values mark it, next to 0x100. The target is a radar-reflective soft target of the kind made for
   ADAS / NCAP testing (U3's inflatable left the object list empty at its position).
3. **Which object a warning is about:** separate characterised target controls with a clean background and independently
   measured motion distinguish U3's candidate targets.
4. **A fork-level design** of the panda limits and the health check, reviewed before anything brakes the car on the
   road. A relay is a fork-only safety function.

Share recordings through a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new/choose).

## Recording PCS / AEB events

The radar's PCS output is decoded through an alarm-stage event
([above](#a-recorded-stock-pcs-alarm-u3)). Further evidence needs isolated target identity,
warning-versus-braking stages and the radar's behavior when its car-bus output is disabled. This section specifies
what to record at a professional test facility or during an incidental event in normal driving.
For ordinary routes and other controlled tests, use [16](16_routes_and_tests.md).

Toyota advises leaving PCS testing to professionals
([RAV4 quick-reference guide, PCS section](https://assets.sia.toyota.com/publications/en/om-s/OM19V1QRG/pdf/OM19V1QRG.pdf)).
Keep every approach speed, target design, abort condition and vehicle-control decision with the facility's validated
procedure, and keep driver braking at its normal timing. This section supplies the data requirements; the facility
supplies the safety setup.

### 1. Isolate and identify the target

U3 had an inflatable decoration and a pickup behind it. The object list tracked the pickup and held 0 entries for the inflatable, so either object may be the warning's intended target
([above](#a-recorded-stock-pcs-alarm-u3)). A new experiment controls the target separately.

- Use a facility-approved, radar-characterized ADAS soft target for a radar-target experiment, and as the only object on
  the approach path; keep people, real parked vehicles and homemade reflector assemblies off it.
- Keep the target's background free of other plausible reflectors; record the complete scene and surveyed positions.
- Measure the target's position and motion independently and demonstrate association before interpreting a PCS edge.
- Read a gap in the object list at the target as an association limit: a radar detection below threshold or a camera input outside the log can each be the source of the warning.

### 2. Record the complete event

Keep full rlogs on all available CAN buses, synchronized external video/reference and road-camera frame indices.
Retain at least 30 seconds before and after the event, adjacent segments, driver actions and the actual sensor/
controller configuration. Record the target alias, radar/filter state, longitudinal mode and any dashboard messages.

| Group | Fields to retain |
|---|---|
| threat and alarm | bus-1 0x100, 0x195/0x196; 0x80/0x85; selected targets 0x235/0x237/0x239/0x23B; car-bus 0x33E |
| PCS and brake stages | original car-bus 0x283/0x344/0x411, brake-pressure/force fields where logged, stockFcw/stockAeb |
| driver and motion | brake/gas, carState, pose/IMU, independently logged target/ego motion, controls and planner outputs |
| configuration/health | radar firmware, fork/profile/version, CAN filter or DSU, diagnostics/restriction where available, all messages before/after |

Verify that the original car-bus outputs reach the log, whatever filter or openpilot configuration is installed. Map
CAN receipt time, video SOF and reference acquisition time to one clock with a measured offset; wall-clock notes and
visual overlap give an approximate alignment.

### 3. Conditions to request from a facility

| Condition | Setup to document | Question |
|---|---|---|
| A: isolated radar-visible target | facility-approved target, radar enabled | whether the alarm and bus-1 0x100 association repeat on a uniquely identified target |
| B: target-visibility control | a separately characterized target, the only reflector in the scene | whether warning behavior differs with radar visibility; input source needs independent evidence |
| C: brake-stage capture | facility-managed warning, brake-assist, pre-fill and autonomous-braking conditions, labelled separately | which car-bus commands and radar-bus values mark each stage |
| D: disabled-output condition | facility-approved control/logging setup with the radar's car-bus output disabled | whether bus-1 threat/alarm signaling remains available; the car's warning or braking is recorded as observed |

Keep runs where warning and braking stay idle, labelled **unexercised**: each records the conditions tried. The facility separates driver braking, brake assist and autonomous action; the
actuator source comes from the brake-pressure/force fields and stage labels, since a pedal press or deceleration trace is
common to all three.

### 4. What the result can support

Repeated, stage-labelled events qualify an alarm or braking decision signal and its timing within the tested
configuration. A safe AEB relay, universal target detection and restoration of stock behavior are separate
questions that need their own fork-level design and safety review
([above](#where-a-relay-stands-for-developers)).
Short-TTC 0x195/0x196 activity with PCS idle is a useful control, with its own label.

Brake requests come from decoded, stage-labelled stock events; a warning-only signal stays a warning, and message
replication is described as replication.

### 5. Share privately, report anonymously

Open a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new?template=research_finding.yml)
with the condition table, firmware/configuration, relative event times, observed stages, reference uncertainty
and runs labelled unexercised. Offer rlogs and video privately; the maintainer arranges transfer.
Keep route/dongle IDs, VINs, GPS and identifying footage out of public posts. The public repo carries anonymous
signal summaries and reproduction instructions.

## Advanced: a radar setting that drops only 0x343 (○ candidate)

Another route to AEB under openpilot longitudinal is a Toyota-specific setting, if one exists, that mutes only the
radar's ACC command (0x343) while its PCS messages keep running. Standard communication control mutes every message.
Someone with Toyota's dealer tool (Techstream) or service information can check whether the radar offers such a setting.
Explore it **only on a spare radar on the bench**: a changed radar configuration can leave the radar faulted, AEB included.
Report what you find through a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new/choose).
