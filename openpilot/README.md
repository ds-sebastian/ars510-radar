# Installing the ARS510 integration

`install.py` copies the decoder into a fork's `opendbc_repo` and applies a small hook patch to three Toyota files
(`values.py`, `interface.py`, `radar_interface.py`). card, radard and the planner are not touched. How it works and
what it does on the road: [docs/08](../docs/08_openpilot_integration.md).

## Install on a comma device

```bash
cd /data && git clone https://github.com/ds-sebastian/ars510-radar
python /data/ars510-radar/openpilot/install.py /data/openpilot/opendbc_repo --flavor <flavor> --profile steady
sudo reboot
```

| flavor | fork | ARS510 flag bit |
|---|---|---|
| `openpilot` | current openpilot (opendbc master, September 2026) | 4096 |
| `starpilot` | StarPilot (September 2026) | 16384 (StarPilot uses 4096 for `AUTO_BRAKE_HOLD`) |
| `sunnypilot` | sunnypilot v2026.002.002 `release-tizi` | 4096 |

| profile | config |
|---|---|
| `steady` | `STEADY_CONFIG`: default + velocity-aided range + far-range vRel smoothing + velocity-jump guard + far-track settling + ramp limiter. **Recommended.** |
| `default` | `OPENPILOT_CONFIG` (withholds saturated velocity readings) |

**Reboot after installing.** The manager pre-imports its Python processes, so a new ignition cycle alone can keep
running the old Toyota modules. After the reboot, check the first drive: `carParams.flags` has the ARS510 bit,
`radarUnavailable` is false, and leads are radar-backed.

Other commands:

```bash
python openpilot/install.py <opendbc_repo> --flavor <flavor> --check       # report state, change nothing
python openpilot/install.py <opendbc_repo> --flavor <flavor> --uninstall   # remove files and reverse the patch
```

A fork update replaces `/data/openpilot`; reinstall after updating (and turn off automatic updates while testing).

## What gets installed

| file | installed as | what |
|---|---|---|
| `../ars510/` | `opendbc/car/toyota/ars510/` | the decoder package, unchanged |
| `ars510_radar_interface.py` | `opendbc/car/toyota/ars510_radar_interface.py` | `Ars510RadarInterface`: raw CAN → RadarData, with the chosen profile |
| `opendbc_toyota_ars510.patch` (or the `starpilot/`, `sunnypilot/` variant) | edits 3 Toyota files | detection flag, `radarUnavailable = False`, hand-over in Toyota's `RadarInterface` |
| `../dbc/*.dbc` | `opendbc/dbc/` | for Cabana; parsing does not use them |

Detection: a `RADAR_ACC` Toyota whose radar firmware is `8821F0R03100`, or whose fingerprint saw 0x80 and 0x85 on bus 1.
Every other car keeps its existing radar parser.

Fork specifics:
- **StarPilot** runs its own radard (lateral gate when matching, match hysteresis, faster lead-acceleration decay) and
  enables its radar extras (adjacent-lane leads, "Force Stop" hint, radar UI) once radar is available. In replay with
  StarPilot's radard, the steady profile gives a 0.24 s head start over StarPilot's own vision-only, with 1.8
  radar-only brakes per hour (0.9 overridden with gas).
- **sunnypilot** passes `CP_SP` to the RadarInterface and still carries `aRel`, `yvRel` and `measured` in RadarPoint;
  the installer adapts the wrapper for both.

## Test on a PC first

```bash
OP=~/openpilot                                          # checkout with .venv (tools/op.sh setup)
cp -r $OP/opendbc_repo /tmp/opendbc_ars510
python openpilot/install.py /tmp/opendbc_ars510 --profile steady
$OP/.venv/bin/python openpilot/check_integration.py --opendbc /tmp/opendbc_ars510
```

`check_integration.py` runs synthetic records through the installed interface the way card does: detection (cold
start by firmware, fallback by bus 1), RadarData points (units, sign, ego-speed subtraction, age gate), radarless
behaviour before the first record, and the timeout report and recovery when records stop and resume. For
sunnypilot add `--flavor sunnypilot`. To replay your own drives stock vs installed, see
[docs/09](../docs/09_tools_and_data.md#replay-your-drives-through-openpilot).

## Optional radard patch

[`radard_vision_fusion.patch`](radard_vision_fusion.patch) is **not** applied by `install.py`. It rewrites radard's
track filter in covariance form (identical output for radar-only tracks) and fuses the vision lead's speed into the
matched radar track. Apply it from an openpilot checkout with `git apply`. Effect and settings:
[docs/07](../docs/07_velocity_excursions.md#options).
