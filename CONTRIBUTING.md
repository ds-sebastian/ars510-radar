# Contributing

Thanks for helping. There are three ways in, from least to most involved:

1. **Drive and report.** Install it, drive, flag odd moments, and open a drive report. Reports from another car, radar
   firmware or fork are the most valuable contribution right now.
2. **Fix or improve code and docs.** Installer support for another fork, clearer docs, tests, tools.
3. **Add a research result.** An open problem from [docs/10](docs/10_research_directions.md), with the evidence.

## Workflow

- `main` only changes through pull requests. Branch from `main` (or fork the repo), one topic per branch, and open a
  PR. Branch names: `fix/…`, `feat/…`, `docs/…`, `research/…`, `integration/…`.
- CI runs on every PR: `pytest`, `tools/check_structure.py`, `tools/check_privacy.py` and `ruff check upstream/`. A PR merges when CI is
  green and the maintainer (@ds-sebastian) has reviewed it. PRs are squash-merged.
- Keep PRs small and self-contained: code, tests and the docs that describe the change travel together.

```bash
git clone https://github.com/ds-sebastian/ars510-radar && cd ars510-radar
python -m venv .venv && . .venv/bin/activate && pip install -e .[dev]
git checkout -b fix/short-description
pytest && python tools/check_structure.py && python tools/check_privacy.py
```

## Testing on your car

The confirmed radar firmware is `8821F0R03100` at 0x750 / 0x0f on the Toyota ARS510 (RAV4 2022 / 2023).
`8821F0R01100` is listed in openpilot fingerprints; for it, detection relies on seeing both 0x80 and 0x85 on bus 1 at
fingerprinting (a warm restart), and one capture adds it to the firmware list. See [firmware validation](docs/10_research_directions.md#for-the-integration).
Install with [`openpilot/README.md`](openpilot/README.md). The installer supports openpilot and forks. The `acc` profile
(the radar's ACC target alone) is the default; `--profile fused` installs the all-tracks alternative and `--profile raw` the
unfiltered decode for comparison. Then:

1. Reboot, drive, and press the bookmark (flag) button whenever braking feels wrong or a lead seems stuck.
2. Open a **Drive report** issue. Give the fork and version, the installed profile, `install.py --check` output, road type, and for each
   flagged moment the time into the drive and what happened.
3. Keep route IDs, dongle IDs, VINs, GPS positions and video that identifies you or others out of public posts. If a log would help,
   say so in the issue and the maintainer arranges a private transfer.

Reports from a different car, radar firmware or fork are especially valuable: they show how far the layout and the
filter carry beyond the owner's car (a second RAV4 has reported so far).

For a targeted contribution, use [the route and test guide](docs/16_routes_and_tests.md). It lists the ordinary
drives, parked/controlled acquisitions, logs to keep and independent references that each question needs.
PCS/AEB event collection follows the [professional/passive specification](docs/15_aeb_pcs.md#recording-pcs--aeb-events).

## Code changes

- **Decoder** (`ars510/`): field changes need a test (a synthetic slot in `tests/` or a bundled sample in
  `data/sample/`) and the matching row in `docs/03` (or `docs/02`, `docs/04`, `docs/05`).
- **Driving behaviour** (anything that changes the RadarPoints a profile publishes, above all the default `acc` and `fused`):
  state the expected effect before running it, replay it through openpilot against the current profile with the gates
  in [docs/09](docs/09_tools_and_data.md#developing-and-testing-a-change) and the vision-only comparison in
  [docs/11](docs/11_profiles_compared.md#against-vision-only), and put the numbers in the PR. Review the moments that
  change as well as the counts. Changes are merged on held-out evidence, beyond the drive that motivated them.
- **Integration** (`openpilot/`): run `openpilot/check_integration.py` against every fork you can
  ([`openpilot/README.md`](openpilot/README.md#test-on-a-pc-first)) and list the results in the PR. The installer
  stays fork-agnostic: an append-only hook, with fork files left as they are and the existing `ToyotaFlags` bits.
- Style: match the surrounding code; the decoder is dependency-free and stays so.

## Docs and research results

The docs describe the **current state only**: what each field is, how sure we are (● confirmed / ◐ likely /
○ candidate), and the evidence behind it.

- Rewrite sentences in place when understanding changes; history lives in git and PRs.
- State what a field is and what the evidence shows, in positive terms; negative results go in the PR description.
- Numbers cited in the docs come from a summary JSON in `data/analysis/summaries/`, listed in `data/README.md`.
  Figures come from the `tools/make_*_figures.py` scripts.
- Drives stay anonymous: drive letters (A/B/C, D1-D4, sample drive E, owner road drives O1-O5, second-car drives U1-U3 and S#) and times relative to an event.
- Research PRs: say what was tested, on which drives, what counts as a pass, and include negative results in the PR
  description. Only confident, reproducible results change the docs.

## Using AI agents

Agents (Codex, Claude Code and others) follow [`AGENTS.md`](AGENTS.md), the same rules as people: branch, PR, CI
green, every change to `main` through a PR, and the privacy rules above. Say in the PR description when an agent wrote the
change.
