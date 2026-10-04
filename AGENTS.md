# AGENTS.md

Instructions for AI coding agents (Codex, Claude Code, Gemini, …) working in this repository. Humans: see
[CONTRIBUTING.md](CONTRIBUTING.md), same rules.

## What this repo is

A decoder and openpilot integration for the Toyota / Continental ARS510 front radar (RAV4 2022 / 2023). It turns the
radar's native object list (a 742-byte record over 106 CAN frames on bus 1, 0x80) into openpilot radar tracks.
Start with [README.md](README.md), then the doc for your area:

| area | code | doc |
|---|---|---|
| transport, CRC, slot layout | `ars510/transport.py`, `record.py`, `constants.py` | `docs/02` |
| field mapping (start bit, length, zero, scale) | `ars510/objects.py` | `docs/03` |
| 0x85 metadata record, lane cells | `ars510/shell85.py` | `docs/04` |
| ACC target, support messages | `ars510/support.py` | `docs/05` |
| openpilot-facing interface, profiles, filters | `ars510/interface.py` | `docs/07`, `docs/08`, `docs/11` |
| install into openpilot / forks | `openpilot/install.py`, `openpilot/ars510_radar_interface.py` | `openpilot/README.md` |
| replay harness, Cabana, figures | `tools/` | `docs/09` |

Parsing does not use a DBC; `dbc/` is for Cabana only.

## Commands

```bash
pip install -e .[dev]
pytest                              # must pass
python tools/check_structure.py     # CRC and layout evidence on the bundled samples; must pass
python tools/check_privacy.py       # no route/dongle IDs, VINs, GPS, local paths; must pass
```

## Rules

- **Never push to `main`.** Work on a branch (`fix/…`, `feat/…`, `docs/…`, `research/…`, `integration/…`), open a PR
  with `gh pr create`, and wait for CI. Merge only when the maintainer asked for the change and CI is green; otherwise
  leave the PR for review.
- **Privacy.** Never commit or paste route IDs, dongle IDs, VINs, GPS, device IPs, local paths or identifying video.
  Drives are anonymous (A/B/C, D1-D4) with relative times. `tools/check_privacy.py` enforces the patterns.
- **Decoder semantics** change only with a test and the matching doc row. Keep `ars510/` dependency-free.
- **Driving behaviour** (anything that changes a profile's output, above all the default `FUSED_CONFIG`) needs an
  openpilot replay against the current profile with the gates in `docs/07`, the vision-only comparison in `docs/11`,
  a review of the moments that change, and numbers in the PR. Do not tune on the drive that motivated the change.
- **Installer** stays fork-agnostic: append-only hook in `toyota/interface.py`, no in-place fork edits, no new
  `ToyotaFlags` bits. Run `openpilot/check_integration.py` against every fork available.
- **Docs** state the current state only (● / ◐ / ○), rewritten in place; numbers come from
  `data/analysis/summaries/*.json` listed in `data/README.md`. No dated banners or dead-end lists.
- **Heavy jobs** (replays, full-log decodes) can use 8-14 GB each. Run at most two in parallel, and on a desktop
  session cap them (for example `systemd-run --user -p MemoryMax=12G …`) so they cannot take the session down.
- Mark agent-written PRs as such in the description.
