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
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

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
