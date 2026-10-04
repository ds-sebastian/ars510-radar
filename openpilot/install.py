#!/usr/bin/env python3
"""Install (or remove) the ARS510 radar-track integration into openpilot or any fork.

    python openpilot/install.py /data/openpilot                     # install (fused profile), then reboot
    python openpilot/install.py /data/openpilot --profile raw       # the unfiltered decode, for comparison
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
  fused     FUSED_CONFIG (default): the radar decode + range fusion + one Kalman speed filter per track that weights
            the object list, the radar's ACC target and its summaries by their own uncertainty
  raw       BASE_CONFIG: the unfiltered radar decode (not vision-only, not stock openpilot) with only what radard
            needs to run. Velocity excursions reach the planner unfiltered; for research and comparison only
  anchor, steady   earlier tuned profiles, outperformed by fused and removed: they install fused (with a notice)
  stock, default   older names for raw
  openpilot the upstream version (upstream/ars510_radar.py, one file in opendbc style): the slimmest filter that
            keeps fused's driving, points with trackId / dRel / yRel / vRel only. For driving the merge candidate
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
PROFILE_LINE = 'PROFILE = PROFILES["fused"]'
PROFILE_NAMES = ("fused", "openpilot", "raw")
LEGACY_NAMES = {"anchor": "fused", "steady": "fused", "stock": "raw", "default": "raw", "upstream": "openpilot"}
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
  return {"package": toyota / "ars510", "interface": toyota / "ars510_radar_interface.py",
          "upstream": toyota / "ars510_upstream.py"}


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
  ap.add_argument("--profile", choices=PROFILE_NAMES + tuple(LEGACY_NAMES), default="fused")
  ap.add_argument("--flavor", help=argparse.SUPPRESS)  # accepted for old instructions; no longer needed
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--check", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  args = ap.parse_args()
  if args.profile in LEGACY_NAMES:
    new = LEGACY_NAMES[args.profile]
    if new == "fused":
      print(f"note: the {args.profile} profile was outperformed by fused and has been removed; installing fused")
    args.profile = new
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
      prof = next((k for k in PROFILE_NAMES + tuple(LEGACY_NAMES) if f'PROFILE = PROFILES["{k}"]' in txt), "unknown")
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
  shutil.copyfile(REPO / "upstream" / "ars510_radar.py", t["upstream"])
  src = (HERE / "ars510_radar_interface.py").read_text()
  assert src.count(PROFILE_LINE) == 1
  t["interface"].write_text(src.replace(PROFILE_LINE, f'PROFILE = PROFILES["{args.profile}"]'))
  interface_py.write_text(text.rstrip("\n") + "\n" + HOOK)
  print(f"installed into {root} ({args.profile} profile" + (f"; replaced the older {legacy.name}" if legacy else "") +
        "). Reboot the device to activate.")
  if args.profile == "raw":
    print("warning: the raw profile publishes the unfiltered radar decode. Velocity excursions (false closings beyond 40 m)\n"
          "reach the planner unfiltered and cause about three times the hard false braking of fused. Use it for research\n"
          "and comparison only; install.py with no --profile installs the recommended fused profile.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
