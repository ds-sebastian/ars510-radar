"""The parts ledger (docs/10, data/analysis/summaries/openpilot_file_parts.json) must add up to the openpilot file: a PR
that changes upstream/ars510_radar.py's code lines has to update its row."""
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def code_lines(path: Path) -> int:
  src = path.read_text()
  doc = set()
  for n in ast.walk(ast.parse(src)):
    if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
        and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
      doc.update(range(n.body[0].lineno, n.body[0].end_lineno + 1))
  return sum(1 for i, line in enumerate(src.split("\n"), 1) if line.strip() and not line.strip().startswith("#") and i not in doc)


def test_ledger_matches_the_openpilot_file():
  ledger = json.loads((REPO / "data/analysis/summaries/openpilot_file_parts.json").read_text())
  n = code_lines(REPO / "upstream/ars510_radar.py")
  assert ledger["file_code_lines"] == n, f"upstream/ars510_radar.py has {n} code lines; update the parts ledger"
  assert sum(p["code_lines"] for p in ledger["parts"]) == n
  docs = (REPO / "docs/10_research_directions.md").read_text()
  assert all(f"| {p['part']} | {p['code_lines']} |" in docs for p in ledger["parts"])
