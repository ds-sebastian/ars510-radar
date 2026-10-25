"""Decoder profiles and the generic openpilot / fork installer."""
from __future__ import annotations

import os
import re
from pathlib import Path
import subprocess
import sys
import types
from unittest import mock

from ars510 import BASE_CONFIG

REPO = Path(__file__).resolve().parents[1]


def test_wrapper_has_one_switchable_profile_line_defaulting_to_acc():
  src = (REPO / "openpilot" / "ars510_radar_interface.py").read_text()
  assert src.count('PROFILE = PROFILES["acc"]') == 1
  assert 'PROFILES = {k: k for k in STANDALONE}' in src and 'STANDALONE = {"acc": "ars510_acc_target", "acc_summaries": "ars510_acc_summaries"}' in src
  assert "FUSED_CONFIG" not in src and "BASE_CONFIG" not in src  # no object-list profile reaches openpilot
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
  # the installer records each install's profile; keep that record in the test's directory, out of the repo
  env = {**os.environ, "ARS510_INSTALL_STATE": str(Path(args[0]) / "install_state.json")}
  return subprocess.run([sys.executable, str(REPO / "openpilot" / "install.py"), *map(str, args)], capture_output=True,
                        text=True, env=env)


def test_installer_appends_one_hook_block_and_uninstalls_cleanly(tmp_path):
  toyota, original = _fake_opendbc(tmp_path)
  for _ in range(2):  # re-running replaces, never duplicates
    r = _install(tmp_path)  # the openpilot checkout; opendbc_repo is found inside it
    assert r.returncode == 0, r.stderr
  text = (toyota / "interface.py").read_text()
  assert text.startswith(original) and text.count("hook_car_interface(CarInterface)") == 1
  assert (toyota / "ars510" / "interface.py").exists()
  assert not (tmp_path / "opendbc_repo" / "opendbc" / "dbc" / "ars510_radar_bus.dbc").exists()  # old Cabana copy removed
  assert 'PROFILE = PROFILES["acc"]' in (toyota / "ars510_radar_interface.py").read_text()  # the default
  for name in ("fused", "openpilot", "raw", "shared_speed", "shared_range", "anchor", "steady", "colored", "stock", "default",
               "upstream"):  # the object-list profiles and their older names: acc, with a note
    r = _install(tmp_path, "--profile", name)
    assert r.returncode == 0 and f"'{name}' is no longer installable" in r.stdout
    assert 'PROFILE = PROFILES["acc"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert not any((toyota / f).exists() for f in ("ars510_upstream.py", "ars510_shared_speed.py", "ars510_shared_range.py"))
  acc_target = (REPO / "upstream" / "ars510_acc_target.py").read_text()  # parses the DBC under the installer's own name
  assert (toyota / "ars510_acc_target.py").read_text() == acc_target.replace('RADAR_DBC = "toyota_tss2_ars510"', 'RADAR_DBC = "ars510_acc_target"')
  assert (toyota.parents[1] / "dbc" / "ars510_acc_target.dbc").read_text() == (REPO / "upstream" / "toyota_tss2_ars510.dbc").read_text()
  assert not (toyota.parents[1] / "dbc" / "toyota_tss2_ars510.dbc").exists()
  assert _install(tmp_path, "--profile", "acc_summaries").returncode == 0
  assert 'PROFILE = PROFILES["acc_summaries"]' in (toyota / "ars510_radar_interface.py").read_text()
  assert (toyota / "ars510_acc_summaries.py").read_text() == (REPO / "openpilot" / "standalone" / "ars510_acc_summaries.py").read_text()
  assert "profile: acc_summaries" in _install(tmp_path, "--check").stdout
  assert _install(tmp_path, "--uninstall").returncode == 0
  assert (toyota / "interface.py").read_text() == original
  assert not (toyota / "ars510").exists() and not (toyota / "ars510_radar_interface.py").exists()
  assert not any((toyota / f).exists() for f in ("ars510_acc_target.py", "ars510_acc_summaries.py"))
  assert not (toyota.parents[1] / "dbc" / "ars510_acc_target.dbc").exists()


def test_installer_leaves_opendbcs_own_ars510_dbc(tmp_path):
  """Once commaai/opendbc#3860 is merged, toyota_tss2_ars510.dbc is opendbc's: kept on install and uninstall. Without that,
  the same file is an older install's copy and is removed."""
  toyota, _ = _fake_opendbc(tmp_path)
  dbc = toyota.parents[1] / "dbc" / "toyota_tss2_ars510.dbc"
  dbc.write_text("an older install's copy")
  assert _install(tmp_path).returncode == 0
  assert not dbc.exists()
  (toyota / "values.py").write_text("ARS510 = dbc_dict('toyota_nodsu_pt_generated', 'toyota_tss2_ars510')\n")
  dbc.write_text("opendbc's own")
  r = _install(tmp_path, "--check")
  assert "opendbc ships toyota_tss2_ars510.dbc" in r.stdout and "leftover" not in r.stdout
  for args in ((), ("--profile", "acc_summaries"), ("--uninstall",)):
    assert _install(tmp_path, *args).returncode == 0
    assert dbc.read_text() == "opendbc's own"


def _git(cwd, *args):
  subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def test_installer_never_overwrites_files_the_fork_tracks(tmp_path):
  toyota, original = _fake_opendbc(tmp_path)
  root = tmp_path / "opendbc_repo"
  (toyota / "ars510_acc_target.py").write_text("the fork's own file\n")
  _git(root, "init")
  _git(root, "add", ".")
  _git(root, "commit", "-m", "fork")
  r = _install(tmp_path)
  assert r.returncode == 1 and "ars510_acc_target.py" in r.stderr
  assert (toyota / "ars510_acc_target.py").read_text() == "the fork's own file\n"
  assert (toyota / "interface.py").read_text() == original and not (toyota / "ars510").exists()
  assert "install stops" in _install(tmp_path, "--check").stdout
  r = _install(tmp_path, "--uninstall")
  assert r.returncode == 0 and (toyota / "ars510_acc_target.py").read_text() == "the fork's own file\n"


def test_installer_updates_a_fork_that_commits_the_install(tmp_path):
  toyota, _ = _fake_opendbc(tmp_path)
  root = tmp_path / "opendbc_repo"
  assert _install(tmp_path).returncode == 0
  _git(root, "init")
  _git(root, "add", ".")
  _git(root, "commit", "-m", "fork with the install committed")
  r = _install(tmp_path, "--profile", "acc_summaries")
  assert r.returncode == 0, r.stderr
  assert 'PROFILE = PROFILES["acc_summaries"]' in (toyota / "ars510_radar_interface.py").read_text()


def test_hook_keeps_toyota_importable_when_it_fails():
  import importlib.util
  spec = importlib.util.spec_from_file_location("ars510_install", REPO / "openpilot" / "install.py")
  install = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(install)
  logged = []
  carlog = types.ModuleType("opendbc.car.carlog")
  carlog.carlog = types.SimpleNamespace(exception=logged.append)
  modules = {"opendbc": types.ModuleType("opendbc"), "opendbc.car": types.ModuleType("opendbc.car"), "opendbc.car.carlog": carlog}
  with mock.patch.dict(sys.modules, modules):  # opendbc without the installed interface file: the import fails
    namespace = {"CarInterface": "the fork's CarInterface"}
    exec(install.HOOK, namespace)
  assert namespace["CarInterface"] == "the fork's CarInterface" and "Toyota runs as shipped" in logged[0]


def test_legacy_patches_are_kept_for_upgrades():
  names = {p.name for p in (REPO / "openpilot" / "legacy").glob("*.patch")}
  assert names == {f"opendbc_toyota_ars510_{f}.patch" for f in ("openpilot", "starpilot", "sunnypilot")}


def test_installer_uses_opendbc_repo_behind_the_openpilot_symlink(tmp_path):
  # real openpilot checkouts have a top-level `opendbc` symlink into opendbc_repo
  toyota, _ = _fake_opendbc(tmp_path)
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
  assert diff == {"range_fusion_gain", "relink_max_gap_s", "drop_saturated_codes", "fused_speed_filter", "path_gate_m",
                  "acc_sigma_mps", "far_acc_only_m", "path_gate_stationary_mps"}
  assert FUSED_CONFIG.range_fusion_gain == 0.1 and not FUSED_CONFIG.drop_saturated_codes
  assert FUSED_CONFIG.acc_sigma_mps == 0.13  # docs/12: ACC weight (0.3 in 2.5)
  assert FUSED_CONFIG.far_acc_only_m == 60.0  # docs/12: far cars beyond 60 m, since 2.6
