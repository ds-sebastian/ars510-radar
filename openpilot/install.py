#!/usr/bin/env python3
"""Install (or remove) the ARS510 radar-track integration into openpilot or any fork.

    python openpilot/install.py /data/openpilot                     # install (acc profile, the default), then reboot
    python openpilot/install.py /data/openpilot --profile acc_summaries   # acc plus the two target-summary cars
    python openpilot/install.py /data/openpilot                     # reinstall / update: keeps the installed profile
    python openpilot/install.py /data/openpilot --check             # report the state only
    python openpilot/install.py /data/openpilot --uninstall         # remove everything this installer added

The path may be the openpilot checkout or its opendbc_repo. The same install works on openpilot, sunnypilot,
StarPilot, CarrotPilot and other forks: the installer adds new files and one marked block to the fork. The installer
  - copies the decoder package to        opendbc/car/toyota/ars510/ (constants, PCS alarm, fault flag)
  - copies the radar interface to        opendbc/car/toyota/ars510_radar_interface.py (profile line set)
  - copies the ACC-target file to        opendbc/car/toyota/ars510_acc_target.py (used by both profiles)
    and its DBC to                       opendbc/dbc/ars510_acc_target.dbc (a name of its own: opendbc's
    toyota_tss2_ars510.dbc, once commaai/opendbc#3860 is merged, stays opendbc's and as shipped)
  - copies the acc_summaries file to    opendbc/car/toyota/ars510_acc_summaries.py (--profile acc_summaries)
  - appends one marked block to the end of opendbc/car/toyota/interface.py, which wraps the fork's own
    CarInterface: ARS510 detection in _get_params and dispatch in RadarInterface (see ars510_radar_interface.py)
An install made with an older, patch-based version of this installer is removed first, and so are the files older
versions installed for the object-list profiles (ars510_upstream.py, ars510_shared_{speed,range}.py). Files the fork's git tracks
are never overwritten or removed: an install whose file names the fork already ships stops before changing anything.

Profiles (docs/08 has the details and replay numbers):
  acc       (default, opendbc-compatible) the radar's ACC target alone as one point (upstream/ars510_acc_target.py with
            toyota_tss2_ars510.dbc): the car Toyota's own ACC follows; every other car comes from the camera. It
            publishes a target as soon as the radar picks it (docs/11)
  acc_summaries  acc plus up to two more cars from the radar's own tracker (the target summaries 0x191-0x194, within
            40 m); for forks: radar-backed cut-ins slightly earlier, braking as acc in replay (docs/11)

The object-list profiles (fused, openpilot, raw, shared_speed, shared_range, and their older names) are not installable:
the object list's speeds have excursions, mostly false closings beyond 40 m, that reach the planner (docs/07). Asking for
one, or reinstalling over one, installs acc and says so.

Without --profile, a reinstall keeps the profile installed before: the one in the installed interface file, or, when a
fork update has removed the install, the one this checkout last installed into the same path (recorded in
openpilot/.installed_profiles.json, which git ignores). A first install gets the recommended acc default.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_PROFILE = "acc"
# The profile last installed into each opendbc path, so a reinstall after a fork update (which removes the installed
# files) keeps it. Lives in this checkout, outside the fork; ARS510_INSTALL_STATE overrides the path (tests).
STATE = Path(os.environ.get("ARS510_INSTALL_STATE", HERE / ".installed_profiles.json"))
LEGACY_PATCHES = sorted((HERE / "legacy").glob("*.patch"))
PROFILE_LINE = 'PROFILE = PROFILES["acc"]'
PROFILE_NAMES = ("acc", "acc_summaries")
# Object-list profiles of older versions (and their older names): asked for, or found installed, they install acc.
REMOVED_PROFILES = ("fused", "openpilot", "raw", "shared_speed", "shared_range", "anchor", "steady", "colored", "stock",
                    "default", "upstream")
REMOVED_NOTE = ("note: '{}' is no longer installable (object-list speed excursions reach the planner, docs/07); "
                "installing acc")
DBCS = ("ars510_radar_bus.dbc", "ars510_objects_vbus.dbc")  # repo dbc/ serves Cabana on a PC and stays in the repo
# The acc DBC is upstream's toyota_tss2_ars510.dbc, installed under its own name so the acc profiles keep parsing with
# this checkout's signals whatever opendbc ships under the upstream name. Older installs copied it to the upstream name.
FORK_DBC = "toyota_tss2_ars510.dbc"
ACC_DBC_LINE = 'RADAR_DBC = "toyota_tss2_ars510"'
ACC_DBC_INSTALLED = 'RADAR_DBC = "ars510_acc_target"'
BEGIN = "# >>> ars510-radar: added by ars510-radar/openpilot/install.py; remove with install.py --uninstall"
END = "# <<< ars510-radar"
# A hook that fails (a fork or opendbc change it does not fit) leaves Toyota as shipped instead of breaking its import.
HOOK = f"""
{BEGIN}
try:
  from opendbc.car.toyota.ars510_radar_interface import hook_car_interface as _ars510_hook_car_interface  # noqa: E402
  CarInterface = _ars510_hook_car_interface(CarInterface)
except Exception:
  from opendbc.car.carlog import carlog  # noqa: E402
  carlog.exception("ARS510: hook not installed, Toyota runs as shipped; run ars510-radar/openpilot/install.py again")
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


# Files older versions installed for the object-list profiles: removed on install and uninstall.
OLD_FILES = ("ars510_upstream.py", "ars510_shared_speed.py", "ars510_shared_range.py")


def targets(root: Path) -> dict[str, Path]:
  toyota = root / "opendbc" / "car" / "toyota"
  return {"package": toyota / "ars510", "interface": toyota / "ars510_radar_interface.py",
          "acc_target": toyota / "ars510_acc_target.py",
          "acc_summaries": toyota / "ars510_acc_summaries.py",
          "acc_dbc": root / "opendbc" / "dbc" / "ars510_acc_target.dbc"}


def tracked(root: Path, paths) -> set[Path]:
  """The paths (files, or directories holding files) the fork's git tracks: files the fork or opendbc ship. Empty
  without git."""
  paths = list(paths)
  try:
    r = subprocess.run(["git", "ls-files", "-z", "--", *map(str, paths)], cwd=root, capture_output=True, text=True, check=False)
  except OSError:
    return set()
  if r.returncode != 0:
    return set()
  files = {(root / f).resolve() for f in r.stdout.split("\0") if f}
  return {p for p in paths if any(f == p.resolve() or p.resolve() in f.parents for f in files)}


def fork_dbc_owned(root: Path) -> bool:
  """Whether toyota_tss2_ars510.dbc is opendbc's own (commaai/opendbc#3860 merged) rather than an older install's copy."""
  values = root / "opendbc" / "car" / "toyota" / "values.py"
  dbc = root / "opendbc" / "dbc" / FORK_DBC
  return (values.exists() and "toyota_tss2_ars510" in values.read_text()) or bool(tracked(root, [dbc]))


def old_dbcs(root: Path) -> list[Path]:
  """DBCs that older versions of this installer copied into the fork: the Cabana DBCs (parsing reads the decoder package
  alone) and the acc DBC under the upstream name, unless opendbc now ships that file itself."""
  old = [root / "opendbc" / "dbc" / dbc for dbc in DBCS]
  if not fork_dbc_owned(root):
    old.append(root / "opendbc" / "dbc" / FORK_DBC)
  return [p for p in old if p.exists()]


def old_files(root: Path) -> list[Path]:
  """Object-list profile files an older version of this installer copied in, unless the fork's git tracks them."""
  toyota = root / "opendbc" / "car" / "toyota"
  found = [toyota / f for f in OLD_FILES if (toyota / f).exists()]
  keep = tracked(root, found)
  return [p for p in found if p not in keep]


def conflicts(root: Path, t: dict[str, Path], text: str) -> list[Path]:
  """Targets the fork's git tracks, which an install would overwrite. A fork that commits this install (the hook block
  in its committed interface.py) owns copies of these files and gets them updated."""
  owned = sorted(tracked(root, [p for p in t.values() if p.exists()]))
  if owned and BEGIN in text:
    interface = Path("opendbc") / "car" / "toyota" / "interface.py"
    r = subprocess.run(["git", "show", f"HEAD:./{interface.as_posix()}"], cwd=root, capture_output=True, text=True, check=False)
    if r.returncode == 0 and BEGIN in r.stdout:
      return []
  return owned


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


def sources() -> dict[str, Path]:
  """What each target is copied from (the interface file differs from its source only by the profile line)."""
  return {"package": REPO / "ars510", "interface": HERE / "ars510_radar_interface.py",
          "acc_target": REPO / "upstream" / "ars510_acc_target.py",
          "acc_summaries": HERE / "standalone" / "ars510_acc_summaries.py",
          "acc_dbc": REPO / "upstream" / "toyota_tss2_ars510.dbc"}


def stale(t: dict[str, Path]) -> list[str]:
  """Installed targets that differ from this checkout: an install made with an older (or newer) ars510-radar."""
  out = []
  for name, src in sources().items():
    dst = t[name]
    if not dst.exists():
      continue
    if src.is_dir():
      files = sorted(p.relative_to(src) for p in src.rglob("*.py"))
      if files != sorted(p.relative_to(dst) for p in dst.rglob("*.py")) or \
         any((src / f).read_bytes() != (dst / f).read_bytes() for f in files):
        out.append(name)
    elif name == "interface":
      txt = dst.read_text()
      prof = next((k for k in PROFILE_NAMES if f'PROFILE = PROFILES["{k}"]' in txt), None)
      if prof is None or txt.replace(f'PROFILE = PROFILES["{prof}"]', PROFILE_LINE) != src.read_text():
        out.append(name)
    elif name == "acc_target":
      if dst.read_text() != src.read_text().replace(ACC_DBC_LINE, ACC_DBC_INSTALLED):
        out.append(name)
    elif src.read_bytes() != dst.read_bytes():
      out.append(name)
  return out


def installed_profile(t: dict[str, Path]) -> str | None:
  """The profile set in the installed interface file (a removed object-list profile included), or None without a
  readable install."""
  if not t["interface"].exists():
    return None
  txt = t["interface"].read_text()
  return next((k for k in PROFILE_NAMES + REMOVED_PROFILES if f'PROFILE = PROFILES["{k}"]' in txt), None)


def read_state() -> dict[str, str]:
  try:
    state = json.loads(STATE.read_text())
  except (OSError, ValueError):
    return {}
  return state if isinstance(state, dict) else {}


def record_profile(root: Path, profile: str | None) -> None:
  """Remember (or, with None, forget) the profile installed into root. Best effort: a read-only checkout only loses
  the fallback for reinstalling after a fork update."""
  state = read_state()
  if profile is None:
    if str(root) not in state:
      return
    state.pop(str(root))
  else:
    state[str(root)] = profile
  try:
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
  except OSError as e:
    print(f"note: could not record the profile in {STATE} ({e})")


def choose_profile(requested: str | None, t: dict[str, Path], root: Path) -> tuple[str, str]:
  """The profile to install and one line saying which and why: requested, kept from the existing install, kept from
  this checkout's record of the last install into this path, or the default."""
  current = installed_profile(t)
  recorded = read_state().get(str(root))
  recorded = recorded if recorded in PROFILE_NAMES + REMOVED_PROFILES else None
  previous = current or recorded
  if requested is None and previous in REMOVED_PROFILES:
    return DEFAULT_PROFILE, (f"profile: {DEFAULT_PROFILE} (replaces the installed '{previous}', which is no longer installable: "
                             "object-list speed excursions reach the planner, docs/07)")
  if requested is not None:
    line = f"profile: {requested} (requested with --profile)"
    if previous is not None and previous != requested:
      line += f"\nnote: --profile changes the profile from {previous} to {requested}"
    return requested, line
  if current is not None:
    return current, f"profile: {current} (kept from the existing install; pass --profile to change it)"
  if recorded is not None:
    return recorded, (f"profile: {recorded} (kept from the last install into this path, which a fork update removed; "
                      "pass --profile to change it)")
  return DEFAULT_PROFILE, f"profile: {DEFAULT_PROFILE} (the default; no earlier install found)"


def remove_hook(text: str) -> str:
  if BEGIN not in text:
    return text
  head, rest = text.split(BEGIN, 1)
  return head.rstrip("\n") + "\n" + rest.split(END, 1)[1].lstrip("\n")


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("openpilot", type=Path, help="openpilot (or fork) checkout, or its opendbc_repo")
  ap.add_argument("--profile", choices=PROFILE_NAMES + REMOVED_PROFILES,
                  metavar="{" + ",".join(PROFILE_NAMES) + "}",
                  help="default: the installed profile on a reinstall, acc on a first install; removed profile names install acc")
  ap.add_argument("--flavor", help=argparse.SUPPRESS)  # accepted for old instructions; ignored
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--check", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  args = ap.parse_args()
  if args.profile in REMOVED_PROFILES:
    print(REMOVED_NOTE.format(args.profile))
    args.profile = DEFAULT_PROFILE
  root = find_opendbc(args.openpilot)
  if root is None:
    print(f"expected opendbc/car/toyota/interface.py under {args.openpilot} (or its opendbc_repo)", file=sys.stderr)
    return 2
  t = targets(root)
  interface_py = root / "opendbc" / "car" / "toyota" / "interface.py"
  text = interface_py.read_text()
  legacy = legacy_patch(root)
  owned = conflicts(root, t, text)
  if owned and not args.check and not args.uninstall:
    print("the fork's git tracks files this installer would overwrite; the checkout stays as it was:\n  " +
          "\n  ".join(map(str, owned)) + "\nupdate ars510-radar (git pull) or report it as an issue", file=sys.stderr)
    return 1

  if args.check:
    print(f"opendbc: {root}")
    print(f"hook in toyota/interface.py: {'present' if BEGIN in text else 'to be installed'}")
    print(f"older patch-based install: {legacy.name if legacy else 'none'}")
    if t["interface"].exists():
      txt = t["interface"].read_text()
      prof = next((k for k in PROFILE_NAMES + REMOVED_PROFILES if f'PROFILE = PROFILES["{k}"]' in txt), "other")
      print(f"profile: {prof}" + (" (no longer installable; install.py replaces it with acc)" if prof in REMOVED_PROFILES else ""))
    print("install.py without --profile installs: " + choose_profile(None, t, root)[1].removeprefix("profile: "))
    for name, p in t.items():
      print(f"{name}: {'present' if p.exists() else 'to be installed'} ({p})")
    for p in old_dbcs(root) + old_files(root):
      print(f"leftover from an older install (removed on the next install): {p}")
    if fork_dbc_owned(root):
      print(f"opendbc ships {FORK_DBC} (left as shipped; the acc profiles parse ars510_acc_target.dbc)")
    for p in conflicts(root, t, text):
      print(f"shipped by the fork under an installer name (install stops): {p}")
    if t["interface"].exists():
      diff = stale(t)
      print("installed files: " + ("match this checkout" if not diff else
            f"differ from this checkout ({', '.join(diff)}); run install.py again, then reboot"))
    return 0

  if legacy is not None and not git_apply(root, legacy, "--reverse"):
    print(f"could not remove the older install ({legacy.name}); the checkout stays as it was", file=sys.stderr)
    return 1
  text = remove_hook(interface_py.read_text())
  for p in old_dbcs(root) + old_files(root):
    p.unlink()

  if args.uninstall:
    interface_py.write_text(text)
    keep = tracked(root, [p for p in t.values() if p.exists()])
    for p in sorted(keep):
      print(f"left as shipped by the fork: {p}")
    for p in t.values():
      if p in keep:
        continue
      if p.is_dir():
        shutil.rmtree(p)
      elif p.exists():
        p.unlink()
    record_profile(root, None)
    print("removed" + (f" (including the older {legacy.name})" if legacy else ""))
    return 0

  if "class CarInterface" not in text:
    print("expected a CarInterface class in toyota/interface.py; the checkout stays as it was", file=sys.stderr)
    return 1
  args.profile, line = choose_profile(args.profile, t, root)
  print(line)
  if t["package"].exists():
    shutil.rmtree(t["package"])
  shutil.copytree(REPO / "ars510", t["package"], ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
  acc_target = (REPO / "upstream" / "ars510_acc_target.py").read_text()
  assert acc_target.count(ACC_DBC_LINE) == 1
  t["acc_target"].write_text(acc_target.replace(ACC_DBC_LINE, ACC_DBC_INSTALLED))
  shutil.copyfile(REPO / "upstream" / "toyota_tss2_ars510.dbc", t["acc_dbc"])
  shutil.copyfile(HERE / "standalone" / "ars510_acc_summaries.py", t["acc_summaries"])
  src = (HERE / "ars510_radar_interface.py").read_text()
  assert src.count(PROFILE_LINE) == 1
  t["interface"].write_text(src.replace(PROFILE_LINE, f'PROFILE = PROFILES["{args.profile}"]'))
  interface_py.write_text(text.rstrip("\n") + "\n" + HOOK)
  record_profile(root, args.profile)
  print(f"installed into {root} ({args.profile} profile" + (f"; replaced the older {legacy.name}" if legacy else "") +
        "). Reboot the device to activate.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
