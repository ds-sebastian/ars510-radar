# 09. Tools, data, and testing on your own car

## Tools

| tool | what it does |
|---|---|
| [`tools/decode_log.py`](../tools/decode_log.py) | rlog / qlog / CAN CSV → one CSV row per published object-list point (`raw`, `fused` or `all-tracks`) |
| [`tools/build_cabana_route.py`](../tools/build_cabana_route.py) | appends reassembled objects to your rlogs on a virtual bus, for Cabana; `--dbc-only` regenerates `dbc/ars510_objects_vbus.dbc` |
| [`tools/openpilot_replay/process_replay_ars510.py`](../tools/openpilot_replay/process_replay_ars510.py) | openpilot's own process_replay (card → radard → plannerd), stock vs installed integration |
| [`tools/openpilot_replay/replay_radard.py`](../tools/openpilot_replay/replay_radard.py) | radard + planner only, several object-list profiles (`all-tracks`, `raw`, `fused`, `fused_no_trackers`) side by side |
| [`tools/fork_lead/`](../tools/fork_lead) | runs a fork's own radard and MPC lead handling on your drives: `prepare_route.py`, `fork_replay.py`, `fork_report.py`, `fork_synth.py` ([below](#compare-forks)) |
| [`tools/check_structure.py`](../tools/check_structure.py) | CRC, slot-index and allocation-count checks on the bundled samples |
| [`tools/make_profile_figures.py`](../tools/make_profile_figures.py) | runs the profiles on the bundled samples: the examples in [12](12_kalman_filter.md); a template for plotting your own idea |
| [`tools/make_analysis_figures.py`](../tools/make_analysis_figures.py), [`make_fused_figures.py`](../tools/make_fused_figures.py), [`make_guide_figures.py`](../tools/make_guide_figures.py), [`make_jitter_figures.py`](../tools/make_jitter_figures.py), [`make_figures.py`](../tools/make_figures.py) | rebuild the other charts in `docs/` |
| [`tools/compute_stats.py`](../tools/compute_stats.py) | descriptive statistics of the dataset → `data/analysis/stats.json` |

### Decode a log

```bash
python tools/decode_log.py data/sample/highway_following_30s.csv.gz -o points.csv
python tools/decode_log.py rlog.zst -o points.csv            # needs openpilot's LogReader on PYTHONPATH
python tools/decode_log.py rlog.zst --profile all-tracks     # every track from age 1, with the radar's own IDs; reports CRC failures
python tools/decode_log.py data/sample/highway_acc_anchor_24s.csv.gz --profile fused    # fused, raw (default) or all-tracks
```

`decode_log.py` runs the object-list decoder. The `acc` profile publishes the radar's ACC target frames (0x235 / 0x237), which
[`tools/fork_lead/prepare_route.py`](../tools/fork_lead/prepare_route.py) extracts next to the `raw` and `fused` points.

### Cabana

The object list is a multi-frame record, so Cabana needs it reassembled first. `build_cabana_route.py` copies your log and appends each record's occupied slots as CAN-FD-sized messages on **virtual bus 10**, byte for
byte, so the DBC bit positions are the real slot bit positions.

```bash
OP=/path/to/openpilot
PYTHONPATH=$OP:$OP/opendbc_repo $OP/.venv/bin/python tools/build_cabana_route.py /path/to/<route>--12 /path/to/<route>--13 --out cabana_out
$OP/openpilot/tools/cabana/cabana --data_dir cabana_out/route "<route>" --dbc dbc/ars510_objects_vbus.dbc
```

| bus-10 address | message | content |
|---|---|---|
| 0x700-0x713 | `ARS510_OBJ_00..19` | raw slot bytes with every field of [03](03_slot_fields.md) |
| 0x720-0x733 | `ARS510_OBJ_xx_DERIVED` | values the interface computes: VREL, V_EGO_0xB4, TRACK_ID_RAW, TRACK_ID_OP, PUBLISHED_OP, SETTLED, DREL_FUSED, VREL_KALMAN |
| 0x740 / 0x741 | `ARS510_REC_HEADER` / `TRAILER` | record header; CRC32 |
| 0x760-0x76B | `ARS510_SHELL85_*` | 0x85 prefix, ten cells (with `PARAMETERS_PRESENT`), CRC |

For the raw radar bus use `dbc/ars510_radar_bus.dbc` on bus 1. Some Cabana builds only list DBCs from
`opendbc/dbc/`; copy the file there locally.

Good first plots: DREL and VREL of one slot next to the video; SCORE_CODE and STATE_CODE as a track ends;
UNK_148_8 / UNK_156_4 (lane weights) during a lane change; VLONG_OVER_GROUND of a lead you follow (≈ your speed);
UNK_112_3 (camera association) as a car you close on comes inside 45 m; UNK_115_5 (class confidence) of a new track. On
the radar bus, `ACC_TARGET_1.REL_SPEED` next to `ACC_TARGET_2.LONG_DIST` and `ACC_TARGET_3.CLASS` (the target's class)
show the radar's own ACC target.

### Replay your drives through openpilot

```bash
OP=/path/to/openpilot
cp -r $OP/opendbc_repo /tmp/opendbc_acc && python openpilot/install.py /tmp/opendbc_acc                      # acc, the default
cp -r $OP/opendbc_repo /tmp/opendbc_fused && python openpilot/install.py /tmp/opendbc_fused --profile fused  # the all-tracks alternative
PY=$OP/.venv/bin/python
PYTHONPATH=$OP $PY tools/openpilot_replay/build_long_mpc_shadow.py --openpilot $OP --out op_shadow   # once, as an alternative to the scons build
$PY tools/openpilot_replay/process_replay_ars510.py run --openpilot $OP --opendbc $OP/opendbc_repo --mpc-shadow op_shadow \
    --label vision --out pr --save-logs pr/logs route--0/rlog route--1/rlog
$PY tools/openpilot_replay/process_replay_ars510.py run --openpilot $OP --opendbc /tmp/opendbc_acc --mpc-shadow op_shadow \
    --label acc --out pr --save-logs pr/logs route--0/rlog route--1/rlog
$PY tools/openpilot_replay/process_replay_ars510.py run --openpilot $OP --opendbc /tmp/opendbc_fused --mpc-shadow op_shadow \
    --label fused --out pr --save-logs pr/logs route--0/rlog route--1/rlog
$PY tools/openpilot_replay/process_replay_ars510.py compare --out pr vision acc      # each compare takes two labels
$PY tools/openpilot_replay/process_replay_ars510.py compare --out pr vision fused
```

The comparison lists detection, radarTracks rate and gaps, radar-matched leads, FCW and braking episodes that only one
run has. To **watch** an episode, render openpilot's UI over the road video from the saved logs:

```bash
PYTHONPATH=$OP $PY $OP/openpilot/tools/clip/run.py "a510a510a510a510/<route>/<start>/<end>" -d pr/logs/acc --big -o acc.mp4
```

To **plot**, open a saved `rlog.zst` in PlotJuggler: `longitudinalPlan.aTarget`, `radarState.leadOne.dRel` / `.vRel`,
`radarTracks`. Replay is open loop: ego motion is as recorded, and "braking" means the planner's requested
acceleration. With ffmpeg 8+, put [`tools/openpilot_replay/ffmpeg`](../tools/openpilot_replay/ffmpeg) first on `PATH`
when clip rendering reports a `-vsync` error.

Here `vision` is unmodified openpilot (vision-only leads on this car), `acc` the default install and `fused` the all-tracks
install; another profile goes into its own opendbc copy (`install.py /tmp/opendbc_raw --profile raw`).

### Compare forks

[14](14_forks.md) comes from `tools/fork_lead/`, which executes a fork's radard and `long_mpc.process_lead` unmodified
on recorded ticks (plain Python; these two are the only openpilot code). Clone the forks, then:

```bash
export PYTHONPATH=$OP                      # openpilot's LogReader, as for decode_log.py
python tools/fork_lead/prepare_route.py -o drive1 seg0/rlog.zst seg1/rlog.zst      # ticks + raw / fused / ACC-target points
python tools/fork_lead/fork_replay.py --sunnypilot ~/sunnypilot --frogpilot ~/frogpilot --starpilot ~/starpilot \
    --out replay drive1 drive2             # 4 fork configurations x 4 profiles per drive; two jobs at a time, about 2 min each
python tools/fork_lead/fork_report.py replay drive1 drive2 --json fork_lead_handling.json
python tools/fork_lead/fork_synth.py --sunnypilot ~/sunnypilot --frogpilot ~/frogpilot --starpilot ~/starpilot --template drive1
```

Pass the forks you have. The result is a proxy for the planner (a demand number on the lead trajectory each fork
gives its MPC), suited to comparing forks and profiles; the planner's own request comes from the replay above. Its tests
(`tests/test_fork_lead_tools.py`) run on this repo alone.

## Developing and testing a change

A change to how points are published (a new filter, guard or decoded field) goes through these steps; each one is cheap
until the last.

1. **See it on the samples.** `data/sample/` has three real captures: steady following, a short excursion, and an
   excursion with the radar's ACC target. Copy a panel of [`tools/make_profile_figures.py`](../tools/make_profile_figures.py)
   and plot your idea against the current profile; synthetic CAN builds events outside the samples the same way.
2. **Add it as an option, off by default.** A field in `NativeInterfaceConfig` ([`ars510/interface.py`](../ars510/interface.py))
   with a comment saying what it fixes, plus a test in `tests/test_interface.py` built from synthetic slots
   (`encode_slot`), including a case where it must leave the track alone.
3. **Say what you expect before replaying.** Write down which events it should change and which it must leave alone.
   Tune on other drives than the one that motivated it.
4. **Replay against the driver.** Run openpilot's card → radard → planner on held-out drives with the profile you change
   (`acc` or `fused`) and with your variant, and report the gates used throughout [12](12_kalman_filter.md):

   | gate | meaning |
   |---|---|
   | hard radar-only ticks | planner ≤ −2 m/s² while the vision-only replay asks ≥ −0.5 m/s²; stays at or below the baseline |
   | radar-only episodes | ≥ 0.3 s at ≤ −1 m/s² while vision-only asks ≥ −0.3; stays at or below the baseline |
   | braking onset | mean time of the first ≤ −0.5 m/s² request relative to each driver brake; stays within 0.03 s of the baseline |
   | early braking | share of driver brakes where the planner reached ≤ −1 m/s² between 3 s before and 0.5 s after the driver started braking; stays at the baseline, or the drop has a stated reason (the path gate and 0.4 x match cost 1.8 points, [12](12_kalman_filter.md#path-gate)) |
   | per event | every driver brake is answered within 0.15 s of the baseline, kept, and as strong when hard |

5. **Open a PR with the numbers**, the figure, and the drives used (anonymised). Changes are merged on held-out
   evidence.

## Data in this repo

[`data/README.md`](../data/README.md) describes every file. In short:

- **`data/sample/`**: three 24-30 s real CAN captures (radar frames plus 0xB4 ego speed, times rebased to 0), used by the
  tests: steady highway following, the velocity excursion of [07](07_velocity_excursions.md), and an excursion with
  the radar's ACC target.
- **`data/analysis/`**: an anonymised dataset from three drives (A, B, C; 88 minutes): every decoded object sample
  with all raw fields, 90k radar-camera pairs, ground-contact and lateral camera pairs, brake-event windows, fault
  injection results, and summary JSONs behind the numbers in these docs.
- **`data/reference/slot_bit_map.json`**: per-bit statistics of the 0x80 slot, header and 0x85 record.

The evidence comes mainly from the owner's RAV4 (TSS2, 2022), logged with openpilot, with drives U1-U3 from a second,
unfiltered RAV4 and an 8.8 h replay set from the issue #66 tester's 2025 RAV4 Hybrid (S#, [12](12_kalman_filter.md#on-a-second-car)). Drives are named by role (A development,
B city, C highway, D1-D4 closed-loop drives, E the ACC sample, O1-O4 and O6-O7 owner road drives, O5 a parked owner test, U1-U3 a second
unfiltered RAV4, S# the tester's drives); each drive carries its letter and times relative to an event. A few
camera stills are included, with licence plates and place names blurred.

## Testing on your own car

Choose a session from [16: Routes and tests](16_routes_and_tests.md) for step-by-step capture procedures,
equipment, required references and interpretation limits. [15](15_aeb_pcs.md#recording-pcs--aeb-events) covers PCS event recording.

1. **Same radar?** The forward radar at 0x750 / 0x0f answers `8821F0R03100` (in your route's `carParams.carFw`). Bus 1
   carries 0x80 at ~1,760 frames/s and 0x85 at ~350 frames/s; `decode_log.py --profile all-tracks` should report zero CRC
   failures.
2. **Sanity checks:** stopped behind a car, dRel matches the gap and vRel ≈ 0; approaching a stopped car,
   `v_long_ground` ≈ 0; a car passing on your left has positive yRel and left-lane weight.
3. **Replay** a few drives as above and look at the braking episodes only one run has.
4. **Install** with [`openpilot/install.py`](../openpilot/README.md#install-on-a-comma-device) and follow the on-car check list in
   [08](08_openpilot_integration.md#checking-a-new-install-on-the-car).

### What to send back

- Your radar FW version, and whether 0x80 / 0x85 look the same.
- Whether 0x500 and 0x502 bytes 4-7 differ from other units (they may be unit identifiers: share with care).
- Replay braking-episode counts per hour, with your classification against the video (real closing / overstated /
  lead steady or opening).
- Short CAN excerpts of interesting events (radar addresses plus bus-0 0xB4, times rebased to 0, like `data/sample/`):
  a clear velocity excursion, a stopped-car approach, a lane change.

Keep route IDs, dongle IDs, GPS and video private; share them when you mean to.
