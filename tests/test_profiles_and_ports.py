"""Decoder profiles and the generic openpilot / fork installer."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
import subprocess
import sys

from ars510 import BASE_CONFIG

REPO = Path(__file__).resolve().parents[1]


def test_wrapper_has_one_switchable_profile_line_defaulting_to_fused():
  src = (REPO / "openpilot" / "ars510_radar_interface.py").read_text()
  assert src.count('PROFILE = PROFILES["fused"]') == 1
  assert 'PROFILES = {"fused": FUSED_CONFIG, "openpilot": None, "raw": BASE_CONFIG, "colored": COLORED_CONFIG}' in src
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
  assert 'PROFILE = PROFILES["fused"]' in (toyota / "ars510_radar_interface.py").read_text()
  for name, installed in (("anchor", "fused"), ("steady", "fused"), ("stock", "raw"), ("default", "raw"),
                          ("upstream", "openpilot")):  # older names
    r = _install(tmp_path, "--profile", name)
    assert r.returncode == 0 and ("removed" in r.stdout) == (installed == "fused")
    assert f'PROFILE = PROFILES["{installed}"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert _install(tmp_path, "--profile", "openpilot").returncode == 0
  assert 'PROFILE = PROFILES["openpilot"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert (toyota / "ars510_upstream.py").read_text() == (REPO / "upstream" / "ars510_radar.py").read_text()
  r = _install(tmp_path, "--profile", "raw")
  assert r.returncode == 0 and "warning" in r.stdout
  assert 'PROFILE = PROFILES["raw"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert "profile: raw" in _install(tmp_path, "--check").stdout
  assert _install(tmp_path, "--uninstall").returncode == 0
  assert (toyota / "interface.py").read_text() == original
  assert not (toyota / "ars510").exists() and not (toyota / "ars510_radar_interface.py").exists()
  assert not (toyota / "ars510_upstream.py").exists()


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


def _legacy_patch_preimages(patch):
  """Rebuild the old hunk lines from the checked-in patch, with filler between hunks."""
  originals = {}
  path = None
  for line in patch.read_text().splitlines(keepends=True):
    if line.startswith("--- a/"):
      path = Path(line.removeprefix("--- a/").strip())
      originals[path] = []
    elif line.startswith("@@ "):
      match = re.match(r"@@ -(\d+)(?:,\d+)? ", line)
      assert match is not None
      lines = originals[path]
      while len(lines) < int(match[1]) - 1:
        lines.append("# Unchanged fixture line between patch hunks.\n")
    elif path is not None and line.startswith((" ", "-")):
      originals[path].append(line[1:])
  # The installer needs the class declaration, which is outside the patch's
  # actual context lines. These files are patch fixtures, never imported.
  interface = Path("opendbc/car/toyota/interface.py")
  originals[interface].append("\nclass CarInterface:\n  pass\n")
  return {path: "".join(lines) for path, lines in originals.items()}


def test_legacy_upgrade_inside_parent_git_worktree_restores_originals(tmp_path):
  toyota, _ = _fake_opendbc(tmp_path)
  root = tmp_path / "opendbc_repo"
  (tmp_path / "opendbc").symlink_to("opendbc_repo/opendbc")
  patch = REPO / "openpilot" / "legacy" / "opendbc_toyota_ars510_openpilot.patch"
  originals = _legacy_patch_preimages(patch)
  assert set(originals) == {Path("opendbc/car/toyota") / name
                            for name in ("interface.py", "radar_interface.py", "values.py")}
  for path, text in originals.items():
    (root / path).write_text(text)

  # opendbc_repo is vendored inside a Git worktree, with no Git root of its own.
  subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
  subprocess.run(["git", "add", *[str(Path("opendbc_repo") / path) for path in originals]],
                 cwd=tmp_path, check=True, capture_output=True)
  assert not (root / ".git").exists()
  clean = _install(tmp_path, "--check")
  assert clean.returncode == 0, clean.stderr
  assert "older patch-based install: none" in clean.stdout

  # Apply the real legacy fixture from the parent tree with an explicit prefix;
  # a bare git apply from inside opendbc_repo can silently skip these paths.
  subprocess.run(["git", "apply", "--directory=opendbc_repo", str(patch)],
                 cwd=tmp_path, check=True, capture_output=True)
  assert all((root / path).read_text() != text for path, text in originals.items())
  legacy = _install(tmp_path, "--check")
  assert legacy.returncode == 0, legacy.stderr
  assert f"older patch-based install: {patch.name}" in legacy.stdout

  installed = _install(tmp_path)
  assert installed.returncode == 0, installed.stderr
  assert f"replaced the older {patch.name}" in installed.stdout
  text = (toyota / "interface.py").read_text()
  assert text.startswith(originals[Path("opendbc/car/toyota/interface.py")])
  assert text.count("hook_car_interface(CarInterface)") == 1
  for path, original in originals.items():
    if path.name != "interface.py":
      assert (root / path).read_text() == original
  upgraded = _install(tmp_path, "--check")
  assert upgraded.returncode == 0, upgraded.stderr
  assert "older patch-based install: none" in upgraded.stdout

  removed = _install(tmp_path, "--uninstall")
  assert removed.returncode == 0, removed.stderr
  assert all((root / path).read_text() == text for path, text in originals.items())
  assert not (toyota / "ars510").exists()
  assert not (toyota / "ars510_radar_interface.py").exists()


def test_fused_is_raw_plus_range_fusion_and_one_speed_filter_without_relink_or_guard():
  from dataclasses import fields
  from ars510 import FUSED_CONFIG
  diff = {f.name for f in fields(BASE_CONFIG) if getattr(BASE_CONFIG, f.name) != getattr(FUSED_CONFIG, f.name)}
  assert diff == {"range_fusion_gain", "relink_max_gap_s", "drop_saturated_codes", "fused_speed_filter"}
  assert FUSED_CONFIG.range_fusion_gain == 0.1 and not FUSED_CONFIG.drop_saturated_codes
