"""upstream/toyota_routing.patch (car-model routing in a fork's opendbc) must keep matching upstream/ars510_radar.py."""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_patch_imports_what_the_upstream_file_defines():
  patch = (REPO / "upstream" / "toyota_routing.patch").read_text()
  assert "+from opendbc.car.toyota.ars510_radar import RadarInterface as Ars510RadarInterface" in patch
  assert "ARS510_RADAR = 'toyota_tss2_ars510'" in patch
  # the ARS510 car must not get a CAN parser for the radar name (it is not a DBC file)
  assert "self.ars510 is not None else _create_radar_can_parser(CP)" in patch
  tree = ast.parse((REPO / "upstream" / "ars510_radar.py").read_text())
  cls = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
  init = next(f for f in cls["RadarInterface"].body if isinstance(f, ast.FunctionDef) and f.name == "__init__")
  assert init.args.vararg is not None  # forks pass CP_SP as well as CP
