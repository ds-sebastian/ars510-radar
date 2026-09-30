## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Type

- [ ] Decoder (field or transport change): test added, doc row updated
- [ ] Driving behaviour (changes `steady` output): replay numbers below
- [ ] Integration / installer: `check_integration.py` results below
- [ ] Docs / figures
- [ ] Research result

## Evidence

<!-- Tests, replay gates (hard radar-only ticks, radar-only episodes, reaction lag, anticipation), forks checked,
     or the drives and pass/fail criteria of a research test, including negative results. -->

## Checklist

- [ ] `pytest`, `tools/check_structure.py` and `tools/check_privacy.py` pass
- [ ] No route/dongle IDs, VINs, GPS, local paths or identifying video
- [ ] Docs describe the current state (no dated notes); cited numbers come from `data/analysis/summaries/`
- [ ] Written with an AI agent: say which (or "none")
