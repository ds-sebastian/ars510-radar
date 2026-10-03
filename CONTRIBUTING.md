# Contributing

Thanks for helping. There are three ways in, from least to most involved: drive and report, fix or improve code and
docs, or add a research result.

## Workflow

- `main` only changes through pull requests. Branch from `main` (or fork the repo), one topic per branch, and open a
  PR. Branch names: `fix/…`, `feat/…`, `docs/…`, `research/…`, `integration/…`.
- CI runs on every PR: `pytest`, `tools/check_structure.py` and `tools/check_privacy.py`. A PR merges when CI is
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
`8821F0R01100` is listed in openpilot fingerprints but its layout and integration remain unconfirmed; detection
currently depends on observing both 0x80 and 0x85 on bus 1. See [firmware validation](docs/10_research_directions.md#for-the-integration).
Install with [`openpilot/README.md`](openpilot/README.md). The installer supports openpilot and forks, and the
`steady` profile is the default. Then:

1. Reboot, drive, and press the bookmark (flag) button whenever braking feels wrong or a lead seems stuck.
2. Open a **Drive report** issue. Give the fork and version, `install.py --check` output, road type, and for each
   flagged moment the time into the drive and what happened.
3. Never post route IDs, dongle IDs, VINs, GPS positions or video that identifies you or others. If a log would help,
   say so in the issue and the maintainer will arrange a private transfer.

Reports from a different car, radar firmware or fork are especially valuable: they are the only way to learn whether
the layout and the smoothing hold beyond one car.

## Code changes

- **Decoder** (`ars510/`): field changes need a test (a synthetic slot in `tests/` or a bundled sample in
  `data/sample/`) and the matching row in `docs/03` (or `docs/02`, `docs/04`, `docs/05`).
- **Driving behaviour** (anything that changes published RadarPoints under the `steady` profile): state the expected
  effect before running it, replay it through openpilot on drives against the current profile with the same gates as
  [docs/07](docs/07_velocity_excursions.md#options), and put the numbers in the PR. Behaviour changes that only look
  better on the drive that motivated them are not merged.
- **Integration** (`openpilot/`): run `openpilot/check_integration.py` against every fork you can
  ([`openpilot/README.md`](openpilot/README.md#test-on-a-pc-first)) and list the results in the PR. The installer
  must stay fork-agnostic: no in-place edits of fork files, no new `ToyotaFlags` bits.
- Style: match the surrounding code; the decoder has no runtime dependencies and must stay that way.

## Docs and research results

The docs describe the **current state only**: what each field is, how sure we are (● confirmed / ◐ likely /
○ candidate), and the evidence behind it.

- Rewrite sentences in place when understanding changes.
- No dated banners, changelogs of claims, or "this didn't work" lists: history lives in git and PRs.
- Numbers cited in the docs come from a summary JSON in `data/analysis/summaries/`, listed in `data/README.md`.
  Figures come from `tools/make_analysis_figures.py`.
- Drives stay anonymous: drive letters (A/B/C, D1-D4) and times relative to an event.
- Research PRs: say what was tested, on which drives, what counts as a pass, and include negative results in the PR
  description. Only confident, reproducible results change the docs.

## Using AI agents

Agents (Codex, Claude Code and others) follow [`AGENTS.md`](AGENTS.md), the same rules as people: branch, PR, CI
green, no direct pushes to `main`, and the privacy rules above. Say in the PR description when an agent wrote the
change.
