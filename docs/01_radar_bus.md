# 01. The radar bus

The ARS510 uses a private radar–camera CAN link, which the comma harness exposes as **bus 1** (`src == 1` in openpilot logs).
Ego speed comes from the car bus (bus 0, Toyota `SPEED` 0xB4). The radar runs a **60 ms cycle (16.7 Hz)**.

```mermaid
flowchart LR
    L["Private radar–camera link<br/>bus 1"] --> O["0x80 object list<br/>742 B record / 60 ms"]
    L --> M["0x85 metadata record<br/>147 B / 60 ms"]
    L --> A["0x235 / 0x237<br/>radar ACC target, 50 Hz"]
    L --> S["0x190-0x198, 0x24x, 0x5xx<br/>timing, targets, status"]
    C[Car] -- "bus 0" --> E["0xB4 wheel speed"]
    O --> D[ars510 decoder]
    M --> D
    E --> D
    D --> P["RadarPoints<br/>dRel, yRel, vRel, trackId"]
```

Stock opendbc parses TSS2 radar tracks at 0x180-0x19F with `toyota_tss2_adas.dbc`, the track layout of other TSS2
Toyotas. On the ARS510 the object list is the segmented record on 0x80, and 0x191-0x194 carry two target summaries from
the radar's internal tracker ([05](05_acc_target_and_support.md#0x191-0x194-selected-target-summaries)).

## Message map

| addr | DLC | rate | content | doc |
|---|---|---|---|---|
| **0x80** | 8 | 106 frames / 60 ms | **object list**: 742-byte record, 20 object slots × 36 bytes + CRC32 | [02](02_object_list.md), [03](03_slot_fields.md) |
| 0x81 | 8 | 16.7 Hz | record-cycle marker `30 00 …` after each 0x80 record start | |
| **0x85** | 8 | 21 frames / 60 ms | metadata record: 147 bytes, ten 12-byte cells (lane / road-boundary curves: offset, heading, curvature) + CRC32 | [04](04_metadata_record_0x85.md) |
| 0x86 | 8 | 16.7 Hz | record-cycle marker for 0x85 | |
| 0x100-0x103 | 7/6/3/2 | 10 Hz | startup state: 0x101 goes 0x1D → 0x11 when the radar is running | [05](05_acc_target_and_support.md#startup-and-readiness) |
| 0x180 | 5 | 16.7 Hz | constant `CF C0 00 00 00` | |
| 0x190 | 7 | 16.7 Hz | cycle header: number of target summaries, µs timestamp and a mod-16 cycle counter | [05](05_acc_target_and_support.md#0x190-cycle-header) |
| 0x191 / 0x193 | 8 | 16.7 Hz | selected-target companions: score, age, track code, class template (width, height, length) | [05](05_acc_target_and_support.md#0x191-0x194-selected-target-summaries) |
| 0x192 / 0x194 | 4 | 16.7 Hz | target summaries: distance and lateral position of one internal-tracker target each | [05](05_acc_target_and_support.md#0x191-0x194-selected-target-summaries) |
| 0x195 / 0x196 | 8 | 16.7 Hz | paired event frames; exact idle payloads in 99.67% of recorded frames | [05](05_acc_target_and_support.md#0x195--0x196-event-pair) |
| 0x197 / 0x198 | 2 / 1 | 16.7 Hz | 0x197 bit 8 = radar running; 0x198 constant `10` | |
| 0x202 | 5 | 16.7 Hz | counter + check byte | |
| 0x210 | 7 | 5 Hz | copy of Toyota road-sign-assist data | |
| **0x235 / 0x237** | 8 | 50 Hz | **radar ACC target** (sent by the radar, ◐): closing speed, relative acceleration, distance, lateral position and speed, target ID, in-path state | [05](05_acc_target_and_support.md#the-radars-acc-target-0x235--0x237) |
| 0x239 / 0x23B / 0x23D | 8/3/8 | 50 Hz | ACC target companions: 0x239 = class, object-list flag, µs timestamp; 0x23B = width in cm + counter + CRC-8; 0x23D all zero | [05](05_acc_target_and_support.md#class-width-and-timestamp-0x239--0x23b) |
| 0x240-0x245, 0x248 | 8 | 16.7 Hz | camera-sent context frames with a rolling phase 1-7; 0x240/0x244 carry light-source records at night | [05](05_acc_target_and_support.md#0x240-0x248-context-frames) |
| 0x24D / 0x24F | 7 / 1 | 1 Hz / 33 Hz | state frame; 0x24F bit 6 = radar running | |
| 0x500 / 0x501 / 0x502 | 6/7/8 | slow | unit-specific constants (redacted in the DBC), status nibble, two slowly drifting codes | |
| 0x680 | 8 | 2 Hz | one tracked object: distance, lateral position, over-ground speed; mostly a stationary roadside object | [05](05_acc_target_and_support.md#0x680-single-object-stream) |

Every frame above is in [`dbc/ars510_radar_bus.dbc`](../dbc/ars510_radar_bus.dbc) with a one-line comment per signal.

## Power-up

| time after the first CAN frame | event |
|---|---|
| 0.2 s | 0x235 / 0x237 (ACC target frames), 0x191 target summaries and 0x680 frames start |
| 0.8 s (median) | 0x680 reports its first tracked object |
| 3.3-4.2 s | openpilot's fingerprinting is done and it starts transmitting (current openpilot) |
| **5.83-6.12 s** | **0x80 / 0x85 object records start** (27 cold starts, [`object_stream_0x680.json`](../data/analysis/summaries/object_stream_0x680.json)) |

- The object list starts after openpilot's fingerprinting has finished, so the openpilot integration detects the
  radar by its firmware version (`8821F0R03100` at 0x750 / 0x0f), with
  0x80 / 0x85 on bus 1 as a fallback ([08](08_openpilot_integration.md)).
- 0x101 switches 0x1D → 0x11 0.14 s after the first 0x80 record and 0x197 bit 8 sets 60 ms later (27 of 27 cold
  starts, spread 7-14 ms): the camera's acknowledgement of the object list, a direct "radar running" signal.
- 0x680 reports tracked objects well before the object list starts.
- Several addresses send an all-ones or all-zeros first frame (for example 0x100 `FFFF…`, 0x192 `0FFF0FFF`).
- Early object records contain placeholder tracks, some at exactly 0 m; the age gate removes them.

## openpilot's radar disable

On the RAV4 2023 the radar itself sends the car's ACC command: opendbc marks the platform `RADAR_ACC`, so openpilot
longitudinal (alpha long) switches the radar's car-bus output off with UDS CommunicationControl `28 01 01` (receive
on, transmit off) to 0x750 / 0x0F, then keeps it off with tester-present `3E 00` every ~0.2 s. That request only
covers bus 0; **bus 1 keeps running unchanged** (●, one unfiltered drive with no CAN filter or other bus-1
hardware, firmware `8821F0R03100`; [`radar_disable_unfiltered.json`](../data/analysis/summaries/radar_disable_unfiltered.json)):

| | before the request | after (26 min, openpilot longitudinal engaged 8 min) |
|---|---|---|
| radar's response | | `68 01` (positive) 20 ms later |
| bus 0 from the radar: 0x283, 0x343 (33 Hz), 0x344 (20 Hz), 0x33E, 0x365, 0x366 (5 Hz), 0x411, 0x494, 0x4FF (~1 Hz) | sent | silent |
| bus 1: all 36 addresses, 0x80 / 0x85 records, ACC target 0x235 / 0x237 | sent | sent at full rate; 25,849 records, 0 CRC failures |
| 0x101 / 0x197 / 0x24F running flags | running | running |

So on this firmware the decoder works with the radar line unfiltered: the object list, the ACC target and the target summaries all
survive openpilot's radar disable. The car-bus messages it switches off, including the radar's PCS / AEB brake
request, are described in [13](13_car_bus_messages.md).

## Ego speed

The object velocities are **over ground**, so the consumer subtracts ego speed. Toyota 0xB4 reads about 1-1.5% below
GPS and wheel speed; every driving profile reads the radar speed at 0.149 m/s per code (`vground_scale = 0.149 / 0.15`
on the nominal 0.15) and subtracts 0xB4 speed ([06](06_accuracy.md#velocity)).
