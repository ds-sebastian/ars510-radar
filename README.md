# ARS510 radar for openpilot

Decoder, DBCs and openpilot integration for the **Toyota / Continental ARS510** front radar, the radar in the
**RAV4 TSS2 2022 / 2023** (openpilot `TOYOTA_RAV4_TSS2_2022` / `_2023`, radar firmware `8821F0R03100` at 0x750 / 0x0f).
openpilot currently runs these cars vision-only; this repo turns the radar's object list into openpilot radar tracks.

![decoded objects on the highway](docs/img/shots/highway_busy.jpg)

*Decoded objects projected onto the road camera. Each box is one radar object at its decoded distance and lateral
position, labelled with track ID, distance, lateral offset and relative speed.*

## Status at a glance

| | state |
|---|---|
| **Object list** (0x80): transport, CRC, 20 slots, track IDs | ● decoded |
| **dRel, yRel, velocity over ground** | ● field layout and motion interpretation; ◐ exact physical zero/scales ([06](docs/06_accuracy.md)) |
| **Object attributes**: lane assignment, class, width / length, angle output, lateral velocity and acceleration, existence score, uncertainties | ◐ decoded; angle defaults and motion-state resets characterised, physical names/scales and independent heading remain provisional ([03](docs/03_slot_fields.md)) |
| **The radar's own ACC target** (0x235 / 0x237, 50 Hz) | ● decoded ([05](docs/05_acc_target_and_support.md)) |
| **Target summaries** (0x191-0x194) | ● raw structure; ◐ target-summary interpretation; metric and class calibration required ([05](docs/05_acc_target_and_support.md)) |
| **Event pair** (0x195 / 0x196) | ● raw payloads and carry-linked 10-bit view; physical meaning and field validity require validation ([05](docs/05_acc_target_and_support.md#0x195--0x196-event-pair)) |
| **openpilot integration**: current openpilot, StarPilot, sunnypilot | installable; replayed end to end; driven by the owner on FrogPilot and StarPilot ports ([08](docs/08_openpilot_integration.md)) |
| **Main open issue** | velocity excursions: 1-10 s false closings beyond 40 m. The `steady` profile halves extra jitter, guards large jumps and delays far-track pickups; gradual ramps and recovery tails can still produce braking ([07](docs/07_velocity_excursions.md)) |

● confirmed · ◐ likely · ○ candidate

## What the radar gives you

| | |
|---|---|
| ![field map](docs/img/analysis/field_map.png) | ![lane weights](docs/img/analysis/lane_weights.png) |
| **Every bit of an object slot**, by role and confidence ([03](docs/03_slot_fields.md)) | **The radar assigns each object to a lane**: ego, left or right, in 1/15 steps |
| ![over ground](docs/img/analysis/vground_vs_ego.png) | ![object size](docs/img/analysis/object_size.png) |
| **Velocity is over ground**: traffic on v_ego, parked on 0, oncoming on −v_ego | **Class, width and length**: car, large vehicle, pedestrian, two-wheeler |

## How it fits into openpilot

```mermaid
flowchart LR
    CAN["CAN: bus 1 radar<br/>+ bus 0 wheel speed"] --> card --> RI["Toyota RadarInterface"]
    RI -- "ARS510 detected<br/>(firmware or 0x80/0x85)" --> A["Ars510RadarInterface<br/>reassemble · CRC · decode · track IDs"]
    A -- "RadarPoints, 16.7 Hz" --> radard["radard (unchanged)"] --> planner["planner (unchanged)"]
```

In replay against the driver (20 routes, 4.6 h), radar + vision **starts braking 0.15 s earlier** than vision alone
on real slowdowns and reacts to more of them, at the cost of some jitter from velocity excursions
([08](docs/08_openpilot_integration.md#radar--vision-against-vision-only-replay)).

## Install

```bash
python openpilot/install.py /data/openpilot/opendbc_repo --flavor openpilot  --profile steady   # current openpilot
python openpilot/install.py /data/openpilot/opendbc_repo --flavor starpilot  --profile steady   # StarPilot
python openpilot/install.py /data/openpilot/opendbc_repo --flavor sunnypilot --profile steady   # sunnypilot v2026.002.002
```

Then reboot the device. Details, the self-check and uninstall: [`openpilot/README.md`](openpilot/README.md).

## Decode in Python

```bash
pip install -e .[dev]    # the decoder itself has no dependencies
pytest
python tools/decode_log.py data/sample/highway_following_30s.csv.gz -o points.csv
```

```python
from ars510 import Ars510NativeRadarInterface, STEADY_CONFIG

radar = Ars510NativeRadarInterface(STEADY_CONFIG)
for t, bus, addr, data in can_frames:            # all buses: bus 1 = radar, bus 0 = car (0xB4 speed)
    out = radar.update_frame(t, bus, addr, data)
    if out:                                       # one per radar cycle (60 ms)
        for p in out["radarData"]["points"]:
            print(p["trackId"], p["dRel"], p["yRel"], p["vRel"])
```

## The core decode

The object list arrives on **bus 1, 0x80** as a 742-byte record split over 106 frames: a header, 20 slots of 36 bytes
and a CRC32. Each slot is one little-endian bit field:

| field | bits | decode |
|---|---|---|
| dRel (forward) | `32\|12` | `(code − 160) / 16` m |
| yRel (left +) | `44\|12` | `(code − 2048) / 64` m |
| velocity over ground | `64\|10` | `(code − 510.5) × 0.15` m/s; vRel = this − ego speed |
| age | `24\|7` | radar cycles; a restart is a new track |
| lane weights (right / left / ego) | `148\|4`, `152\|4`, `156\|4` | 0-15, summing to 15 or 16 |
| class | `163\|3` | 1 new, 2 car, 3 large vehicle, 4 pedestrian, 5 provisional (cyclist/person associations; ○), 6 two-wheeler |

These are nominal affine decodes, with calibration limits in [06](docs/06_accuracy.md#encoding-constants-and-motion-geometry).
The velocity zero near 510–511 does not establish the factory rounding rule. The driving profiles apply an
additional `.149 / .15` ground-speed alignment before subtracting Toyota 0xB4 ego speed.

The full field list is in [docs/03](docs/03_slot_fields.md).

## Documentation

| doc | contents |
|---|---|
| [01 Radar bus](docs/01_radar_bus.md) | every message on the radar bus, power-up timeline |
| [02 Object list](docs/02_object_list.md) | 0x80 transport, header, track IDs, an object's life, which objects the radar lists |
| [03 Slot fields](docs/03_slot_fields.md) | every bit of an object: kinematics, lifecycle, lane assignment, class and size, uncertainty |
| [04 Metadata record](docs/04_metadata_record_0x85.md) | 0x85: pairing with 0x80, lane-boundary cells |
| [05 ACC target and support messages](docs/05_acc_target_and_support.md) | 0x235 / 0x237, target summaries, timing, readiness |
| [06 Accuracy](docs/06_accuracy.md) | distance, lateral, velocity and identity against camera and odometry |
| [07 Velocity excursions](docs/07_velocity_excursions.md) | the jitter / false-closing issue and the options against it |
| [08 openpilot integration](docs/08_openpilot_integration.md) | how it hooks in, profiles, radard behaviour, replay and road results |
| [09 Tools and data](docs/09_tools_and_data.md) | decoding, Cabana, replay, the dataset, testing on your car |
| [10 Research directions](docs/10_research_directions.md) | the most promising next steps |

## Repository layout

| path | contents |
|---|---|
| [`ars510/`](ars510) | pure-Python decoder: reassembly, CRC, slot decode, track IDs, openpilot-shaped interface (`OPENPILOT_CONFIG`, `STEADY_CONFIG`) |
| [`dbc/`](dbc) | `ars510_radar_bus.dbc` (every radar-bus frame) and `ars510_objects_vbus.dbc` (reassembled objects for Cabana) |
| [`openpilot/`](openpilot) | installer, per-fork hook patches, self-check, optional radard patch |
| [`tools/`](tools) | log decoder, Cabana exporter, openpilot replay harness, figure and statistics scripts |
| [`data/`](data) | two real CAN samples, an anonymised analysis dataset (3 drives, 88 min) and summary JSONs |
| [`docs/`](docs) | the documentation above |

## Where the evidence comes from

One owner's 2022 RAV4, logged with openpilot: three reference drives (A development, B city, C highway; 88 minutes)
with camera and odometry references, 399 one-minute segments from 24 drives for field statistics, 20 held-out routes
(4.6 h) for replay against the driver, and closed-loop drives on FrogPilot and StarPilot. Route IDs, dongle IDs, GPS
and full video are not included.

## License

MIT (see [LICENSE](LICENSE)). The DBCs and docs are yours to reuse in opendbc or elsewhere.
