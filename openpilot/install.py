#!/usr/bin/env python3
"""Install (or remove) the ARS510 radar-track integration into openpilot or any fork.

    python openpilot/install.py /data/openpilot                     # install (acc profile, the default), then reboot
    python openpilot/install.py /data/openpilot --profile raw       # the unfiltered decode, for comparison
    python openpilot/install.py /data/openpilot                     # reinstall / update: keeps the installed profile
    python openpilot/install.py /data/openpilot --check             # report the state only
    python openpilot/install.py /data/openpilot --uninstall         # remove everything this installer added

The path may be the openpilot checkout or its opendbc_repo. The same install works on openpilot, sunnypilot,
StarPilot, CarrotPilot and other forks: the installer adds new files and one marked block to the fork. The installer
  - copies the decoder package to        opendbc/car/toyota/ars510/
  - copies the radar interface to        opendbc/car/toyota/ars510_radar_interface.py (profile line set)
  - copies the openpilot version to      opendbc/car/toyota/ars510_upstream.py (used by --profile openpilot)
  - copies the ACC-target file to        opendbc/car/toyota/ars510_acc_target.py (used by --profile acc)
    and its DBC to                       opendbc/dbc/ars510_acc_target.dbc (a name of its own: opendbc's
    toyota_tss2_ars510.dbc, once commaai/opendbc#3860 is merged, stays opendbc's and as shipped)
  - copies the acc_summaries file to    opendbc/car/toyota/ars510_acc_summaries.py (--profile acc_summaries)
  - copies two research files to         opendbc/car/toyota/ars510_shared_{speed,range}.py (--profile shared_speed / shared_range)
  - appends one marked block to the end of opendbc/car/toyota/interface.py, which wraps the fork's own
    CarInterface: ARS510 detection in _get_params and dispatch in RadarInterface (see ars510_radar_interface.py)
An install made with an older, patch-based version of this installer is removed first. Files the fork's git tracks
are never overwritten or removed: an install whose file names the fork already ships stops before changing anything.

Profiles (docs/08 has the details and replay numbers):
  acc       (default, opendbc-compatible) the radar's ACC target alone as one point (upstream/ars510_acc_target.py with
            toyota_tss2_ars510.dbc): the car Toyota's own ACC follows; every other car comes from the camera. It
            publishes a target as soon as the radar picks it; fused holds new tracks back for 60 cycles (docs/11)
  acc_summaries  acc plus up to two more cars from the radar's own tracker (the target summaries 0x191-0x194, within
            40 m, speed from their range slope); the main alternative: radar-backed cut-ins slightly earlier,
            braking as acc in replay (docs/11)
  fused     FUSED_CONFIG: the radar decode + range fusion + one Kalman speed filter per track that weights
            the object list and the radar's ACC target by their own uncertainty, with a path gate (= the openpilot version); every radar car within 60 m
  raw       BASE_CONFIG: the unfiltered radar decode with only what radard
            needs to run. Velocity excursions reach the planner unfiltered; for research and comparison only
  openpilot fused in one file (upstream/ars510_radar.py, opendbc style), driving identically, points with trackId /
            dRel / yRel / vRel only. The all-tracks upstream alternative; the proposal is acc
  Also tried, set aside (installable for research; docs/17): shared_speed / shared_range (every object and the ACC
  target through one gate-free Kalman model)

Legacy names are aliases: anchor/steady/colored select fused, upstream selects openpilot,
and stock/default select raw. Every alias prints its selection.

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
PROFILE_NAMES = ("acc", "acc_summaries", "fused", "openpilot", "raw", "shared_speed", "shared_range")
LEGACY_NAMES = {"anchor": "fused", "steady": "fused", "colored": "fused", "stock": "raw", "default": "raw", "upstream": "openpilot"}
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


def targets(root: Path) -> dict[str, Path]:
  toyota = root / "opendbc" / "car" / "toyota"
  return {"package": toyota / "ars510", "interface": toyota / "ars510_radar_interface.py",
          "upstream": toyota / "ars510_upstream.py", "acc_target": toyota / "ars510_acc_target.py",
          "shared_speed": toyota / "ars510_shared_speed.py", "shared_range": toyota / "ars510_shared_range.py",
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
          "upstream": REPO / "upstream" / "ars510_radar.py", "acc_target": REPO / "upstream" / "ars510_acc_target.py",
          "shared_speed": HERE / "standalone" / "ars510_shared_speed.py",
          "shared_range": HERE / "standalone" / "ars510_shared_range.py",
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
  """The profile set in the installed interface file (legacy names mapped), or None without a readable install."""
  if not t["interface"].exists():
    return None
  txt = t["interface"].read_text()
  prof = next((k for k in PROFILE_NAMES + tuple(LEGACY_NAMES) if f'PROFILE = PROFILES["{k}"]' in txt), None)
  return LEGACY_NAMES.get(prof, prof)


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
  recorded = recorded if recorded in PROFILE_NAMES else None
  previous = current or recorded
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
  ap.add_argument("--profile", choices=PROFILE_NAMES + tuple(LEGACY_NAMES),
                  metavar="{" + ",".join(PROFILE_NAMES) + "}",
                  help="default: the installed profile on a reinstall, acc on a first install; legacy aliases also accepted")
  ap.add_argument("--flavor", help=argparse.SUPPRESS)  # accepted for old instructions; ignored
  g = ap.add_mutually_exclusive_group()
  g.add_argument("--check", action="store_true")
  g.add_argument("--uninstall", action="store_true")
  args = ap.parse_args()
  if args.profile in LEGACY_NAMES:
    new = LEGACY_NAMES[args.profile]
    retired = {"anchor": "the tuned profile was removed; ", "steady": "the tuned profile was removed; ",
               "colored": "the colored-noise profile was removed; "}.get(args.profile, "")
    print(f"note: {retired}'{args.profile}' is an alias for '{new}'; the recommended default is '{DEFAULT_PROFILE}'")
    args.profile = new
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
      prof = next((k for k in PROFILE_NAMES + tuple(LEGACY_NAMES) if f'PROFILE = PROFILES["{k}"]' in txt), "other")
      print(f"profile: {prof}")
    print("install.py without --profile installs: " + choose_profile(None, t, root)[1].removeprefix("profile: "))
    for name, p in t.items():
      print(f"{name}: {'present' if p.exists() else 'to be installed'} ({p})")
    for p in old_dbcs(root):
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
  for p in old_dbcs(root):
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
  shutil.copyfile(REPO / "upstream" / "ars510_radar.py", t["upstream"])
  acc_target = (REPO / "upstream" / "ars510_acc_target.py").read_text()
  assert acc_target.count(ACC_DBC_LINE) == 1
  t["acc_target"].write_text(acc_target.replace(ACC_DBC_LINE, ACC_DBC_INSTALLED))
  shutil.copyfile(REPO / "upstream" / "toyota_tss2_ars510.dbc", t["acc_dbc"])
  for name in ("acc_summaries", "shared_speed", "shared_range"):
    shutil.copyfile(HERE / "standalone" / f"ars510_{name}.py", t[name])
  src = (HERE / "ars510_radar_interface.py").read_text()
  assert src.count(PROFILE_LINE) == 1
  t["interface"].write_text(src.replace(PROFILE_LINE, f'PROFILE = PROFILES["{args.profile}"]'))
  interface_py.write_text(text.rstrip("\n") + "\n" + HOOK)
  record_profile(root, args.profile)
  print(f"installed into {root} ({args.profile} profile" + (f"; replaced the older {legacy.name}" if legacy else "") +
        "). Reboot the device to activate.")
  if args.profile in ("shared_speed", "shared_range"):
    print("warning: a research profile. The object list's slow, correlated errors reach the planner: replays ask for hard\n"
          "radar-only braking 7-21 times as often as fused (docs/17). Keep to research use.")
  if args.profile == "raw":
    print("warning: the raw profile publishes the unfiltered radar decode. Velocity excursions (false closings beyond 40 m)\n"
          "reach the planner unfiltered: 93 hard radar-only braking ticks on the held-out replay routes against 16 for fused and\n"
          "14 for acc (docs/11). Use it for research and comparison; --profile acc installs the default.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
