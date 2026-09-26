"""Decoder profiles and the openpilot / StarPilot install targets."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from ars510 import OPENPILOT_CONFIG, STEADY_CONFIG

REPO = Path(__file__).resolve().parents[1]


def test_steady_is_openpilot_plus_k4_only():
  diff = {f.name for f in dataclasses.fields(OPENPILOT_CONFIG)
          if getattr(OPENPILOT_CONFIG, f.name) != getattr(STEADY_CONFIG, f.name)}
  assert diff == {"range_fusion_gain", "vrel_smooth_far_tau_s"}
  assert STEADY_CONFIG.range_fusion_gain == 0.1 and STEADY_CONFIG.vrel_smooth_far_tau_s == 1.0


def test_wrapper_has_one_switchable_profile_line():
  src = (REPO / "openpilot" / "ars510_radar_interface.py").read_text()
  assert src.count('PROFILE = PROFILES["default"]') == 1
  assert 'PROFILES = {"default": OPENPILOT_CONFIG, "steady": STEADY_CONFIG}' in src


def test_starpilot_patch_targets_and_flag_bit():
  patch = (REPO / "openpilot" / "starpilot" / "opendbc_toyota_ars510_starpilot.patch").read_text()
  files = set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M))
  assert files == {f"opendbc/car/toyota/{n}.py" for n in ("interface", "radar_interface", "values")}
  # StarPilot already uses 4096 (AUTO_BRAKE_HOLD) and 8192 (DSU_BYPASS)
  assert "+  ARS510_RADAR = 16384" in patch
  assert "ARS510_RADAR = 4096" not in patch
  upstream = (REPO / "openpilot" / "opendbc_toyota_ars510.patch").read_text()
  assert "+  ARS510_RADAR = 4096" in upstream
