# Viewing ARS510 objects in Cabana

The object list is a multi-frame record, so Cabana cannot decode it straight from 0x80. `tools/build_cabana_route.py` reassembles each record and appends it to a copy of your log as ordinary CAN messages on a **virtual bus 10**, one message per occupied object slot. The slot bytes are copied verbatim, so the DBC bit positions are the real slot bit positions.

## Build

Run with an openpilot environment, which provides cereal:

```bash
OP=/path/to/openpilot
PYTHONPATH=$OP:$OP/opendbc_repo $OP/.venv/bin/python tools/build_cabana_route.py \
    /path/to/<route>--12 /path/to/<route>--13  --out cabana_out
```

- Each input directory holds `rlog`, `rlog.zst` or `rlog.bz2`, plus optional cameras. Cameras are symlinked.
- The output is `cabana_out/route/<route>--<n>/rlog`: the original events plus the virtual-bus events.
- To regenerate only the DBC: `python tools/build_cabana_route.py --dbc-only`.

## Open

```bash
$OP/tools/cabana/cabana --data_dir cabana_out/route "<route>" --dbc dbc/ars510_objects_vbus.dbc
```

Some Cabana builds only list DBCs from `opendbc/dbc/`. If so, copy the file there locally; don't commit it into openpilot. For the raw bus use `dbc/ars510_radar_bus.dbc` (bus 1).

## Messages on bus 10

| address | message | notes |
|---|---|---|
| 0x700–0x713 | `ARS510_OBJ_00..19` | raw slot bytes: AGE, DREL, YREL_LEFT, VLONG_OVER_GROUND, … plus unverified candidates (`UNK_*`, `PER_TRACK_*`, `CONST_*`) |
| 0x720–0x733 | `ARS510_OBJ_xx_DERIVED` | **not radar bytes**: VREL (over-ground − 0xB4), V_EGO_0xB4, TRACK_ID_RAW, TRACK_ID_OP (what openpilot would see), PUBLISHED_OP, SETTLED (age ≥ 60), plus the two candidates DREL_FUSED and VREL_SMOOTHED |
| 0x740 / 0x741 | `ARS510_REC_HEADER` / `TRAILER` | record bytes 0–16; CRC32 |
| 0x760 | `ARS510_SHELL85_HDR` | 0x85 proposed prefix bytes 0–20 |
| 0x761–0x76A | `ARS510_SHELL85_CELL_00..09` | provisional 12-byte raw cells; not established objects |
| 0x76B | `ARS510_SHELL85_CRC` | verified CRC at 141–144 and trailer at 145–146 |

Regenerate virtual logs together with this DBC. Older exports used a different, incorrect ID85 slicing; loading the new DBC onto those logs does not fix their payloads. Raw ID80 bit `2|6` is now named `SLOT_INDEX_CODE`, not an object category. ID85 CRC failures are withheld. The exporter currently restarts interfaces per input segment, so derived track IDs are segment-local, not a cross-segment physical identity guarantee.

Useful plots:
- DREL with VREL of one slot next to the video;
- TRACK_ID_RAW, which changes on age restart;
- SETTLED, to see the young-track convergence;
- VLONG_OVER_GROUND of a lead while you follow it, which should be ≈ your own speed.
