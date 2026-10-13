"""The opendbc integration in openpilot/: install into a copy of a stock opendbc, self-check, uninstall.

Needs an opendbc checkout and a Python with pycapnp, e.g. openpilot's venv:
    ARS510_OPENDBC=$OP/opendbc_repo ARS510_OPENDBC_PYTHON=$OP/.venv/bin/python pytest tests/test_openpilot_integration.py
Skipped when those are not set. Only the copy is modified.
"""
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OPENDBC = os.environ.get("ARS510_OPENDBC")
PYTHON = os.environ.get("ARS510_OPENDBC_PYTHON", sys.executable)


def test_integration_files_compile() -> None:
    for f in ("ars510_radar_interface.py", "install.py", "check_integration.py"):
        py_compile.compile(str(REPO / "openpilot" / f), doraise=True)


@pytest.mark.skipif(not OPENDBC, reason="set ARS510_OPENDBC (and ARS510_OPENDBC_PYTHON) to an opendbc checkout")
def test_install_check_uninstall(tmp_path: Path) -> None:
    dst = tmp_path / "opendbc_repo"
    shutil.copytree(OPENDBC, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"), symlinks=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "ARS510_INSTALL_STATE": str(tmp_path / "state.json")}

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([*args], cwd=REPO, env=env, capture_output=True, text=True)

    before = (dst / "opendbc/car/toyota/interface.py").read_text()
    r = run(sys.executable, "openpilot/install.py", str(dst))
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(PYTHON, "openpilot/check_integration.py", "--opendbc", str(dst))
    assert r.returncode == 0 and "ALL OK" in r.stdout, r.stdout + r.stderr
    r = run(sys.executable, "openpilot/install.py", str(dst), "--uninstall")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dst / "opendbc/car/toyota/interface.py").read_text() == before
    assert not (dst / "opendbc/car/toyota/ars510").exists()


def stub_opendbc(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal opendbc layout the installer accepts, and the install-state file the tests point it at."""
    root = tmp_path / "opendbc_repo"
    toyota = root / "opendbc/car/toyota"
    toyota.mkdir(parents=True)
    (root / "opendbc/dbc").mkdir()
    (toyota / "interface.py").write_text("class CarInterface:\n  pass\n")
    return root, tmp_path / "state.json"


def installer(root: Path, state: Path):
    def run(*args: str) -> str:
        env = {**os.environ, "ARS510_INSTALL_STATE": str(state)}
        r = subprocess.run([sys.executable, "openpilot/install.py", str(root), *args], cwd=REPO, env=env,
                           capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    return run


def installed(root: Path) -> str:
    txt = (root / "opendbc/car/toyota/ars510_radar_interface.py").read_text()
    return txt.split('PROFILE = PROFILES["', 1)[1].split('"', 1)[0]


def test_check_reports_an_outdated_install(tmp_path: Path) -> None:
    """--check tells an install from this checkout apart from one made with another ars510-radar version."""
    root, state = stub_opendbc(tmp_path)
    toyota = root / "opendbc/car/toyota"
    run = installer(root, state)

    run("--profile", "fused")
    assert "installed files: match this checkout" in run("--check")
    old = toyota / "ars510_radar_interface.py"
    old.write_text(old.read_text().replace("def detect(", "def detect_old("))
    (toyota / "ars510/objects.py").write_text("# older\n")
    assert "differ from this checkout (package, interface); run install.py again" in run("--check")
    run()
    assert "installed files: match this checkout" in run("--check")


def test_first_install_gets_the_default(tmp_path: Path) -> None:
    root, state = stub_opendbc(tmp_path)
    out = installer(root, state)()
    assert "profile: acc (the default; no earlier install found)" in out
    assert installed(root) == "acc"


def test_reinstall_keeps_the_installed_profile(tmp_path: Path) -> None:
    """The issue #66 case: an update script re-runs install.py without --profile on a fused install."""
    root, state = stub_opendbc(tmp_path)
    run = installer(root, state)
    assert "note:" not in run("--profile", "fused")
    out = run()
    assert "profile: fused (kept from the existing install; pass --profile to change it)" in out
    assert installed(root) == "fused"
    assert "install.py without --profile installs: fused (kept from the existing install" in run("--check")


def test_reinstall_after_a_fork_update_keeps_the_profile(tmp_path: Path) -> None:
    """A fork update resets the checkout (installed files and hook gone); the record in this checkout keeps the profile."""
    root, state = stub_opendbc(tmp_path)
    run = installer(root, state)
    run("--profile", "raw")
    shutil.rmtree(root)
    stub_opendbc(tmp_path)
    out = run()
    assert "profile: raw (kept from the last install into this path, which a fork update removed" in out
    assert installed(root) == "raw"


def test_explicit_profile_changes_it_with_a_note(tmp_path: Path) -> None:
    root, state = stub_opendbc(tmp_path)
    run = installer(root, state)
    run("--profile", "fused")
    out = run("--profile", "acc")
    assert "profile: acc (requested with --profile)" in out
    assert "note: --profile changes the profile from fused to acc" in out
    assert "kept from the existing install" in run() and installed(root) == "acc"


def test_legacy_name_in_the_installed_file_is_kept_as_its_profile(tmp_path: Path) -> None:
    root, state = stub_opendbc(tmp_path)
    run = installer(root, state)
    run("--profile", "fused")
    iface = root / "opendbc/car/toyota/ars510_radar_interface.py"
    iface.write_text(iface.read_text().replace('PROFILES["fused"]', 'PROFILES["anchor"]'))
    assert "profile: fused (kept from the existing install" in run()


def test_uninstall_forgets_the_profile(tmp_path: Path) -> None:
    root, state = stub_opendbc(tmp_path)
    run = installer(root, state)
    run("--profile", "fused")
    run("--uninstall")
    assert "profile: acc (the default; no earlier install found)" in run()
