# 04. Support messages

None of these is currently needed for the native object decode. Bounded searches tested three possibilities:
- a "finalised" lead speed;
- a confidence;
- a correction meant to be combined with 0x80.

**No usable decoder for those functions has been established. Absence is not proved.** Details and search limits follow.

## 0x191–0x194: two selected-target summaries

The radar publishes two target summaries, each as a companion pair: 0x191 with 0x192, and 0x193 with 0x194.

**0x191 / 0x193 (8 bytes).** Sentinel `FEFEFEFCFCFFFEFF`.
- bits `1|7`: a score-like code, 91–100 when active and 127 when empty. Same-identity transitions are almost always stable or unit steps.
- bits `9|7`: a track-age-like counter; plateaus at 126, 127 when empty.
- bits `26|6`: a track identity code. It can migrate between the two pairs.
- bits `34|6`, `49|7`, `56|8`: an identity-stable descriptor tuple with a few discrete values (e.g. 18/22/25, 15/23, 20/45/120). Class or size? Unresolved.
- bits `43|5`: a dynamic code, 9–30.

**0x192 / 0x194 (4 bytes).** Sentinel `00FF00FF`.
- bytes 0–1: big-endian 13-bit **distance-like candidate**, about **3/64 m per code** (≈ 0.047 m). Earlier fits split between 0.04 and 0.05; 3/64 fits best in the tested matching. Metric scale and association remain provisional.
- byte 2: **lateral-bin candidate**. Observed associations: 7/8 own lane, 6 and 9 adjacent lanes, 10–13 far left, 2–5 the oncoming side. Not an established OEM lane codebook.
- byte 3: unknown. It relates to neither match quality nor speed.

### What 0x192 is

This looks like the ACC / pre-collision target the radar computes for the car, with its own target selection. It is **not a cleaner measurement of the lead:**
- It is heavily smoothed: cycle-to-cycle jitter is 0.06–0.2 m against 0.7–1.0 m for the raw 0x80 range.
- It lags the 0x80 track by 10–15 m during closings.
- Where it follows the 0x80 lead, its derivative tracks native vRel (r 0.94) with slope only 0.65–0.9, i.e. low-passed.
- It matches some 0x80 track within 1.5 m only 18–39% of the time. That is consistent with its own selection plus heavy filtering.

It is too lagged to serve as vRel. It might be useful as a sanity check ("the radar's own ACC also sees a target in my lane at about this distance"), but that has not been tested.

## 0x235–0x23D: 50 Hz companion / debug family

- Byte 1 contains the historical low-nibble status/mux view and a high-nibble rolling counter. On 0x237, that low nibble overlaps the distance field and is **not an independent selector**; see the correction in [15](15_acc_target_stream_and_health_signals.md).
- Byte 0 is an exact affine parity check over the rest of the frame. The per-address masks are in `ars510_radar_bus.dbc`; the OEM algorithm name is unknown.
- 0x237 bytes 1–2 correlate with lead distance (r 0.89–0.93).
- Direct ego speed, steering, brake, accel or yaw fields were searched in 3,428 packed candidates, and none survived.
- These frames are not a Continental-standard object stream (dead end D-004).

## 0x240 / 0x241 / 0x244 / 0x245 / 0x248

**Correction (2026-09-28): the mirror description applied only to the default
payloads on the initial two drives.** In the expanded 399-segment, 24-drive
research corpus, `0x240` and `0x244` each carry 37,094 non-default bodies across
three drives, including one confirmation drive. Their two historical BE24
containers differ and byte 7 is nonzero on every such frame. `0x241` and
`0x245` retain the zero/default bodies in this scope. Of 321,840 exact-time
complete quartets, 31,940 differ across addresses. Counts are imported research
results, not a bundled rerun ([summary](../data/analysis/summaries/context_24x.json)).

Byte-0 bits `5|3` cycle through 1–7. This establishes a rolling phase, **not seven
objects or scan channels**. Changing bodies are more similar on adjacent cycles
than seven cycles apart in all six drive/address comparisons; that descriptive
result does not exclude every multiplexing scheme. Bit `3` of `0x240` separates
the default/zero and other bodies in this corpus, but is not decoded as object
validity. `0x248` also has previously unreported live bits at byte 0 bits 0–1,
byte 2 bit 1 and byte 6 bit 0; their meanings remain unresolved.

Historical openpilot [camera-emulation definitions](https://github.com/commaai/openpilot/blob/v0.5.13/selfdrive/car/toyota/values.py)
use the same four addresses and default bodies; its
[controller](https://github.com/commaai/openpilot/blob/v0.5.13/selfdrive/car/toyota/carcontroller.py)
generates the same seven-state prefix. This is a source-family clue, **not proof
of the transmitting ECU or software injection on these captures**. No selected
family frames appeared in `sendcan` in the two original-log spot checks.
Bus-1 presence alone cannot establish radar origin.

DBC labels now preserve these regions as raw unknowns rather than asserting
mirrored words or reserved zeros. The BE24 grouping is a historical display
container, not a demonstrated active-field boundary. Physical units, source,
and any Doppler/strength/quality meaning are unresolved; runtime decoding is
unchanged.

## 0x100–0x103, 0x197, 0x24F: startup

- 0x101 goes 0x1D → 0x11 exactly 70 ms before 0x197 bit 8 flips 0 → 1.
- 0x24F bit 6 does the same.
- These are one-way startup phases, useful to detect a radar reboot.
- They are **not** object validity.

## 0x190: cycle header

- Bytes 2–5 are a big-endian microsecond timestamp.
- The byte 6 high nibble is a mod-16 counter advancing +3 per cycle, on more than 99.996% of cycles.
- Use it to detect dropped cycles if you need to.

## 0x210

A replica of Toyota road-sign-assist data: speed-sign presence, the `RSA1.SPDVAL1` value, and the `RSA3.TSRMSW` switch. Not radar data.

## Scope of the negative search

The original scan covered unsigned little-endian windows of lengths 4, 6, 8, 10, 12 and 16 in other bus-1 messages, about 10k windows per drive at 10 Hz, plus ID85 analysis fields and ID80 header/slot candidates. It excluded windows with fewer than three values and used linear correlation against time-aggregated errors. Some slot tests also excluded fields classified as constant. Thus binary validity flags, constants, object-specific joins and conditional/nonlinear effects were not exhausted. The original ID85 partition also included CRC bytes ([03](03_shell_record_0x85.md)).

Each was tested against:
- the camera-measured velocity error of the radar's lead, and its magnitude (bar |r| > 0.3);
- the range walk (bar |r| > 0.3);
- ego speed (bar |r| > 0.9).

A field had to pass on two or more drives. No linear candidate passed the chosen gates. A later categorical/conditional follow-up found scene/range/speed associations and a few weak variance candidates, but no validated excursion guard ([13](13_evidence_review.md)). Constants cannot be identified from within-unit correlation alone.

Toyota's older TSS2 interface uses a paired `TRACK_B.SCORE` alongside validity/history; do not transfer that mapping here. This stream already has a per-slot score-like byte at `16|8`, as well as selected-target score-like codes in 0x191/0x193. Whether they represent existence, measurement quality or something else remains open. A score of 100 is not a demonstrated accuracy guarantee.

## 0x195 / 0x196: rare coupled payloads; corrected constant labels

An expanded 399-segment census contains 387,226 frames per address and 123
same-segment event groups. Of 387,189 uniquely matched pairs within 20ms,
387,179 exclude the documented all-FF initialization payload in 0x196.
Five previously constant-labelled regions vary in that subset:

| Address | MSB-first start, width | Violating pairs |
|---|---|---:|
| 0x195 | 16, 3 | 95 |
| 0x195 | 19, 2 | 95 |
| 0x195 | 28, 5 | 10 |
| 0x196 | 40, 3 | 298 |
| 0x196 | 56, 2 | 70 |

The DBC now calls these regions `UNKNOWN`. Their historical bit cuts remain
available as lossless raw views, **not confirmed numeric field boundaries**.
The 0x195 28,5 exceptions occur on one discovery drive; the other four regions
vary in both discovery and confirmation captures. No unit or physical meaning
is established. The old failed geometry screen also did not prove diagnostic
or vehicle-state semantics. These bits might extend adjacent numeric fields;
that requires separate carry/borrow and physical evidence.

All 2,511 distinct observed payloads round-trip through the corrected schema.
Six representative payloads were checked against four original logs. The counts
are imported research results from previously exposed captures, not a bundled
rerun ([summary](../data/analysis/summaries/event_pair_structure.json)).
No control behavior or object decoder changes follow from this correction.
