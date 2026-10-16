"""data/reference/units.json is the one place a unit is corrected first: the decoder, the profile files and docs/03 must
agree with it, and retired values must not come back (they reached some files and not others before: docs/06)."""
import json
import re
from pathlib import Path

import pytest

from ars510 import constants, interface, objects
from ars510.support import ACC_CHECK_237

REPO = Path(__file__).resolve().parents[1]
LEDGER = json.loads((REPO / "data" / "reference" / "units.json").read_text())
DOC03 = (REPO / "docs" / "03_slot_fields.md").read_text()
CODE = [p for d in ("ars510", "openpilot", "upstream", "tools") for p in (REPO / d).rglob("*.py") if "legacy" not in p.parts]


@pytest.mark.parametrize("name", sorted(LEDGER["slot_fields"]))
def test_slot_field_layout_zero_and_scale(name):
  row, field = LEDGER["slot_fields"][name], getattr(objects, name)
  assert f"{field.bit_start}|{field.bit_len}" == row["bits"]
  if field.unit == "code":  # kept in centred codes; the physical zero and scale live in the ledger and the interface
    assert field.zero_code == row["decoder_centre"]
  else:
    assert (field.zero_code, field.scale) == pytest.approx((row["zero"], row["scale"]))


def test_84_10_acceleration_matches_everywhere():
  row = LEDGER["slot_fields"]["ACCEL_LIKE"]
  assert (interface.ACCEL_ZERO, interface.ACCEL_SCALE) == (row["zero"], row["scale"])
  assert row["scale_range"][0] <= interface.ACCEL_SCALE <= row["scale_range"][1]
  assert f"`(code − {row['doc_text']}) ×` about {row['scale']} m/s²" in DOC03
  assert f"{row['scale_range'][0]}-{row['scale_range'][1]}" in DOC03


@pytest.mark.parametrize("name", sorted(LEDGER["uncertainty_codes"]))
def test_uncertainty_code_units_in_the_decoder_and_docs(name):
  row = LEDGER["uncertainty_codes"][name]
  src = (REPO / "ars510" / "objects.py").read_text()
  comment = re.search(rf"^\s+{name}: .*# (.*)$", src, re.M)[1]
  assert row["bits"] in comment and all(f"{v:g}" in comment for v in row["per_count"]), comment
  assert f"`{row['bits'].replace('|', chr(92) + '|')}`" in DOC03 and row["doc_text"] in DOC03


def test_acc_target_units_in_the_dbc():
  dbc = (REPO / "upstream" / "toyota_tss2_ars510.dbc").read_text()
  for sig, row in LEDGER["acc_target"].items():
    assert re.search(rf"SG_ {sig} : \d+\|\d+@0[+-] \({row['scale']:g},{row['offset']:g}\)", dbc), sig
  assert LEDGER["acc_target"]["LAT_DIST"]["wrap_m"] == 4096 * LEDGER["acc_target"]["LAT_DIST"]["scale"]
  assert ACC_CHECK_237[1] == 0x14  # the check byte's term for the wrapped bit, which acc / acc_summaries read


def test_ego_and_cycle_constants():
  assert interface.B4_TO_VEGO == pytest.approx(1 / LEDGER["ego"]["used"])
  assert LEDGER["ego"]["used"] == LEDGER["ego"]["b4_over_vego"]["car_A"]
  assert constants.RADAR_CYCLE_S == LEDGER["radar_cycle_s"]["value"]


@pytest.mark.parametrize("rule", LEDGER["retired"], ids=lambda r: r["pattern"])
def test_retired_values_stay_out_of_the_code(rule):
  pattern = re.compile(rule["pattern"], re.M)
  hits = [f"{p.relative_to(REPO)}" for p in CODE if p != Path(__file__) and pattern.search(p.read_text())]
  assert not hits, f"{rule['why']}: {hits}"
