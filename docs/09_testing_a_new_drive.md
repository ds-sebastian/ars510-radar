# 09. Testing on your own car and contributing

## 1. Confirm you have the same radar

- FW query: the forward radar at 0x750 subaddress 0x0f answers `8821F0R03100`. The version is in your route's `carParams.carFw`.
- Bus 1 carries 0x80 at ~1760 frames/s and 0x85 at ~350 frames/s. The first 0x80 frame of each record starts `12 E4`.
- `python tools/decode_log.py your_rlog --profile raw` should report **zero CRC failures**.

If your firmware differs, the bus map may still hold. Please report it either way ([how to contribute](#5-what-to-send-back)).

## 2. Look at it

- Decode to CSV: `python tools/decode_log.py rlog.zst -o points.csv`. This needs openpilot's `LogReader` on `PYTHONPATH` for rlog input.
- Cabana: [cabana.md](cabana.md).
- Sanity checks anyone can do:
  - At standstill behind a car, dRel should match the gap and vRel ≈ 0.
  - Approaching a stopped car, `v_long_ground` should be ≈ 0 and vRel ≈ −v_ego.
  - A car passing on your left should have positive yRel.

## 3. Replay through openpilot

`tools/openpilot_replay/replay_radard.py` runs openpilot's real radard and longitudinal planner over your logs. It runs three pipelines side by side: vision only, raw radar, and `OPENPILOT_CONFIG`.

```bash
OP=/path/to/openpilot          # a checkout matching (or close to) the version you drive
# only if the checkout has never been built with scons:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$OP $OP/.venv/bin/python tools/openpilot_replay/build_long_mpc_shadow.py --openpilot $OP --out op_shadow
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$OP:$OP/opendbc_repo:. $OP/.venv/bin/python tools/openpilot_replay/replay_radard.py \
    --openpilot $OP --mpc-shadow op_shadow --force-engaged --out replay_out  route--0/rlog route--1/rlog ...
```

`summary.json` lists FCW ticks per profile and every **native-only braking episode**, where radar makes openpilot brake (≤ −1 m/s²) while vision alone would not (≥ −0.3). Classify each episode against the video:
- **confirmed:** the lead really was closing;
- **overstated:** closing, but milder than radar said;
- **contradicted:** the lead was steady or opening.

The contradicted rate per engaged hour is the number that decides whether this radar can ever be trusted for braking. Replay is open-loop, so it cannot tell you what the car would have done.

### End to end, with the installed integration, and watching it

`tools/openpilot_replay/process_replay_ars510.py` tests the real install rather than the decoder alone. It runs
openpilot's own process_replay (`card` → `radard` → `plannerd`) twice: once with a stock opendbc, once with a copy
that has [`openpilot/`](../openpilot) installed. Then it compares:
- detection;
- radarTracks rate, gaps and errors;
- radar-matched leads;
- FCW;
- braking only in one of the two runs.

```bash
cp -r $OP/opendbc_repo /tmp/opendbc_ars510 && python openpilot/install.py /tmp/opendbc_ars510
PY=$OP/.venv/bin/python
$PY tools/openpilot_replay/process_replay_ars510.py run --openpilot $OP --opendbc $OP/opendbc_repo --mpc-shadow op_shadow \
    --label stock  --out pr --save-logs pr/logs route--0/rlog route--1/rlog
$PY tools/openpilot_replay/process_replay_ars510.py run --openpilot $OP --opendbc /tmp/opendbc_ars510 --mpc-shadow op_shadow \
    --label ars510 --out pr --save-logs pr/logs route--0/rlog route--1/rlog
$PY tools/openpilot_replay/process_replay_ars510.py compare --out pr stock ars510
```

To **watch** an episode, render openpilot's UI over the road video from the saved logs. It shows the planned path
and the lead chevron from the replayed radarState. The time window is in seconds from the start of the route:

```bash
PYTHONPATH=$OP $PY $OP/openpilot/tools/clip/run.py "a510a510a510a510/<route>/<start>/<end>" -d pr/logs/ars510 --big -o ars510.mp4
```

To **plot** signals, open a saved `rlog.zst` in PlotJuggler (`$OP/openpilot/tools/plotjuggler/juggle.py`), for
example:
- `longitudinalPlan.aTarget`, the acceleration openpilot would request;
- `radarState.leadOne.dRel` and `.vRel`;
- `radarTracks`.

Replay is open-loop and does not run controlsd with openpilot longitudinal. So "gas / brake" is the planner's
requested acceleration, not an actuator command. Steering is unaffected by radar.

- System ffmpeg 8 and newer dropped `-vsync`, which openpilot's FrameReader still passes. If clip fails in ffmpeg,
  put [`tools/openpilot_replay/ffmpeg`](../tools/openpilot_replay/ffmpeg) first on PATH (`PATH=$PWD/tools/openpilot_replay:$PATH`). It turns `-vsync 0` into the output option `-fps_mode passthrough`.
- The viewer logs carry a few documented display fixes; see the script docstring.

## 4. Pre-register before you look

Some tests in this repo were pre-registered; others were exploratory or later follow-ups. Do not treat previously inspected B/C data as an untouched holdout. Before a new confirmatory test, write:

1. the rule, with every parameter frozen;
2. the pass criteria, for example:
   - "contradicted episodes fall ≥ 50%";
   - "≥ 80% of confirmed closings still brake within ±1 s";
   - "no early-warning event delayed > 0.5 s";
3. which drives are held out.

Then run once and report pass or fail as is. A failed pre-registered test is a useful result. Add it to [08](08_dead_ends.md).

## 5. What to send back

These are useful, but review them for identifying information before sharing:

- **Radar FW version**, and whether 0x80 / 0x85 look identical.
- Whether **0x500** (6 bytes) and **0x502** bytes 4–7 differ between units. These may contain serial/calibration identifiers; do not publish full values without deciding that disclosure is acceptable.
- `replay_radard.py` `summary.json` counts per engaged hour, with your classification of episodes.
- Short CAN excerpts of interesting events (an explicit radar-address allowlist plus bus 0 0xB4), with times rebased to 0, like `data/sample/`. Raw logs can contain identifiers and other private channels; a CAN-only subset is not automatically anonymous.
  - A clear vRel excursion.
  - A stopped-car approach.
  - An occlusion.

Please don't post route IDs, dongle IDs, GPS or video unless you mean to.

## 6. Physics tests without another car or openpilot changes

Start with existing video and ego motion, not another fitted teacher. Identify stationary vehicles from video/odometry independently of radar range, retain contradictory radar samples, and test ground speed against zero and longitudinal relative speed against -ego speed on straight approaches. The newer test already weakens the old near-range claim ([13](13_evidence_review.md)); do not repeat it unchanged. Separate a genuinely stationary target from a queue still rolling to a stop, and check timing under braking.

Stationary targets constrain the ground-velocity zero, not its multiplicative scale. Nonzero-motion windows plus an independently checked distance scale are needed for scale. Body-frame derivatives on curves require yaw and sensor lever-arm terms. Reserve event windows before fitting any delay or correction.

## 7. Optional instrumented reference

A **two-car drive**: the lead car carries its own logging device (a second comma device or a GPS logger), and the ARS510 car follows at 20–100 m through:
- steady following;
- closing;
- opening;
- lane changes.

Synchronized, accuracy-characterized lead/ego logging can provide a stronger independent reference. Ordinary consumer GPS subtraction is not exact range or velocity truth: timing, antenna offsets, heading and multipath need an error budget. With that established, it can test:
- whether excursions are radar errors or real target behaviour;
- native velocity accuracy in steady far following, the one band where it loses to zero;
- far-range dRel scale.

Surveyed lateral offsets would also constrain the lateral scale. This is optional, not a prerequisite for further work on the existing routes.
