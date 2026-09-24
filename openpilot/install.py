#!/usr/bin/env python3
"""Install (or remove) the experimental ARS510 radar-track integration into an opendbc checkout.

    python openpilot/install.py /path/to/openpilot/opendbc_repo            # install
    python openpilot/install.py /path/to/openpilot/opendbc_repo --check    # report state, change nothing
    python openpilot/install.py /path/to/openpilot/opendbc_repo --uninstall

What it writes into <opendbc_repo>:
  opendbc/car/toyota/ars510/                    the decoder package from this repo (copied unchanged)
  opendbc/car/toyota/ars510_radar_interface.py  the RadarInterface used when ToyotaFlags.ARS510_RADAR is set
  opendbc/dbc/ars510_radar_bus.dbc              raw radar-bus frames, for cabana only (not used for parsing)
  opendbc/dbc/ars510_objects_vbus.dbc           reassembled objects on a virtual bus, for cabana only
and applies opendbc_toyota_ars510.patch (Toyota values.py / interface.py / radar_interface.py hooks).
The patch was made against opendbc 4134c0d (openpilot 10b9e73, September 2026); `git apply` refuses if it does not
fit, and nothing is copied in that case.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PATCH = HERE / "opendbc_toyota_ars510.patch"
DBCS = ("ars510_radar_bus.dbc", "ars510_objects_vbus.dbc")


def targets(root: Path) -> dict[str, Path]:
  toyota = root / "opendbc" / "car" / "toyota"
  return {"package": toyota / "ars510", "interface": toyota / "ars510_radar_interface.py",
          **{dbc: root / "opendbc" / "dbc" / dbc for dbc in DBCS}}


def git_apply(root: Path, *args: str) -> bool:
  r = subprocess.run(["git", "apply", *args, str(PATCH)], cwd=root, capture_output=True, text=True)
  return r.returncode == 0


def patch_state(root: Path) -> str:
  if git_apply(root, "--check", "--reverse"):
    return "applied"
  if git_apply(root, "--check"):
    return "not applied"
  return "does not fit this opendbc version"


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("opendbc_repo", type=Path, help="opendbc checkout (the directory that contains opendbc/car)")
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--check", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  args = ap.parse_args()
  root = args.opendbc_repo.resolve()
  if not (root / "opendbc" / "car" / "toyota" / "radar_interface.py").exists():
    print(f"{root} does not look like an opendbc checkout", file=sys.stderr)
    return 2
  t = targets(root)
  state = patch_state(root)

  if args.check:
    print(f"patch: {state}")
    for name, p in t.items():
      print(f"{name}: {'present' if p.exists() else 'missing'} ({p})")
    return 0

  if args.uninstall:
    if state == "applied" and not git_apply(root, "--reverse"):
      print("failed to reverse the patch", file=sys.stderr)
      return 1
    for p in t.values():
      if p.is_dir():
        shutil.rmtree(p)
      elif p.exists():
        p.unlink()
    print("removed")
    return 0

  if state == "does not fit this opendbc version":
    print("opendbc_toyota_ars510.patch does not apply to this checkout; nothing changed", file=sys.stderr)
    return 1
  if state == "not applied" and not git_apply(root):
    print("git apply failed; nothing changed", file=sys.stderr)
    return 1
  if t["package"].exists():
    shutil.rmtree(t["package"])
  shutil.copytree(REPO / "ars510", t["package"], ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
  shutil.copy2(HERE / "ars510_radar_interface.py", t["interface"])
  for dbc in DBCS:
    shutil.copy2(REPO / "dbc" / dbc, t[dbc])
  print(f"installed into {root} (patch was {state})")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
