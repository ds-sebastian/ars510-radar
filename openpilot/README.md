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

That's all: the fork is detected, the `fused` profile is installed, and an install made with an older patch-based
version of this installer is replaced automatically. `--profile raw` installs the unfiltered decode for comparison
([docs/11](../docs/11_profiles_compared.md) compares them); the removed `anchor` and `steady` names install `fused`.

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
| `fused` (default) | `FUSED_CONFIG`: `raw` + range fusion + one Kalman speed filter fusing the object list, the ACC target (0x235) and the summaries (0x192/0x194) by the radar's own uncertainty. Fewest false brakes ([docs/11](../docs/11_profiles_compared.md)) |
| `raw` | `BASE_CONFIG`: the unfiltered radar decode (not vision-only, not stock openpilot) with only what radard needs, for research and comparison. Velocity excursions reach the planner unfiltered (three times the hard false braking of `fused`); the installer prints a warning. `stock` and `default` are its older names |
| `openpilot` | the upstream version ([`upstream/ars510_radar.py`](../upstream/ars510_radar.py)), installed as `opendbc/car/toyota/ars510_upstream.py`: one file in opendbc style with `fused`'s filter minus the summaries, points with `trackId` / `dRel` / `yRel` / `vRel` only (`upstream` is its older name) |
| `colored` | experimental: `COLORED_CONFIG`, `fused` with a colored-noise (bias) state for the object list; road tests only ([docs/12](../docs/12_kalman_filter.md#kalman-variants-tested)) |

Older names still work and print what they select: `anchor` / `steady` → `fused`, `stock` / `default` → `raw`,
`upstream` → `openpilot`. Note that `--profile default` means `raw`; leave `--profile` out for the recommended `fused`.

## What gets installed

| file | installed as | what |
|---|---|---|
| `../ars510/` | `opendbc/car/toyota/ars510/` | the decoder package, unchanged |
| `ars510_radar_interface.py` | `opendbc/car/toyota/ars510_radar_interface.py` | `Ars510RadarInterface` (raw CAN → RadarData) and the hook |
| `../upstream/ars510_radar.py` | `opendbc/car/toyota/ars510_upstream.py` | the upstream version (used by `--profile openpilot`) |
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
  StarPilot's radard, an earlier tuned profile gave a 0.24 s head start over StarPilot's own vision-only, with 1.8
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

## Troubleshooting

| symptom | what to check |
|---|---|
| `no opendbc/car/toyota/interface.py under …` | pass the openpilot checkout (`/data/openpilot`) or its `opendbc_repo` directly |
| leads are still vision-only after installing | reboot (a new ignition cycle is not enough); `--check` must show `hook … present`; the radar's firmware must be `8821F0R03100`, or bus 1 must carry 0x80 and 0x85 (`tools/decode_log.py` on a log from the car) |
| radar leads disappeared after a fork update | the update reset `/data/openpilot`; run the installer again and reboot |
| `radarUnavailableTemporary` alerts | the radar stopped sending its object list for more than 0.5 s; check the wiring / harness; openpilot longitudinal's radar disable does not stop the object list on `8821F0R03100` ([docs/01](../docs/01_radar_bus.md#openpilots-radar-disable)), so a log showing 0x80 stopping after the radar's `68 01` response points to other firmware ([docs/08](../docs/08_openpilot_integration.md#checking-a-new-install-on-the-car)) |
| the lead chevron sits on the hood when stopped close behind a car | a UI quirk: the chevron is drawn from the radar distance in the camera frame; driving is not affected |
| braking feels wrong | flag the moment with the bookmark button and open a [drive report](https://github.com/ds-sebastian/ars510-radar/issues/new?template=drive_report.yml); `--uninstall` returns to vision only |

## Optional radard patch

[`radard_vision_fusion.patch`](radard_vision_fusion.patch) is **not** applied by `install.py`. It rewrites radard's
track filter in covariance form (identical output for radar-only tracks) and fuses the vision lead's speed into the
matched radar track. Apply it from an openpilot checkout with `git apply`. Effect and settings:
[docs/07](../docs/12_kalman_filter.md#other-approaches-tested).
