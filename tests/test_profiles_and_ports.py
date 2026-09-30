"""Decoder profiles and the generic openpilot / fork installer."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
import subprocess
import sys

from ars510 import OPENPILOT_CONFIG, STEADY_CONFIG

REPO = Path(__file__).resolve().parents[1]


def test_steady_is_openpilot_plus_k4_jump_guard_far_settling_and_ramp_limiter():
  diff = {f.name for f in dataclasses.fields(OPENPILOT_CONFIG)
          if getattr(OPENPILOT_CONFIG, f.name) != getattr(STEADY_CONFIG, f.name)}
  assert diff == {"range_fusion_gain", "vrel_smooth_far_tau_s", "vjump_thresh_mps", "far_min_publish_age",
                  "ramp_up_mps2", "ramp_down_mps2"}
  assert STEADY_CONFIG.ramp_up_mps2 == 4.0 and STEADY_CONFIG.ramp_down_mps2 == 6.0 and STEADY_CONFIG.ramp_ref_tau_s == 3.0
  assert STEADY_CONFIG.range_fusion_gain == 0.1 and STEADY_CONFIG.vrel_smooth_far_tau_s == 1.0
  assert STEADY_CONFIG.vjump_thresh_mps == 8.0 and OPENPILOT_CONFIG.drop_saturated_codes
  assert STEADY_CONFIG.far_min_publish_age == 100 and STEADY_CONFIG.far_publish_range_m == 70.0
  assert OPENPILOT_CONFIG.far_min_publish_age == 0


def test_wrapper_has_one_switchable_profile_line_defaulting_to_steady():
  src = (REPO / "openpilot" / "ars510_radar_interface.py").read_text()
  assert src.count('PROFILE = PROFILES["steady"]') == 1
  assert 'PROFILES = {"default": OPENPILOT_CONFIG, "steady": STEADY_CONFIG}' in src
  assert "def hook_car_interface(" in src and "ToyotaFlags.ARS510_RADAR" not in src


def _fake_opendbc(tmp_path):
  toyota = tmp_path / "opendbc_repo" / "opendbc" / "car" / "toyota"
  toyota.mkdir(parents=True)
  (tmp_path / "opendbc_repo" / "opendbc" / "dbc").mkdir()
  (tmp_path / "opendbc_repo" / "opendbc" / "dbc" / "ars510_radar_bus.dbc").write_text("old install")
  original = "class CarInterface:\n  pass\n"
  (toyota / "interface.py").write_text(original)
  return toyota, original


def _install(*args):
  return subprocess.run([sys.executable, str(REPO / "openpilot" / "install.py"), *map(str, args)], capture_output=True, text=True)


def test_installer_appends_one_hook_block_and_uninstalls_cleanly(tmp_path):
  toyota, original = _fake_opendbc(tmp_path)
  for _ in range(2):  # re-running replaces, never duplicates
    r = _install(tmp_path)  # the openpilot checkout; opendbc_repo is found inside it
    assert r.returncode == 0, r.stderr
  text = (toyota / "interface.py").read_text()
  assert text.startswith(original) and text.count("hook_car_interface(CarInterface)") == 1
  assert (toyota / "ars510" / "interface.py").exists()
  assert not (tmp_path / "opendbc_repo" / "opendbc" / "dbc" / "ars510_radar_bus.dbc").exists()  # old Cabana copy removed
  assert 'PROFILE = PROFILES["steady"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert _install(tmp_path, "--profile", "default").returncode == 0
  assert 'PROFILE = PROFILES["default"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert _install(tmp_path, "--uninstall").returncode == 0
  assert (toyota / "interface.py").read_text() == original
  assert not (toyota / "ars510").exists() and not (toyota / "ars510_radar_interface.py").exists()


def test_legacy_patches_are_kept_for_upgrades():
  names = {p.name for p in (REPO / "openpilot" / "legacy").glob("*.patch")}
  assert names == {f"opendbc_toyota_ars510_{f}.patch" for f in ("openpilot", "starpilot", "sunnypilot")}


def test_installer_uses_opendbc_repo_behind_the_openpilot_symlink(tmp_path):
  # real openpilot checkouts have a top-level `opendbc` symlink into opendbc_repo
  toyota, original = _fake_opendbc(tmp_path)
  (tmp_path / "opendbc").symlink_to("opendbc_repo/opendbc")
  r = _install(tmp_path, "--check")
  assert r.returncode == 0 and f"opendbc: {(tmp_path / 'opendbc_repo').resolve()}" in r.stdout
  assert "older patch-based install: none" in r.stdout
  assert _install(tmp_path).returncode == 0
  assert (toyota / "interface.py").read_text().count("hook_car_interface(CarInterface)") == 1
