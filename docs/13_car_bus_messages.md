# 13. The radar's car-bus messages

On the RAV4 2022 / 2023 the ARS510 is also Toyota's driving-support ECU (`DS1` / "DSU" in the DBCs). It sends
nine messages on the **car bus (bus 0)**, the same ones a TSS-P DSU sends. They carry the ACC command, the
pre-collision (PCS / AEB) brake request and the PCS status on the dash. openpilot longitudinal either filters or switches off these
messages, which decides whether the car keeps its automatic emergency braking. Numbers:
[`radar_car_bus_messages.json`](../data/analysis/summaries/radar_car_bus_messages.json) and
[`radar_disable_unfiltered.json`](../data/analysis/summaries/radar_disable_unfiltered.json).

## The nine messages

All nine stop when openpilot disables the radar ([01](01_radar_bus.md#openpilots-radar-disable)), so the radar sends them.

| addr | name (opendbc / Toyota) | rate, DLC | idle payload | content | |
|---|---|---|---|---|---|
| 0x343 | `ACC_CONTROL` / `ACC1S03` | 33 Hz, 8 | `00 00 43 00 00 00 00 91` at power-up | ACC acceleration request and ACC / HUD flags | ● |
| 0x344 | `PRE_COLLISION_2` / `ACC1F01` | 20 Hz, 8 | `00 00 01 00 00 00 00 50` | PCS / AEB deceleration request, pre-fill and alarm triggers; idle with only `PCSOPR` (bit 16) set | ● idle, ◐ fields |
| 0x283 | `PRE_COLLISION` / `DS11F01` | 33 Hz, 7 | `00 00 00 00 00 00 8C` | AEB brake force and state (`STATE` 3 = emergency braking) | ● idle, ◐ fields |
| 0x33E | none | 5 Hz, 7 | `7F FF 00 80 00 xx 00` | target-gated fields, one rising with ego speed | ○ |
| 0x365 | `DSU_CRUISE` / `DS11D70` | 5 Hz, 7 | `00 00 00 00 FC 00 00` | **ACC lead distance (m) and relative speed (km/h)** | ● |
| 0x366 | `DS11D71` | 5 Hz, 7 | `50 00 7F FF 00 7A 00` | **target report**, mostly the ACC target: relative speed (0.5 km/h), distance (≈ 0.8 m), lateral offset (0.34 m per code) | ◐ |
| 0x411 | `PCS_HUD` / `DS12F02` | 1 Hz, 8 | `00 20 00 00 00 00 80 00` | PCS state, sensitivity, FCW and the blocked-radar / temperature / beam-alignment alerts | ● idle, ◐ alerts |
| 0x494 | none | 1 Hz, 8 | `82 00 00 00 00 00 00 00` | constant | ○ |
| 0x4FF | `FRD1N01` (front radar → gateway) | ~0.8 Hz, 8 | `3F 00 00 00 00 00 00 00` | front-radar node frame, `FRDNID` = 0x3F | ○ |

Toyota names come from the leaked `toyota_2017_ref_pt.dbc` in opendbc. 0x343, 0x344 and 0x283 end in the Toyota
checksum: (address high byte + low byte + DLC + data bytes) & 0xFF. In normal driving 0x283, 0x344, 0x411, 0x494 and 0x4FF hold their idle payloads
(4.1 h of owner drives and U1; 0x411 over 752 owner segments, where it reads `40 20 …`, `PCS_INDICATOR` 1, from about 0.2 s to 3 s
after each of 27 cold starts).
0x33E, 0x365 and 0x366 change with the lead.

### 0x365: lead distance and relative speed (●)

Byte 4 is the distance to the radar's ACC target in metres, and 0xFC means no target. Byte 5 is the relative speed in km/h,
signed, negative when closing. The other bytes are zero. Both fields match the ACC target (0x235 / 0x237,
[05](05_acc_target_and_support.md#the-radars-acc-target-0x235--0x237)) on two owner drives and on a second car up to 37 m/s:

| drive | distance: scale, r, MAD | speed: scale, r, MAD | frames |
|---|---|---|---|
| O2 (city, ≤ 22 m/s) | 0.992, 0.9995, 0.24 m | 0.999, 0.9997, 0.14 km/h | 830 |
| O3 (city, ≤ 18 m/s) | 0.997, 0.9992, 0.17 m | 1.001, 0.9995, 0.14 km/h | 474 |
| U1 (expressway, ≤ 37 m/s) | 0.997, 0.9992, 0.22 m | 0.995, 0.993, 0.27 km/h | 1,816 |

This is opendbc's `DSU_CRUISE.LEAD_DISTANCE`, plus the Toyota name `D_VRCC` for byte 5.

### 0x366: target report, mostly the ACC target (◐)

Fields count MSB-first from the first payload bit; `ars510.support.parse_0x366` returns them (`None` for the `7FFF` no-target word).

| bits | field | coding |
|---|---|---|
| `16\|9` | relative speed | `(code − 155) × 0.5 km/h` for codes below 256; higher codes (seen: 442-506) return `None` |
| `25\|7` | distance | ≈ 0.8 m per code (fit 0.79); 127 = no target |
| `40\|5` | lateral offset | signed, −0.34 m per code (right positive, ±5 m); 15 = no target, −16 = invalid (mostly a target beyond ±5 m) |

**While the radar has an ACC target, 0x366 reports that target.** Against the latest `0x235`/`0x237` on an owner drive
(820 frames) the residuals are 0.06 m/s, 0.26 m and 0.14 m, about the quantization of both frames, and 99 % agree in
distance within 1.5 m ([summary](../data/analysis/summaries/target_366_coding.json)).

**It also reports while there is no ACC target**: 224 of 1,059 reports on owner drive O2 and 8 of 467 on O3, with fresh
ACC frames saying "no target" (one span of 32 reports over 6.2 s). On O2 the car moves slowly during them (median ego 1.6 m/s, median relative speed −7 m/s); the 61 that match an
object-list track sit a median 4 m to the side, and their speeds correlate at 0.81; the target it picks then is possibly a PCS candidate (○)
([coverage](../data/analysis/summaries/target_366_coverage.json)).

![0x366 report coverage](img/analysis/target_366_coverage.png)

**High speed codes.** Eight reports have codes 442-506; five same-tail steps among them close at 20-28 m/s by their distances; subtracting 512 counts
fits them (mean difference 2.9 m/s). The parser returns a speed for codes below 256, the domain the ACC target confirms
([domain](../data/analysis/summaries/target_366_speed_domain.json)).

It arrives about 90 ms after 0x365. Byte 0 is 0x50 or 0x52, byte 4 bits 3-7 are raw speed / range-dependent flags, and
the low three bits of byte 5 are constant. The profiles take the same target from the 50 Hz ACC target frames.

![0x366 against 0x365](img/analysis/target_366_coding.png)

### 0x343 from the radar (●)

With stock ACC (U1, 21 min) the radar's own command spans −0.52 to +0.20 m/s². It always sends `ACC_TYPE` 1 and
`ALLOW_LONG_PRESS` 3, `MINI_CAR` 1 while it has a lead, mostly `PERMIT_BRAKING` 1, and `DISTANCE` pulses on button
presses. `RADAR_DIRTY`, `ACC_MALFUNCTION`, `ACC_CUT_IN` and `CANCEL_REQ` stay 0. openpilot's own `ACC_CONTROL` sends
`ALLOW_LONG_PRESS` 1.
On a second car with a board in the radar's car-bus line, stock ACC passes the radar's 0x343 through unchanged: `MINI_CAR`
equals ACC-target presence on 99.98 % of cruise-on cycles. Its command spans −0.83 to +0.72 m/s² while cruising, and stopped
behind a lead with cruise off it sends a constant −0.30 m/s² (U1 does the same on 96 % of such cycles). How the command follows the ACC target is in
[10](10_research_directions.md#learn-from-toyotas-own-longitudinal-control)
([`stock_acc_law.json`](../data/analysis/summaries/stock_acc_law.json)).

## openpilot longitudinal: filter or disable

The radar's car-bus link runs to the gateway, which relays it onto the car bus. The comma harness sits at the camera,
so the radar's 0x343 reaches the powertrain on a path that bypasses the panda. With one 0x343 sender allowed on the
bus, openpilot longitudinal needs one of two setups:

| | radar CAN filter (smartDSU-style) | openpilot's radar disable (alpha long) |
|---|---|---|
| how | a board in the radar's line drops only the radar's 0x343 while openpilot sends its own; status message 0x2FF (~51 Hz) lets forks detect it | UDS `28 01 01` to 0x750 / 0x0F switches off the radar's car-bus transmit |
| radar's 0x343 | ends as openpilot's begins (3.487 s / 3.501 s after power-up, O4) | silent |
| PCS / AEB (0x283 / 0x344) | **passed to the car**: the radar's AEB stays in place | **silent**: the radar's PCS / AEB request is off with its car-bus output |
| 0x411 on the dash | the radar's: PCS on | openpilot's `40 20 00 00 10 01 00 00`: PCS off |
| car's reaction | normal (0x320 bit 13 clear) | **0x320 bit 13** set (0x344 missing, below); dash "Pre-Collision System Malfunction" and PCS OFF lamp |
| bus 1 (decoder input) | running | running ([01](01_radar_bus.md#openpilots-radar-disable)) |

**0x320 bit 13 = "0x344 missing" (●).** 0x320 (`VSC1S07`) is the gateway's brake-system status to the
driving-support ECU. Its bit 13 (byte 1 bit 5; Toyota name `P2BRXMK`) sets about 0.15 s after the radar's 0x344
(`ACC1F01`) stops and clears on the next 0x320 frame (20 Hz) once 0x344 is back. 0x283 does not affect it, and neither does
0x344's `PCSOPR` bit (16, "PCS operational", 1 in the radar's idle frame).

![0x320 bit 13 during the O5 replay test](img/analysis/pcs_flag_0x344.png)

The test was run on O5, the owner's car, parked in P. Toyota's interface disabled the radar with openpilot's UDS request,
then replayed the radar's idle frames from openpilot in 15 s phases:

| on the car bus (O5) | 0x320 frames with bit 13 clear / set |
|---|---|
| radar's own messages | 2,713 / 1 |
| radar silent, nothing replayed | 0 / 1,906 |
| idle 0x283 only | 0 / 307 |
| idle 0x344 (`PCSOPR` 1) | 306 / 0 |
| idle 0x344 with `PCSOPR` 0 | 305 / 1 |
| 0x283 + 0x344, `PCSOPR` 1 / 0 | 305 / 1, 305 / 1 |

The single set frames are each the last frame of a phase, 0.15 s after 0x344 stopped. On U2 (unfiltered, alpha long)
the bit sets 0.17 s after the disable and stays set for the whole drive; on U1 and on filtered cars it is clear.

**The dash warning does not follow bit 13 (●, O5).** From about 7 s after the radar fell silent, the dash showed
"Pre-Collision System Malfunction – Visit Your Dealer" with the PCS OFF lamp. It stayed on in every replay phase. It cleared
by itself, with no restart, once the radar's messages (including its 0x411) were back. Replaying idle 0x344 therefore
keeps the brake system's link check satisfied without hiding from the driver that PCS is off. It does not restore
AEB: the radar's PCS brake request is still off.

**The event pair keeps running while the radar is disabled (◐).** On U2 the bus-1 event pair 0x195 / 0x196
([05](05_acc_target_and_support.md#0x195--0x196-event-pair)) became active 6 times (0.1-1.3 s, 4-7 m/s, ACC-target
time to collision 3.6-7.5 s). That state stays on bus 1. On U1 (stock ACC) the 5 comparable short states
left 0x283 / 0x344 / 0x411 idle: the event pair is a threat state that occurs without PCS action on the car bus (◐); the PCS brake request
itself travels on the car bus.

## What panda allows openpilot to send

openpilot's Toyota longitudinal TX list (DSU-unplugged TSS-P support) already covers most of these messages:

| message | panda |
|---|---|
| 0x343 | allowed, `ACCEL_CMD` −3.5..+2.0 m/s² |
| 0x344, 0x33E, 0x365, 0x366, 0x411 | allowed |
| 0x283 | allowed only with bytes 0-5 zero (the idle frame) |
| 0x494, 0x4FF | outside the TX list |

opendbc's `toyotacan.create_pcs_commands` builds 0x283 + 0x344; the carcontroller does not call it.

## AEB without a CAN filter

**Today:** stock AEB works with stock ACC (openpilot lateral only, no filter) and with openpilot longitudinal through a
radar CAN filter. With openpilot longitudinal and no filter, the radar is disabled and the car has no AEB. The dash
says so ("Pre-Collision System Malfunction", PCS OFF lamp).

**Why the disable takes AEB with it.** AEB is a live request: the radar sends non-idle 0x283 / 0x344 frames at the
moment it decides to brake, and the brake system acts on them. UDS communication control (`28 01 01`) stops all of the
radar's normal car-bus messages at once; there is no per-message mute that would keep 0x283 / 0x344 and drop only 0x343.
Startup order makes no difference: whatever openpilot sends before, during or after the disable, no brake request
leaves the radar afterwards.

### Relaying the radar's decision (○ theoretical)

The disable silences only the radar's car-bus side. On bus 1, which the comma reads, the radar keeps sending its object
list, ACC target and threat states at full rate ([01](01_radar_bus.md#openpilots-radar-disable)). On U2 its short
time-to-collision event pair (0x195 / 0x196, [05](05_acc_target_and_support.md#0x195--0x196-event-pair)) kept firing
while it was disabled. The radar's PCS logic appears to keep running; only its output to the car is cut. A relay would
reconnect that output through openpilot, so Toyota's own tuned decision logic still decides when to brake.

How it would work:

1. **Listen on bus 1.** Each cycle openpilot reads the radar's PCS state from bus 1: alarm, pre-fill, brake assist,
   autonomous braking, and the requested deceleration. This only works if the radar puts its brake decision on bus 1.
   The event pair seen so far is a threat state: on U1 its short states left 0x283 / 0x344 / 0x411 idle (above). A
   brake request has not been seen on bus 1, because no AEB activation has been recorded.
2. **Translate to the car bus.** openpilot sends the 0x283 / 0x344 / 0x411 frames the radar would have sent for that
   state. The mapping is learned from a car with a radar CAN filter, where both buses are visible at once during a stock
   activation: each bus-1 state lines up with the car-bus frames the radar sent at the same moment.
3. **Keep the streams running.**
   - **0x344 without a gap** (20 Hz, idle `00 00 01 00 00 00 00 50`). The brake system checks for it: 0x320 bit 13
     sets 0.15 s after it stops (above).
   - **0x283 idle** (33 Hz), so an activation only changes the content of a running stream.
   - The stages carry the reference names: alarm (`PCSALM`, `PCSWAR`, FCW in 0x411), brake pre-fill (`PREFILL`),
     brake assist, autonomous braking (0x283 `FORCE` and `STATE` 3, `PRECOLLISION_ACTIVE`; 0x344 `DSS1GDRV`
     deceleration).
4. **Fail safe.** If bus 1 goes stale, a record fails its CRC, or openpilot stops, the relay drops to idle frames, and
   the dash shows PCS off (below). The relay adds one openpilot cycle of delay (10-30 ms) to the radar's own timing.
5. **A panda safety mode that allows it.** Upstream panda passes 0x283 only with bytes 0-5 zero. A fork would allow
   the radar's brake request with limits: force, duration, only while moving, and only while bus 1 is healthy.

### The dash: PCS shows what is true

The malfunction warning does not follow 0x344 or 0x283 (O5 above); the radar's own 0x411 (`PCS_HUD`) is the leading
candidate. The rule for any implementation:

| situation | dash | 0x411 |
|---|---|---|
| relay healthy (radar records arriving, openpilot running, panda in its AEB mode) | PCS on | as the radar's idle frame, `PCS_OFF` 0 |
| any part unhealthy, or the relay not yet validated | PCS off | `PCS_OFF` 1, as upstream openpilot sends today |
| openpilot not running | malfunction | nothing sent; the car's own check reports it |

"PCS on" also has to carry the radar's real alerts. The radar's own 0x411 reports a blocked or dirty sensor
(`PCS_DUST2`) and faults (`PCS_INDICATOR` 2); a relay that always sends the idle frame would hide them. No blockage or
fault signal on bus 1 is known yet. Until one is found ([10](10_research_directions.md#what-radard-gets-from-other-radars):
a drive with a covered or dirty radar shows which candidate reacts), "PCS on" cannot report a radar blinded by snow or dirt.

### What is needed, in order

1. **One recorded stock AEB activation with bus 0 and bus 1 logged.** A car with a radar CAN filter keeps the radar
   enabled and can record it. Use an inflatable PCS test target on a closed lot at low speed. Bus 0 gives the activation
   sequence (0x283 / 0x344 / 0x411); bus 1 shows whether the radar announces its decision there, and how. Share
   it through a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new/choose).
2. **A parked 0x411 test.** With the radar disabled, send upstream's "PCS off" 0x411 and see whether the dash changes from
   "Malfunction" to "PCS off". This names the dash's input. It is the same kind of parked test as O5.
3. **A fork-level design** of the panda limits and the health check, reviewed before anything brakes the car on the
   road. A relay does not fit upstream openpilot; it is a fork-only safety function.

### Advanced: a radar setting that drops only 0x343 (○ unexplored)

Another route would make the relay unnecessary: a Toyota-specific setting, if one exists, that stops only the
radar's ACC command (0x343) while its PCS messages keep running. Standard communication control cannot do this, and no
such setting is known. Someone with Toyota's dealer tool (Techstream) or service information could check whether the
radar offers one. Explore it **only on a spare radar on the bench**: changing a radar's configuration can leave it
faulted, AEB included, and is not something to try on a car that is driven. Report what you find through a
[research finding](https://github.com/ds-sebastian/ars510-radar/issues/new/choose).
