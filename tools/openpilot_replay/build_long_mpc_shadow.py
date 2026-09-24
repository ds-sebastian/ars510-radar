#!/usr/bin/env python3
"""Build openpilot's longitudinal MPC solver OUTSIDE the openpilot checkout, for offline replay.

A source checkout that has not been built with scons has `long_mpc.py` but not its generated acados solver,
and building it in place modifies the checkout. This copies `long_mpc.py` unchanged into
`<out>/longitudinal_mpc_lib/`, runs its code generation there, and compiles the solver and Cython wrapper the
way the checkout's SConscript does. `replay_radard.py --mpc-shadow <out>` prepends that directory to
`openpilot.selfdrive.controls.lib.__path__`, so openpilot's unmodified `LongitudinalPlanner` imports it.
If your checkout is already built (scons), you do not need this.

  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$OP $OP/.venv/bin/python build_long_mpc_shadow.py --openpilot $OP --out op_shadow
Tested against openpilot 10b9e73 (September 2026); the file list may change in other versions.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import argparse


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("+", " ".join(cmd)[:200])
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--openpilot", type=Path, required=True, help="openpilot checkout root")
    ap.add_argument("--out", type=Path, default=Path("op_shadow"))
    args = ap.parse_args()
    pkg = args.openpilot / "openpilot" if (args.openpilot / "openpilot" / "selfdrive").exists() else args.openpilot
    SRC = pkg / "selfdrive/controls/lib/longitudinal_mpc_lib"
    DEST = args.out.resolve() / "longitudinal_mpc_lib"
    import acados
    import numpy as np
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("long_mpc.py", "__init__.py"):
        shutil.copy2(SRC / name, DEST / name)
    gen = DEST / "c_generated_code"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ACADOS_SOURCE_DIR=acados.DIR,
               ACADOS_PYTHON_INTERFACE_PATH=acados.TEMPLATE_DIR, TERA_PATH=acados.TERA_PATH)
    run([sys.executable, "long_mpc.py"], cwd=DEST, env=env)  # code generation into DEST/c_generated_code

    inc = [acados.INCLUDE_DIR, os.path.join(acados.INCLUDE_DIR, "blasfeo", "include"), os.path.join(acados.INCLUDE_DIR, "hpipm", "include")]
    for lib in ["libacados.so", "libblasfeo.so", "libhpipm.so", "libqpOASES_e.so.3.1"]:
        shutil.copy2(Path(acados.LIB_DIR) / lib, gen / lib)
    if not (gen / "libqpOASES_e.so").exists():
        (gen / "libqpOASES_e.so").symlink_to("libqpOASES_e.so.3.1")
    sources = ["acados_solver_long.c", "long_model/long_expl_ode_fun.c", "long_model/long_expl_vde_forw.c"]
    sources += [f"long_cost/long_cost_y{s}_{f}.c" for s in ("", "_e", "_0") for f in ("fun", "fun_jac_ut_xt", "hess")]
    sources += ["long_constraints/long_constr_h_fun.c", "long_constraints/long_constr_h_fun_jac_uxt_zt.c"]
    cflags = ["-O2", "-fPIC", "-DACADOS_WITH_QPOASES", "-Wno-unused"] + [f"-I{d}" for d in inc] + [f"-I{gen}"]
    run(["gcc", "-shared", *cflags, "-o", str(gen / "libacados_ocp_solver_long.so"), *[str(gen / s) for s in sources],
         f"-L{gen}", "-lacados", "-lhpipm", "-lblasfeo", "-lqpOASES_e", "-lm", "-Wl,--disable-new-dtags", "-Wl,-rpath,$ORIGIN"], cwd=gen)

    tpl = Path(acados.TEMPLATE_DIR)
    run([sys.executable, "-m", "cython", "-o", str(gen / "acados_ocp_solver_pyx.c"), "-I", str(gen), "-I", str(tpl),
         str(tpl / "acados_ocp_solver_pyx.pyx")], cwd=gen, env=env)
    run(["gcc", "-shared", "-pthread", "-fPIC", "-O2", "-Wno-cpp", "-Wno-unused", f"-I{sysconfig.get_paths()['include']}", f"-I{np.get_include()}",
         *[f"-I{d}" for d in inc], f"-I{gen}", "-o", str(gen / "acados_ocp_solver_pyx.so"), str(gen / "acados_ocp_solver_pyx.c"),
         f"-L{gen}", "-lacados_ocp_solver_long", "-Wl,--disable-new-dtags", "-Wl,-rpath,$ORIGIN"], cwd=gen)

    receipt = {"source": str(SRC / "long_mpc.py"), "source_sha256": hashlib.sha256((SRC / "long_mpc.py").read_bytes()).hexdigest(),
               "copy_sha256": hashlib.sha256((DEST / "long_mpc.py").read_bytes()).hexdigest(), "acados": acados.DIR, "numpy": np.__version__}
    (DEST / "build_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
