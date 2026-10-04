# Installing the ARS510 integration

One installer for openpilot and its forks (sunnypilot, StarPilot and other trees with openpilot's `opendbc_repo`
layout). It adds the decoder and appends one marked block to the end of Toyota's `interface.py`; no fork file is
edited in place, and card, radard and the planner are untouched. How it works and what it does on the road:
[docs/08](../docs/08_openpilot_integration.md).

## Install on a comma device

```bash
cd /data && git clone https://github.com/ds-sebastian/ars510-radar
python /data/ars510-radar/openpilot/install.py /data/openpilot
sudo reboot
```

That's all: the fork is detected, the `anchor` profile is installed, and an install made with an older patch-based
version of this installer is replaced automatically. Pick another profile with `--profile steady` or `--profile raw`.

**Reboot after installing.** The manager pre-imports its Python processes, so a new ignition cycle alone keeps the old
Toyota modules. On the first drive after the reboot, `radarUnavailable` is false and leads are radar-backed.

```bash
python /data/ars510-radar/openpilot/install.py /data/openpilot --check        # report state, change nothing
python /data/ars510-radar/openpilot/install.py /data/openpilot --uninstall    # remove everything it added
cd /data/ars510-radar && git pull && python openpilot/install.py /data/openpilot   # update, then reboot
```

A fork update resets `/data/openpilot`: run the installer again after updating (and turn off automatic updates
while testing).

| profile | config |
|---|---|
| `anchor` (default) | `ANCHOR_CONFIG`: `steady` + the radar's own ACC target (0x235) as a bound on the lead's speed, and its target-range summaries (0x192/0x194) for far cars up to 80 m. Fewest false brakes at the same response ([docs/08](../docs/08_openpilot_integration.md#profiles)) |
| `fused` | `FUSED_CONFIG`: `raw` + range fusion + one uncertainty-weighted speed filter fusing the object list, the ACC target (0x235) and the summaries (0x192/0x194). Replaces the far-range layers and the anchor clips ([docs/07](../docs/07_velocity_excursions.md#fused-speed-filter-fused-profile)) |
| `steady` | `STEADY_CONFIG`: velocity-aided range, far-range vRel smoothing, far-track settling, ramp limiter ([docs/07](../docs/07_velocity_excursions.md#how-the-filtering-works-step-by-step)) |
| `raw` | `OPENPILOT_CONFIG`: the unfiltered radar decode (not vision-only, not stock openpilot) with only what radard needs, for research and comparison. Velocity excursions reach the planner unfiltered (about twice the hard false braking of `steady`); the installer prints a warning. `stock` and `default` are its older names |

## What gets installed

| file | installed as | what |
|---|---|---|
| `../ars510/` | `opendbc/car/toyota/ars510/` | the decoder package, unchanged |
| `ars510_radar_interface.py` | `opendbc/car/toyota/ars510_radar_interface.py` | `Ars510RadarInterface` (raw CAN → RadarData) and the hook |
| 4-line block | end of `opendbc/car/toyota/interface.py` | `CarInterface = hook_car_interface(CarInterface)` |

The DBCs in [`../dbc/`](../dbc) are for inspecting the radar in Cabana on a PC. Parsing does not use them (a DBC
cannot describe the 106-frame record), so they are not installed on the device.

The hook wraps the fork's own Toyota `CarInterface` after it is defined:
- **detection** in `_get_params`: a radar-ACC Toyota whose radar firmware is `8821F0R03100`, or whose fingerprint saw
  0x80 and 0x85 on bus 1, gets `radarUnavailable = False`;
- **tracks** through `CarInterface.RadarInterface`: `Ars510RadarInterface` for that car, the fork's own
  RadarInterface for every other car. Extra constructor arguments (sunnypilot's `CP_SP`) pass through, and forks
  whose RadarPoint still has `aRel` / `yvRel` / `measured` get those fields filled.

No `ToyotaFlags` bit is added, so the install cannot collide with a fork's own flags.

Fork notes:
- **StarPilot** runs its own radard (lateral gate when matching, match hysteresis, faster lead-acceleration decay) and
  enables its radar extras (adjacent-lane leads, "Force Stop" hint, radar UI) once radar is available. In replay with
  StarPilot's radard, the steady profile gives a 0.24 s head start over StarPilot's own vision-only, with 1.8
  radar-only brakes per hour (0.9 overridden with gas).
- **sunnypilot** carries `aRel` and `yvRel`: the radar's filtered acceleration and its lateral velocity, the latter
  using the Toyota 0x24 yaw rate.

## Test on a PC first

```bash
OP=~/openpilot                                          # any fork checkout with a .venv (tools/op.sh setup)
cp -r $OP/opendbc_repo /tmp/opendbc_ars510
python openpilot/install.py /tmp/opendbc_ars510
$OP/.venv/bin/python openpilot/check_integration.py --opendbc /tmp/opendbc_ars510
```

`check_integration.py` runs synthetic records through the installed Toyota interface the way card does:
- detection: cold start by firmware, fallback by bus 1, other cars untouched;
- RadarData points: units, sign, ego-speed subtraction, age gate;
- radarless behaviour before the first record;
- the timeout report and recovery when records stop and resume.

It passes 21-22 checks on current openpilot, the openpilot 10b9e73 used for replays and sunnypilot v2026.002.002. To
replay your own drives stock vs installed, see
[docs/09](../docs/09_tools_and_data.md#replay-your-drives-through-openpilot).

## Optional radard patch

[`radard_vision_fusion.patch`](radard_vision_fusion.patch) is **not** applied by `install.py`. It rewrites radard's
track filter in covariance form (identical output for radar-only tracks) and fuses the vision lead's speed into the
matched radar track. Apply it from an openpilot checkout with `git apply`. Effect and settings:
[docs/07](../docs/07_velocity_excursions.md#other-approaches-tested).
