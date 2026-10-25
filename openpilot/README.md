# Installing the ARS510 integration

One installer for openpilot and its forks (sunnypilot, StarPilot, CarrotPilot and other trees with openpilot's `opendbc_repo`
layout). It adds the decoder and appends one marked block to the end of Toyota's `interface.py`; the fork's files stay as
shipped apart from that block, and card, radard and the planner run as shipped. How it works and what it does on the road:
[docs/08](../docs/08_openpilot_integration.md).

## Install on a comma device

```bash
cd /data && git clone https://github.com/ds-sebastian/ars510-radar
python /data/ars510-radar/openpilot/install.py /data/openpilot
sudo reboot
```

The fork is detected, the `acc` profile is installed, and an install made with an older patch-based
version of this installer is replaced automatically. `--profile acc_summaries` installs the alternative for forks
([docs/11](../docs/11_profiles_compared.md) compares them).

Running the installer again without `--profile` keeps the profile already installed, so an update script can call it
as is. It looks in the installed interface file, and when a fork update has removed the install, in the record this
checkout keeps of its last install into the same path (`openpilot/.installed_profiles.json`, ignored by git). A first
install gets `acc`, and so does a reinstall over a profile that is no longer installable. The installer prints one line with the active profile and why (`requested with --profile`,
`kept from the existing install`, `kept from the last install into this path`, or `the default`), and a note when
`--profile` changes it. `--check` shows what a plain re-run would install; `--uninstall` forgets the record.

**Reboot after installing.** The manager pre-imports its Python processes, so a new ignition cycle alone keeps the old
Toyota modules. On the first drive after the reboot, `radarUnavailable` is false and leads are radar-backed.

```bash
python /data/ars510-radar/openpilot/install.py /data/openpilot --check        # report state (read-only), incl. whether the install matches this checkout
python /data/ars510-radar/openpilot/install.py /data/openpilot --uninstall    # remove everything it added
cd /data/ars510-radar && git pull && python openpilot/install.py /data/openpilot   # update (keeps the profile), then reboot
```

A fork update resets `/data/openpilot`: run the installer again after updating (and turn off automatic updates
while testing). The re-run reinstalls the profile you had.

| profile | config |
|---|---|
| `acc` (default) | the radar's ACC target alone as one point, the upstream proposal, open as [commaai/opendbc#3860](https://github.com/commaai/opendbc/pull/3860) ([`upstream/ars510_acc_target.py`](../upstream/ars510_acc_target.py) with [`toyota_tss2_ars510.dbc`](../upstream/toyota_tss2_ars510.dbc), opendbc's CANParser, 45 code lines): the car Toyota's own ACC follows, published as soon as the radar picks it; every other car comes from the camera ([docs/17](../docs/17_upstream.md#towards-an-upstream-comma-interface)) |
| `acc_summaries` | `acc` plus up to two more cars from the radar's own tracker ([`standalone/ars510_acc_summaries.py`](standalone/ars510_acc_summaries.py), 53 code lines): the target summaries 0x191-0x194 within 40 m, the ACC car published once, speed from a Kalman filter on each summary's range over the radar's clock. Aimed at forks: braking as `acc` over all replays, cut-ins radar-backed earlier, about 30 engaged road minutes so far ([docs/11](../docs/11_profiles_compared.md#acc_summaries-acc-plus-the-summary-cars)) |

The object-list profiles of earlier versions (`fused`, `openpilot`, `raw`, `shared_speed`, `shared_range`, and the older
names `anchor`, `steady`, `colored`, `stock`, `default`, `upstream`) are not installable: they publish the object list's
speeds, whose excursions (mostly false closings beyond 40 m, [docs/07](../docs/07_velocity_excursions.md)) reach the
planner. On the second car's 38 latest held-out drives `fused` added 2.05 s of unnecessary braking per moving hour over
`acc`, including a −3.31 m/s² request for a list track at 54 m whose closing speed read 23.7 m/s at a constant range
([`second_car_batch3.json`](../data/analysis/summaries/second_car_batch3.json)). `--profile` with one of those names,
or a reinstall over one, installs `acc` and prints a note; the files older versions installed for them
(`ars510_upstream.py`, `ars510_shared_{speed,range}.py`) are removed. The object-list filter stays in `ars510/` as
research code ([docs/12](../docs/12_kalman_filter.md)).

## What gets installed

| file | installed as | what |
|---|---|---|
| `../ars510/` | `opendbc/car/toyota/ars510/` | the decoder package, unchanged (the interface uses its constants, PCS alarm and fault flag) |
| `ars510_radar_interface.py` | `opendbc/car/toyota/ars510_radar_interface.py` | `Ars510RadarInterface` (dispatch to the profile file, the radar's fault flag) and the hook |
| `../upstream/ars510_acc_target.py` | `opendbc/car/toyota/ars510_acc_target.py` | the ACC target alone (`--profile acc`) |
| `standalone/ars510_acc_summaries.py` | `opendbc/car/toyota/ars510_acc_summaries.py` | the ACC target plus the summary cars (`--profile acc_summaries`) |
| `../upstream/toyota_tss2_ars510.dbc` | `opendbc/dbc/ars510_acc_target.dbc` | its DBC: the ACC target messages, under a name of its own so opendbc's `toyota_tss2_ars510.dbc` ([commaai/opendbc#3860](https://github.com/commaai/opendbc/pull/3860)) stays as shipped |
| 8-line block | end of `opendbc/car/toyota/interface.py` | `CarInterface = hook_car_interface(CarInterface)`; on any error it logs and leaves Toyota as shipped |

The DBCs in [`../dbc/`](../dbc) are for inspecting the radar in Cabana on a PC; the decoder reassembles the 106-frame
record in Python. The only DBC installed on the device is `ars510_acc_target.dbc`, which the `acc` profiles parse.
The installer never overwrites or removes a file the fork's git tracks; if the fork ships a file under one of the
names above, the install stops before changing anything (`--check` lists it).

The hook wraps the fork's own Toyota `CarInterface` after it is defined:
- **detection** in `_get_params`: a radar-ACC RAV4 2022 or 2023-25 gets `radarUnavailable = False` from the car model
  (both radar firmwares in openpilot's fingerprints are the ARS510, [docs/01](../docs/01_radar_bus.md#radar-firmware))
  when the radar's early bus-1 frames (0x190 / 0x191 / 0x235 …, from 0.2 s after power-up) are in the fingerprint;
  without them the car is radarless with vision leads instead of a radar that never reports, also when opendbc
  declares the radar itself;
  the C-HR and Yaris are enabled for testing (same radar frames, [docs/01](../docs/01_radar_bus.md#c-hr-and-yaris)), the
  Yaris always with `acc` because it sends no 0xB4 wheel speed;
- **tracks** through `CarInterface.RadarInterface`: `Ars510RadarInterface` for that car, the fork's own
  RadarInterface for every other car. Extra constructor arguments (sunnypilot's `CP_SP`) pass through, and forks
  whose RadarPoint still has `aRel` / `yvRel` / `measured` get those fields filled;
- **the radar's PCS alarm** in `update`: the alarm bit on bus 1 (0x100) sets `carState.stockFcw`. openpilot logs it
  but shows no alert for `stockFcw` ([docs/15](../docs/15_aeb_pcs.md#where-a-relay-stands-for-developers)). Upstream the
  same lives in Toyota's carstate in [commaai/opendbc#3860](https://github.com/commaai/opendbc/pull/3860).

The install leaves `ToyotaFlags` as the fork defines it.

Fork notes:
- **StarPilot** runs its own radard (lateral gate when matching, match hysteresis) and planner (a
  lead-acceleration extrapolation that holds `aLeadK` unchanged above 35 mph) and
  enables its radar extras (adjacent-lane leads, "Force Stop" hint, radar UI) once radar is available.
- **sunnypilot** carries `aRel` and `yvRel`: the radar's filtered acceleration and its lateral velocity, the latter
  using the Toyota 0x24 yaw rate.

## Test on a PC first

```bash
OP=~/openpilot                                          # any fork checkout with a .venv (tools/op.sh setup)
cp -r $OP/opendbc_repo /tmp/opendbc_ars510
python openpilot/install.py /tmp/opendbc_ars510
$OP/.venv/bin/python openpilot/check_integration.py --opendbc /tmp/opendbc_ars510
```

`check_integration.py` runs radar frames through the installed Toyota interface the way card does:
- detection: cold start by firmware, fallback by bus 1, other cars untouched;
- the PCS alarm (0x100) as `stockFcw`;
- `acc`: the bundled ACC-target sample, one point per radar cycle, units and sign, timeout and recovery, and
  `radarUnavailableTemporary` while the radar's 0x196 fault flag is held;
- `acc_summaries`: synthetic ACC target and summary frames, the ACC car published once, summary cars beyond 40 m left
  out, timeout and recovery.

On the openpilot 10b9e73 used for replays it passes 20 checks with `acc` and 17 with `acc_summaries` (that tree has no
optional RadarPoint fields). To replay your own drives stock vs installed, see
[docs/09](../docs/09_tools_and_data.md#replay-your-drives-through-openpilot).

## Troubleshooting

| symptom | what to check |
|---|---|
| `expected opendbc/car/toyota/interface.py under …` | pass the openpilot checkout (`/data/openpilot`) or its `opendbc_repo` directly |
| leads are still vision-only after installing | reboot (a full reboot reloads the Toyota modules); `--check` must show `hook … present`; the car must fingerprint as `TOYOTA_RAV4_TSS2_2022`, `TOYOTA_RAV4_TSS2_2023`, `TOYOTA_CHR_TSS2` or `TOYOTA_YARIS` (a radar-ACC Toyota) |
| `radarUnavailable` true on a RAV4 2022 / 2023 with the hook present | `--check` must show `installed files: match this checkout`; an install from before the car-model detection needed the radar firmware in `carFw` or 0x80 / 0x85 on bus 1 during fingerprinting, and a car picked manually (CarrotPilot's car selection, `FINGERPRINT`) at a cold start has neither: `git pull`, install again, reboot |
| radar leads disappeared after a fork update | the update reset `/data/openpilot`; run the installer again and reboot |
| `radarUnavailableTemporary` alerts | the radar stopped sending its ACC-target frames for more than 0.5 s, or holds its own fault flag (0x196, a blocked radar); check the wiring / harness and the radar cover; openpilot longitudinal's radar disable keeps bus 1 running on `8821F0R03100` ([docs/01](../docs/01_radar_bus.md#openpilots-radar-disable)), so a log showing bus 1 stopping after the radar's `68 01` response points to other firmware or hardware in the radar line ([docs/08](../docs/08_openpilot_integration.md#checking-a-new-install-on-the-car)) |
| the lead chevron sits on the hood when stopped close behind a car | a UI quirk: the chevron is drawn from the radar distance in the camera frame; driving uses the measured distance |
| braking feels wrong | flag the moment with the bookmark button and open a [drive report](https://github.com/ds-sebastian/ars510-radar/issues/new?template=drive_report.yml); `--uninstall` returns to vision only |

## Optional radard patch

[`radard_vision_fusion.patch`](radard_vision_fusion.patch) is a separate radard change for forks that want it; apply it
from an openpilot checkout with `git apply` (`install.py` leaves radard as shipped). It rewrites radard's track filter
in covariance form (identical output for radar-only tracks) and fuses the vision lead's speed into the matched radar
track. Replayed on the 20 held-out drives with the unfiltered decode, it brought the planner's requests closer to the
driver's acceleration (pre-registered driver-agreement error −0.004) at a mean 0.085 s later reaction
([`radard_vision_fusion.json`](../data/analysis/summaries/radard_vision_fusion.json)).
