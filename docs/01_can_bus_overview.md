# 01. The radar bus

On the logged RAV4 the ARS510 object data appears on **comma harness bus 1** (`src == 1` in openpilot logs). Ego speed comes from the car bus (bus 0, Toyota `SPEED` 0xB4).

Stock opendbc parses TSS2 radar tracks at 0x180–0x19F with `toyota_tss2_adas.dbc`. **That layout does not apply to this radar.** On the ARS510:
- 0x180 is a constant;
- 0x191–0x194 are two "selected target" summaries;
- the object list lives in a segmented record on 0x80.

openpilot currently gives these RAV4 platforms no radar DBC, so it sets `radarUnavailable` and runs vision-only.

## Message map (bus 1)

| addr | DLC | rate | what it is | status |
|---|---|---|---|---|
| **0x80** | 8 | 106 frames per 60 ms (~1760 frames/s) | **Object list**: 742-byte record over 106 frames, 20 slots × 36 bytes + CRC32. See [02](02_object_record_0x80.md) | decoded |
| 0x81 | 8 | 16.7 Hz | Fixed `30 00 00 00 00 00 00 00` within 20 ms after each 0x80 record start | framing only |
| **0x85** | 8 | 21 frames per 60 ms | 147-byte record; verified CRC at 141–144, trailer 145–146; provisional 12-byte cells in 21–140. See [03](03_shell_record_0x85.md) | CRC verified, cell semantics open |
| 0x86 | 8 | 16.7 Hz | Same marker as 0x81, for 0x85 | framing only |
| 0x100–0x103 | 7/6/3/2 | 10 Hz | Startup/state frames: 0x101 state 0x1D → 0x11 once at startup; 0x102 has 3 live bits; 0x103 all zero | context |
| 0x180 | 5 | 16.7 Hz | Constant `CFC0000000` | constant |
| 0x190 | 7 | 16.7 Hz | Cycle header: bytes 2–5 big-endian µs timestamp; byte 6 high nibble a mod-16 counter (+3 per cycle) | timing |
| 0x191 / 0x193 | 8 | 16.7 Hz | Selected-target companions: score-like code (91–100 active, 127 none), age counter, 6-bit track code, three descriptor codes | partly understood |
| **0x192** / 0x194 | 4 | 16.7 Hz | Selected-target summaries: 0x192 bytes 0–1 a heavily smoothed distance (~3/64 m per code), byte 2 a lateral bin. See [04](04_support_messages.md) | partly understood |
| 0x195 / 0x196 | 8 | 16.7 Hz, idle except rare events | Paired event frames, idle 99.97% of the time; field boundaries known, meaning not | unknown |
| 0x197 / 0x198 | 2 / 1 | 16.7 Hz | 0x197 bit 8 is a one-way startup flag; 0x198 constant `10` | context |
| 0x202 | 5 | 16.7 Hz | Counter in byte 1 high nibble; byte 0 a check byte fully determined by the counter | framing |
| 0x210 | 7 | 5 Hz | Copy of Toyota road-sign-assist data (speed-sign value, presence, TSR switch) | not radar data |
| 0x235 / 0x237 / 0x239 / 0x23B / 0x23D | 8/8/8/3/8 | 50 Hz | Companion/debug family with mux + rolling counter in byte 1; byte 0 an affine parity check. 0x237 bytes 1–2 correlate with lead distance (r ≈ 0.9) | debug |
| 0x240 / 0x241 / 0x244 / 0x245 | 8 | 16.7 Hz | Mirror frames: byte 0 mux phase, two identical BE24 words | debug |
| 0x248 | 8 | 16.7 Hz | Startup / event context | context |
| 0x24D / 0x24F | 7 / 1 | 1 Hz / 33 Hz | Constant / startup flag | constant |
| 0x500 / 0x501 / 0x502 | 6 / 7 / 8 | 2 / 2 / 0.33 Hz | Constants plus two slowly drifting codes in 0x502 (temperature-like?). **0x500 and 0x502 carry what may be unit-specific constants (serial or calibration?). They are redacted in the shared DBC; compare yours** | unknown |
| 0x680 | 8 | 2 Hz | Status/mux context. The older Toyota Continental `CLUSTER_F` object layout does **not** apply (dead end D-037) | unknown |

The frame-level DBC [`dbc/ars510_radar_bus.dbc`](../dbc/ars510_radar_bus.dbc) exposes all of these. Its comments give observed constants, idle payloads and startup behaviour.

The radar cycle is **60 ms (16.67 Hz)**. Bus 2 (camera side) carries ordinary Toyota camera traffic plus a 50 Hz 0x191 unrelated to the radar's 0x191.

## Power-on

Several addresses send an "initialisation" payload on their first frame (all ones, all zeros, or a superset of later payloads). Examples:
- 0x100 `FFFF0000000000`
- 0x192 `0FFF0FFF`
- 0x196 `FFFFFFFFFFFFFFFF`

These are observations, not validity rules. Early object records also contain placeholder tracks, some at exactly 0 m. The age gate handles them ([02](02_object_record_0x80.md), [07](07_openpilot_integration.md)).

## Where the radar's own ego speed comes from

No tested message on the radar bus correlated with ego speed at |r| > 0.97 in the bounded scan across 47 addresses on buses 1 and 2. This does not establish which speed input the radar receives: multiplexing, transformations and forwarding remain possible. The leading velocity interpretation is over-ground, so the consumer subtracts ego speed. Choice of ego-speed source matters at the 1–1.5% level ([02](02_object_record_0x80.md#velocity-scale-and-the-0149-question)).
