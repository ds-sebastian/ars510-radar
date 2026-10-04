#!/usr/bin/env python3
"""Install (or remove) the ARS510 radar-track integration into openpilot or any fork.

    python openpilot/install.py /data/openpilot                     # install (anchor profile), then reboot
    python openpilot/install.py /data/openpilot --profile steady    # choose another profile
    python openpilot/install.py /data/openpilot --check             # report state, change nothing
    python openpilot/install.py /data/openpilot --uninstall         # remove everything this installer added

The path may be the openpilot checkout or its opendbc_repo. The same install works on openpilot, sunnypilot,
StarPilot and other forks: no fork file is patched in place. The installer
  - copies the decoder package to        opendbc/car/toyota/ars510/
  - copies the radar interface to        opendbc/car/toyota/ars510_radar_interface.py (profile line set)
  - appends one marked block to the end of opendbc/car/toyota/interface.py, which wraps the fork's own
    CarInterface: ARS510 detection in _get_params and dispatch in RadarInterface (see ars510_radar_interface.py)
An install made with an older, patch-based version of this installer is removed first.

Profiles (docs/08 has the details and replay numbers):
  anchor    ANCHOR_CONFIG (default): steady + the radar's own ACC target (0x235) as a velocity anchor
  steady    STEADY_CONFIG: stock + range fusion, far smoothing, far settling, ramp limiter
  stock     OPENPILOT_CONFIG: the plain decode with only what radard needs to run. Velocity excursions reach the
            planner unfiltered (about twice the hard false braking of steady); for research and comparison only
  default   older name for stock, kept so existing installs and instructions keep working
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LEGACY_PATCHES = sorted((HERE / "legacy").glob("*.patch"))
PROFILE_LINE = 'PROFILE = PROFILES["anchor"]'
PROFILE_NAMES = ("anchor", "steady", "stock", "default")
DBCS = ("ars510_radar_bus.dbc", "ars510_objects_vbus.dbc")  # repo dbc/ is for Cabana on a PC; not installed
BEGIN = "# >>> ars510-radar: added by ars510-radar/openpilot/install.py; remove with install.py --uninstall"
END = "# <<< ars510-radar"
HOOK = f"""
{BEGIN}
from opendbc.car.toyota.ars510_radar_interface import hook_car_interface as _ars510_hook_car_interface  # noqa: E402
CarInterface = _ars510_hook_car_interface(CarInterface)
{END}
"""


def find_opendbc(path: Path) -> Path | None:
  """The opendbc checkout: the directory holding the real opendbc/ package. openpilot checkouts have a top-level
  `opendbc` symlink into opendbc_repo; resolve it, so git sees the files where they are tracked."""
  for root in (path / "opendbc_repo", path, path / "opendbc"):
    pkg = root / "opendbc"
    if (pkg / "car" / "toyota" / "interface.py").exists():
      return pkg.resolve().parent
  return None


def targets(root: Path) -> dict[str, Path]:
  toyota = root / "opendbc" / "car" / "toyota"
  return {"package": toyota / "ars510", "interface": toyota / "ars510_radar_interface.py"}


def old_dbcs(root: Path) -> list[Path]:
  """Cabana DBCs that older versions of this installer copied into the fork; parsing never used them."""
  return [p for p in (root / "opendbc" / "dbc" / dbc for dbc in DBCS) if p.exists()]


def git_apply(root: Path, patch: Path, *args: str) -> bool:
  """git apply with paths relative to the opendbc checkout. When opendbc_repo sits inside a larger work tree
  (openpilot vendors it), git would resolve paths from that tree's top and skip files it considers elsewhere while
  still exiting 0. GIT_CEILING_DIRECTORIES stops the search above opendbc_repo, and any skipped file counts as failure."""
  env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(root.resolve().parent)}
  r = subprocess.run(["git", "apply", "-v", *args, str(patch)], cwd=root, env=env, capture_output=True, text=True)
  return r.returncode == 0 and "Skipped patch" not in r.stdout + r.stderr


def legacy_patch(root: Path) -> Path | None:
  """The older patch-based install, if one is applied here."""
  for patch in LEGACY_PATCHES:
    if git_apply(root, patch, "--check", "--reverse"):
      return patch
  return None


def remove_hook(text: str) -> str:
  if BEGIN not in text:
    return text
  head, rest = text.split(BEGIN, 1)
  return head.rstrip("\n") + "\n" + rest.split(END, 1)[1].lstrip("\n")


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("openpilot", type=Path, help="openpilot (or fork) checkout, or its opendbc_repo")
  ap.add_argument("--profile", choices=PROFILE_NAMES, default="anchor")
  ap.add_argument("--flavor", help=argparse.SUPPRESS)  # accepted for old instructions; no longer needed
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--check", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  args = ap.parse_args()
  root = find_opendbc(args.openpilot)
  if root is None:
    print(f"no opendbc/car/toyota/interface.py under {args.openpilot} (or its opendbc_repo)", file=sys.stderr)
    return 2
  t = targets(root)
  interface_py = root / "opendbc" / "car" / "toyota" / "interface.py"
  text = interface_py.read_text()
  legacy = legacy_patch(root)

  if args.check:
    print(f"opendbc: {root}")
    print(f"hook in toyota/interface.py: {'present' if BEGIN in text else 'missing'}")
    print(f"older patch-based install: {legacy.name if legacy else 'none'}")
    if t["interface"].exists():
      txt = t["interface"].read_text()
      prof = next((k for k in PROFILE_NAMES if f'PROFILE = PROFILES["{k}"]' in txt), "unknown")
      print(f"profile: {prof}")
    for name, p in t.items():
      print(f"{name}: {'present' if p.exists() else 'missing'} ({p})")
    for p in old_dbcs(root):
      print(f"leftover from an older install (removed on the next install): {p}")
    return 0

  if legacy is not None and not git_apply(root, legacy, "--reverse"):
    print(f"could not remove the older install ({legacy.name}); nothing changed", file=sys.stderr)
    return 1
  text = remove_hook(interface_py.read_text())
  for p in old_dbcs(root):
    p.unlink()

  if args.uninstall:
    interface_py.write_text(text)
    for p in t.values():
      if p.is_dir():
        shutil.rmtree(p)
      elif p.exists():
        p.unlink()
    print("removed" + (f" (including the older {legacy.name})" if legacy else ""))
    return 0

  if "class CarInterface" not in text:
    print("toyota/interface.py defines no CarInterface; nothing changed", file=sys.stderr)
    return 1
  if t["package"].exists():
    shutil.rmtree(t["package"])
  shutil.copytree(REPO / "ars510", t["package"], ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
  src = (HERE / "ars510_radar_interface.py").read_text()
  assert src.count(PROFILE_LINE) == 1
  t["interface"].write_text(src.replace(PROFILE_LINE, f'PROFILE = PROFILES["{args.profile}"]'))
  interface_py.write_text(text.rstrip("\n") + "\n" + HOOK)
  print(f"installed into {root} ({args.profile} profile" + (f"; replaced the older {legacy.name}" if legacy else "") +
        "). Reboot the device to activate.")
  if args.profile in ("stock", "default"):
    print("warning: the stock profile publishes the plain decode. Velocity excursions (false closings beyond 40 m)\n"
          "reach the planner unfiltered and cause about twice the hard false braking of steady. Use it for research\n"
          "and comparison only; install.py with no --profile installs the recommended anchor profile.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
