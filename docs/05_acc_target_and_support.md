# 05. The radar's own ACC target and the support messages

Besides the object list, the radar publishes the target its own ACC follows, target summaries, timing and status.
Bit numbers for the big-endian frames below treat the 8-byte frame as one big-endian integer (bit 0 = LSB of byte 7),
matching [`dbc/ars510_radar_bus.dbc`](../dbc/ars510_radar_bus.dbc) and `ars510.support`.

## The radar's own ACC target (0x235 / 0x237)

This radar is also the car's stock ACC controller. At **50 Hz**, three times the object-list rate, it publishes the
target it follows:

| field | decode | DBC signal / parser |
|---|---|---|
| closing speed | 0x235 bits 29-39: `(code − 1024) × 0.1` m/s, negative = closing | `A235_ACC_TARGET_VREL`, `parse_acc_target_vrel` |
| relative acceleration | 0x235 byte 2: `(code − 100) × 0.1` m/s², positive = opening | `A235_ACC_TARGET_AREL`, `parse_acc_target_arel` |
| lateral position | 0x237 bits 28-38: `code × 0.01667 − 16.70` m, left positive | `A237_ACC_TARGET_LAT` |
| distance, coarse | 0x237 bits 47-51: `code × 5.26 + 9.6` m | `A237_ACC_TARGET_DIST_COARSE` |
| distance, fine | 0x237 bits 39-51: 0.02 m per code for changes | `A237_ACC_TARGET_DISTANCE_CODE`, `parse_acc_target_range_code` |
| target present | 0x235 byte-1 low nibble ≠ 1 (1 = idle, bytes 2-7 `64 80 0B 24 00 FF`) | `A235_STATUS_MUX4` |

How well these hold:
- **Closing speed** correlates with the matched object's vRel at r = 0.78 / 0.82 (discovery / confirmation drives)
  and is unbiased against openpilot's vision lead (median 0.00 m/s).
- **Relative acceleration** gives the same binned curve against the derivative of the closing speed on discovery,
  confirmation and further drives (r 0.57 / 0.62 / 0.83; slope ≈ 1 at 0.1 m/s² per code), about 0.1-0.2 s behind it.
- **Fine distance:** the change of the 13-bit code times 0.0198 m equals the integrated closing speed over 2 s windows
  (confirmation median 0.0198 m/code, 565 windows). Use it for distance *changes*; its absolute offset is still to be
  pinned.
- **Lateral** correlates with the matched object at r = 0.97.

### A second witness for velocity

The ACC target is matched to an object by position. When the object list's vRel and the ACC target's closing speed
differ by more than 3 m/s, **the vision lead sides with the ACC target 86-90% of the time** (discovery 90%, n = 715;
confirmation 86%, n = 421, route-bootstrap 79-99%). Through the drive-A false closing ([07](07_velocity_excursions.md)),
the object's vRel swung to −6 m/s while the ACC target stayed at +1.3 m/s.

The ACC target comes from the radar's own ACC pipeline: it starts 0.2 s after power-up, long before openpilot
transmits, it tracks the lead rather than openpilot's commands, and it is published whether or not cruise is
engaged. Toyota may fuse its factory camera into it.

**Coverage** is the limit: the target is present on 57% of radar-lead moments, and on 5% beyond 80 m, where velocity
excursions concentrate. The interface offers it as an option (`acc_target_clip_mps`, off by default); see
[07](07_velocity_excursions.md#options) for its measured effect.

## 0x191-0x194: selected-target summaries

Two target summaries, each a pair: 0x191 with 0x192, and 0x193 with 0x194. They describe targets the radar selects
itself (ACC / pre-collision).

**0x191 / 0x193** (8 bytes, sentinel `FE FE FE FC FC FF FE FF`):

| bits (LE) | field |
|---|---|
| `1\|7` | score: 91-100 active, 127 none |
| `9\|7` | target age in cycles, saturates at 126 |
| `26\|6` | target track code; a code can move between the two pairs |
| `34\|6`, `49\|7`, `56\|8` | descriptor tuple, constant per target (e.g. 18/22/25, 15/23, 20/45/120) |
| `43\|5` | dynamic code 9-30, grows with target age |

**0x192 / 0x194** (4 bytes, sentinel `00 FF 00 FF`):

| bytes | field |
|---|---|
| 0-1 | big-endian 13-bit distance, about **3/64 m per code** |
| 2 | **lateral lane bin**: 7/8 own lane, 6 and 9 adjacent lanes, 10-13 far left, 2-5 oncoming side |
| 3 | raw |

The 0x192 distance is heavily smoothed: record-to-record jitter 0.06-0.2 m (0x80 range: 0.7-1.0 m), and it lags the
0x80 track by 10-15 m during closings. Its derivative follows native vRel at r = 0.94 with slope 0.65-0.9. It is a good
"the radar's ACC also has a target in my lane at about this distance" signal.

## 0x190: cycle header

- Bytes 2-5: big-endian **microsecond timestamp**.
- Byte 6 high nibble: **cycle counter** mod 16, +3 per cycle on more than 99.996% of cycles. Use it to detect dropped
  cycles.

## 0x195 / 0x196: event pair

Idle 99.97% of the time and active during rare events (123 event groups in 399 minutes). 0x195 bits 18-27
(MSB-first) form one 10-bit code:

```python
q10 = ((payload[2] & 0x3f) << 4) | (payload[3] >> 4)   # 510 when idle
```

All 42 observed carry/borrow crossings between the two historical sub-fields follow this rule. The DBC lists the
remaining sub-fields of both frames as raw codes.

## 0x240-0x248: context frames

0x240, 0x241, 0x244 and 0x245 share a **rolling phase 1-7** in byte 0 bits 5-7 (0 at startup). On most drives their
bodies hold a default payload; on some drives 0x240 and 0x244 carry changing payloads, always in the same body class
at the same moments, and 0x244 bytes 4 and 7 are always equal. 0x248 carries startup and event bits with the same
phase. Toyota's camera ECU uses the same address family, so these are likely camera-side context forwarded on the
radar link.

## Startup and readiness

| signal | booting | running |
|---|---|---|
| 0x101 byte 0 | `0x1D` | `0x11` |
| 0x197 bit 8 | 0 | 1 (70 ms after 0x101 switches) |
| 0x24F bit 6 | 0 | 1 |

All three switch once and stay, so they are a direct "radar running" signal and a radar-reboot detector.

## Other frames

- **0x202:** counter in byte 1 high nibble (+1 per frame); byte 0 is a fixed function of the counter (map in the DBC).
- **0x210:** copy of Toyota road-sign-assist data (speed-sign presence, `RSA1.SPDVAL1`, `RSA3.TSRMSW`).
- **0x500 / 0x502:** unit-specific constants (redacted in the shared DBC; compare yours) and two slowly drifting codes
  in 0x502 (temperature-like behaviour).
- **0x680, 0x501:** status nibbles.
- **0x180, 0x198, 0x23D:** constants.
