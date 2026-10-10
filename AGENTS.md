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
| ACC target, support messages, car-bus 0x366 | `ars510/support.py` | `docs/05`, `docs/13` |
| openpilot-facing interface, profiles, filters | `ars510/interface.py` | `docs/08`, `docs/11`, `docs/12` |
| install into openpilot / forks | `openpilot/install.py`, `openpilot/ars510_radar_interface.py` | `openpilot/README.md` |
| replay harness, Cabana, figures | `tools/` | `docs/09` |

Parsing works from raw frames; `dbc/` is for Cabana.

## Commands

```bash
pip install -e .[dev]
pytest                              # must pass
python tools/check_structure.py     # CRC and layout evidence on the bundled samples; must pass
python tools/check_privacy.py       # no route/dongle IDs, VINs, GPS, local paths; must pass
ruff check upstream/                # the openpilot file follows opendbc's ruff rules (CI)
```

## Rules

- **`main` changes only through pull requests.** Work on a branch (`fix/…`, `feat/…`, `docs/…`, `research/…`, `integration/…`), open a PR
  with `gh pr create`, and wait for CI. Merge only when the maintainer asked for the change and CI is green; otherwise
  leave the PR for review.
- **Privacy.** Route IDs, dongle IDs, VINs, GPS, device IPs, local paths and identifying video stay out of commits and pastes.
  Drives are anonymous (A/B/C, D1-D4, E, O1-O3) with relative times. `tools/check_privacy.py` enforces the patterns.
- **Decoder semantics** change only with a test and the matching doc row. Keep `ars510/` dependency-free.
- **Driving behaviour** (anything that changes a profile's output, above all the default `FUSED_CONFIG`) needs an
  openpilot replay against the current profile with the gates in `docs/09`, the vision-only comparison in `docs/11`,
  a review of the moments that change, and numbers in the PR. Tune on other drives than the one that motivated the change.
- **The openpilot file** (`upstream/ars510_radar.py`) is meant for upstream, where every line has to be defended. A PR
  that adds or removes lines there updates its row in the parts ledger (`docs/10`, "Parts of the openpilot file", and
  `data/analysis/summaries/openpilot_file_parts.json`): code lines, evidence, what removing it costs, upstream status.
- **Installer** stays fork-agnostic: append-only hook in `toyota/interface.py`, no in-place fork edits, no new
  `ToyotaFlags` bits. Run `openpilot/check_integration.py` against every fork available.
- **Docs** state the current state only (● / ◐ / ○), rewritten in place; numbers come from
  `data/analysis/summaries/*.json` listed in `data/README.md`. No dated banners or dead-end lists.
- **Heavy jobs** (replays, full-log decodes) can use 8-14 GB each. Run at most two in parallel, and on a desktop
  session cap them (for example `systemd-run --user -p MemoryMax=12G …`) so the session stays up.
- Mark agent-written PRs as such in the description.
