# openpilot integration (experimental, not drive-tested)

This directory turns the decoder into radar tracks for **current openpilot**. It was built against opendbc
`4134c0d` / openpilot `10b9e73` (September 2026). It has been checked:
- by opendbc's own tests;
- by a self-check on synthetic records;
- by replaying logged drives through openpilot's real `card` → `radard` → `plannerd`.

It has **not** been run in a car. Read [docs/07](../docs/07_openpilot_integration.md) and [docs/14](../docs/14_stationary_objects_and_field_roles.md) first: vRel has unflagged excursions, and the radar never lists a vehicle that was already stopped when it came into view.

| file | installed as | what |
|---|---|---|
| `ars510_radar_interface.py` | `opendbc/car/toyota/ars510_radar_interface.py` | `Ars510RadarInterface`: raw CAN → RadarData |
| `../ars510/` | `opendbc/car/toyota/ars510/` | the decoder package, copied unchanged |
| `../dbc/*.dbc` | `opendbc/dbc/` | for cabana only; parsing does not use them |
| `opendbc_toyota_ars510.patch` | edits 3 Toyota files | detection flag, CarParams, hand-over in Toyota's `RadarInterface` |
| `install.py` | | copy the files and apply the patch (`--check`, `--uninstall`) |
| `check_integration.py` | | self-check of an installed copy, no car or log needed |

## How it hooks in

1. **Detection** (`toyota/interface.py`). A RADAR_ACC Toyota gets `ToyotaFlags.ARS510_RADAR` and
   `radarUnavailable = False` when either:
   - its radar FW is in `ARS510_FW_VERSIONS` (`values.py`, currently `8821F0R03100`); or
   - 0x80 and 0x85 were seen on bus 1 during fingerprinting.

   Other cars are unchanged. The FW rule is needed because after power-up the radar sends its first object record
   about 5.9 s after first CAN (11 of 11 logged cold starts, 5.83-5.92 s), and fingerprinting is over by then. An
   early version that only checked bus 1 missed the radar on every cold start in replay.
2. **Hand-over** (`toyota/radar_interface.py`). Toyota's `RadarInterface` delegates `update()` to
   `Ars510RadarInterface` when the flag is set. `card.py` needs no change. It calls
   `RI.update(can_capnp_to_list(...))` at 100 Hz and publishes `radarTracks` whenever that returns something.
   radard then runs unmodified.
3. **No CANParser.** The object list is one 742-byte record sent as 106 ISO-TP-style frames on 0x80 every ~60 ms.
   - CANParser keeps only the latest value per address, or a per-call list in `vl_all`.
   - A DBC cannot say which part of the record a frame holds: the sequence nibble wraps every 16 frames.
   - So the interface reads the raw `(address, data, src)` tuples that card passes in. It reassembles the frames,
     checks the record CRC32 and decodes the 20 slots. Ego speed for vRel comes from 0xB4 on bus 0 in the same
     packets.
   - Cost in replay on a desktop CPU: about 8 µs per call on average.
4. **Output.** `RadarPoint` is `trackId, dRel, yRel, vRel` in current cereal; `aRel`, `yvRel` and `measured` are
   deprecated. `OPENPILOT_CONFIG` is used:
   - tracks younger than 60 cycles are held back;
   - track IDs are re-linked across brief losses;
   - no point is published without a fresh ego speed, so vRel is never NaN.

## What it reports, and what openpilot does with it

| situation | RadarData | effect in openpilot |
|---|---|---|
| record completed (~16.7 Hz) | points, no error | radard fuses tracks with vision leads |
| before the first record (radar booting ~6 s, or silenced) | empty, no error, 20 Hz | same as a radarless car: vision-only leads |
| no record after one has arrived, for > 0.5 s | `radarUnavailableTemporary`, 20 Hz | radarTracks invalid → radarState invalid → selfdrived `commIssue` (lateral too); with openpilot long also `radarTempUnavailable` |
| CRC-failed record | dropped | nothing (the 0.5 s rule covers sustained loss) |

## Test it on a PC first

```bash
OP=~/openpilot                                    # checkout with .venv (tools/op.sh setup)
cp -r $OP/opendbc_repo /tmp/opendbc_ars510        # or install straight into $OP/opendbc_repo
python openpilot/install.py /tmp/opendbc_ars510
$OP/.venv/bin/python openpilot/check_integration.py --opendbc /tmp/opendbc_ars510
```

Replay your own drives, stock versus patched. See the docstring of
[`tools/openpilot_replay/process_replay_ars510.py`](../tools/openpilot_replay/process_replay_ars510.py). It uses
openpilot's process_replay, so the patched fingerprinting, CarParams and RadarInterface run exactly as `card` would
run them.

## Putting it on a comma device

This patch is for current openpilot. Install it into the device's `opendbc_repo` (or into your own openpilot fork
and install that branch), then reboot.

It does **not** fit FrogPilot 0.9.7 or other forks on the older car API:
- there, radard owns the RadarInterface and passes serialized capnp bytes;
- `RadarData.errors` is a list, and any entry raises `radarFault`, a soft disable.

Suggested order on the car, lowest risk first:

1. **Parked, ignition on, openpilot longitudinal off (stock ACC).** Check that `carParams.flags` has bit 4096 and
   `radarUnavailable` is false. After ~6 s, `radarTracks` should arrive at ~16.7 Hz with points.
2. **Drive with stock ACC, openpilot lateral only.** Radar tracks then feed radarState: the UI lead, and what the
   planner would do. They do not feed the car's longitudinal control. Afterwards compare radarState leads with the
   video. Look for `commIssue` events: they would mean 0x80 records paused for > 0.5 s.
3. **Alpha longitudinal, parked first.** On RAV4 2022 / 2023, alpha long sets `DISABLE_RADAR`, and card sends the
   radar a UDS *communication control: disable TX* at startup. **Check whether 0x80 keeps coming on bus 1 after
   that.** The logged drives never used this path: they ran FrogPilot with a device sending 0x2FF on bus 0, which
   FrogPilot treats as a smartDSU. If 0x80 stops, radar tracks and stock openpilot longitudinal are mutually
   exclusive on this car. The interface then stays in its radarless state (a warning is logged) and openpilot runs
   vision-only.
