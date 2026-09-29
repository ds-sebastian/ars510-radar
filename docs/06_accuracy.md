# 06. Accuracy: how well the object fields match the world

Three drives carry the accuracy measurements: **A** (development, 26 min mixed), **B** (held out, 43 min city, often
wet or at night, hilly) and **C** (held out, 24 min highway). The references each measure something different:

| reference | what it gives |
|---|---|
| camera ground contact | absolute distance at 5-25 m: YOLO box bottom projected on a flat road with the log's calibration |
| camera box growth | closing speed from image expansion over 2 s, `−(dRel + 1.52) · d ln(h)/dt` (metric scale from radar range) |
| camera size ratio | scale-free range change: the box-height ratio over 1.5 s equals the inverse range ratio |
| ego odometry | wheel speed, GPS, gyro: velocity scale, and exact vRel of stopped targets (−v_ego) |
| openpilot's vision model | lateral side, far-range distance, lead speed |

## At a glance

| quantity | result |
|---|---|
| **dRel** scale and zero, 5-25 m | slope 1.001 / 0.992 / 0.993 against camera ground contact; zero within 0.2 m on flat roads |
| **dRel** far range | median residual 3.7 m at 60-100 m and 5.1 m at 100-150 m against camera/model consensus |
| **dRel** record to record | walks by about 3% of range (see range walks below) |
| **yRel** side | correct on 97.9-99.3% of off-centre targets against the camera, 99.3% against the vision model |
| **yRel** scale | 1/64 m per code, ±10% (lane peaks 62.8-67.3 codes/m, camera 69-73) |
| **velocity** zero and scale | zero at code 510.5; 0.150 / 0.149 / 0.153 m/s per code from the radar's own range slope with GPS ego speed |
| **vRel** vs camera | far better than zero or range differencing at every range (table below) |
| **vRel**, stopped targets 5-30 m | RMS 0.54 m/s on settled tracks |
| **trackId** | no ID ever in two slots; 77 of 87 camera-checked tracks within 60 m keep one camera identity ≥ 95% of their life |

## Distance

![range ground contact](img/analysis/range_ground_contact.png)

- **Scale 1/16 m.** Closing rate over relative speed gives 15.93 / 16.01 codes per metre on two calibration routes;
  camera ground contact gives slope 0.99-1.00 on all three drives.
- **Zero at code 160 (−10 m).** Camera ground contact puts it within 0.2 m on A and C; hilly drive B reads +0.7 m,
  which a 0.25° camera-pitch error explains. The radar's origin matches openpilot's `RADAR_TO_CAMERA = 1.52 m`.
- **Far range** (drive A, camera box scale averaged with the vision model where they agree): median absolute residual
  3.7 m at 60-100 m (distance ratio 1.017) and 5.1 m at 100-150 m (ratio 0.979).

## Lateral

![lane peaks](img/analysis/lateral_lane_peaks.png)

- **Left positive, Cartesian.** Codes per metre stay constant across range, and ego-lane objects stay within 0.1 m of
  centre from 15 to 130 m on straight road.
- **Scale 1/64 m, ±10%.** Adjacent-lane peaks at highway speed give 63.9 / 67.3 / 62.8 codes per metre for 3.66 m
  lanes; camera outer box edges give 68.9 / 69.7 / 72.8. A surveyed offset would pin it.

![lateral scale](img/analysis/lateral_scale_camera.png)

## Velocity

- **Over ground.** See [03](03_slot_fields.md#kinematics).
- **Zero 510.5.** With ego and target stopped, codes pile on 510 and 511 (weighted means 510.49 / 510.40 / 510.20).

  ![standstill codes](img/analysis/standstill_codes.png)

- **Scale 0.15 m/s per code.** Regressing the code on the radar's own 8 s range slope plus GPS ego speed gives
  0.1504 / 0.1487 / 0.1530 (every 90% CI contains 0.15). Against the ACC target's speed (0x235) the slope is
  0.99 / 1.02 at 40-80 m.
- **Ego reference.** Toyota 0xB4 reads about 1.5% below GPS and wheel speed. With 0xB4 as ego speed, steady following
  fits 0.149, so `OPENPILOT_CONFIG` uses `vground_scale = 0.149 / 0.15`. The best alignment between radar velocity and
  ego speed is +0.05-0.1 s.
- **Against the camera** (closing speed from box growth over 2 s, all camera-paired samples):

  | drive | band | native vRel | constant 0 | 1 s range derivative |
  |---|---|---|---|---|
  | A | 3-30 / 30-60 / 60-100 m | **0.23** / **1.38** / **4.65** | 2.34 / 4.40 / 10.6 | 5.6 / 16.5 / 42.6 |
  | B | same | **0.66** / **3.90** / **24.3** | 5.79 / 10.2 / 34.2 | 4.6 / 18.2 / 85.7 |
  | C | same | **0.38** / **1.63** / **7.13** | 5.09 / 2.51 / 12.0 | 10.5 / 22.1 / 72.9 |

  *Mean squared difference, (m/s)².*

  ![vrel mse](img/analysis/vrel_mse_baselines.png)

  ![vrel vs camera](img/analysis/vrel_vs_camera.png)

- **Random error, by range.** A three-cornered-hat split of radar, camera and range-slope disagreements gives the
  radar's velocity scatter as 0.35-0.56 m/s at 3-30 m, 1.0-1.4 m/s at 30-60 m and 1.6-2.9 m/s at 60-100 m
  (A / B / C: 0.35 / 1.02 / 1.60, 0.56 / 1.44 / 2.90, 0.56 / 1.14 / 1.73). The error is correlated over about
  1-3 s and has heavy tails: these are the velocity excursions of [07](07_velocity_excursions.md).
- **Stopped targets.** Against targets that video and odometry show stopped at 5-30 m, settled tracks read vRel with
  RMS 0.54 m/s (B and C).
- **Timing.** On decelerating leads the radar's speed leads the camera's by 0.2-0.4 s.

## Range walks

Settled-track range jumps by metres from record to record at 40 m and beyond: about 3% of range, decorrelating within
about 5 cycles. Over 1.5 s, integrating the radar's own velocity tracks the camera's scale-free size ratio **2-4×
better** than the radar's range change does:

| drive | 5-40 m | 40-80 m | 80-160 m |
|---|---|---|---|
| A | 1.6 vs **0.5** m | 3.3 vs **1.0** m | 5.8 vs **2.1** m |
| B | 1.5 vs **0.7** m | 3.8 vs **1.9** m | 7.3 vs **5.1** m |
| C | 2.1 vs **0.6** m | 3.6 vs **1.2** m | 6.6 vs **3.0** m |

*Median disagreement, range change vs integrated vRel.*

![range walk](img/analysis/range_walk_vs_integrated_vrel.png)

![range walk on a real closing](img/shots/range_walk_brake_event.jpg)

*A real closing: the radar lead reads 24.7 m against the vision model's 36.8 m while the camera box grows only 16%.
The radar's velocity was right; its range walked. radard's 25% distance gate rejects the radar lead here.*

So velocity is the radar's strong channel and range its noisy one. Velocity-aided range (`range_fusion_gain = 0.1`)
halves the walks ([08](08_openpilot_integration.md#profiles)). Differentiating range to get velocity is 4-10× worse
than the native velocity field.

## Track identity

- **Within the radar:** a track ID is never live in two slots, and 98.3-98.9% of consecutive same-slot cycles continue
  the same age run.
- **Against the camera** (within 60 m, tracks with a long camera chain): the radar track keeps one camera identity for
  at least 95% of its life on A 21 / 21, B 28 / 36 and C 28 / 30 tracks.
- **Re-link:** `OPENPILOT_CONFIG` re-links a track the radar re-initialises within 3.5 s near its predicted position,
  so radard keeps its filter state across short losses.
