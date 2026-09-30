#!/usr/bin/env python3
"""Fail if tracked text files contain identifiers of a real car, drive or person.

    python tools/check_privacy.py            # scan every file git tracks (what CI runs)
    python tools/check_privacy.py FILE ...   # scan specific files

Drives in this repo are anonymised (A/B/C, D1-D4, relative times). This blocks what usually leaks when results are
exported from a research workspace: openpilot route and dongle IDs, Toyota VINs, GPS coordinates, local home paths,
device paths and private IP addresses. A line that must contain a match (for example this file's own patterns) can
end with `privacy-ok`.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".gz", ".parquet", ".zst", ".bz2", ".pdf", ".pyc"}
PATTERNS = {  # privacy-ok
  "openpilot route id": re.compile(r"\b[0-9a-f]{8}--[0-9a-f]{10}\b"),  # privacy-ok
  "openpilot route name (date form)": re.compile(r"\b\d{4}-\d{2}-\d{2}--\d{2}-\d{2}-\d{2}\b"),  # privacy-ok
  # 16 hex characters with both a digit and a letter, not a decimal fraction; the replay harness's fixed fake dongle
  # id a510a510a510a510 is allowed
  "dongle id": re.compile(r"(?<![0-9a-fA-F.])(?!(?:a510){4})(?=[0-9a-f]{0,15}[a-f])(?=[0-9a-f]{0,15}\d)[0-9a-f]{16}(?![0-9a-fA-F])"),  # privacy-ok
  "Toyota VIN": re.compile(r"\b(?:JT|2T|4T|5T|JT)[A-HJ-NPR-Z0-9]{15}\b"),  # privacy-ok
  "GPS coordinate field": re.compile(r"[\"']?(?:latitude|longitude|lat|lon|lng)[\"']?\s*[:=]\s*-?\d+\.\d{3,}", re.I),  # privacy-ok
  "local home path": re.compile(r"(?:/home/|/Users/|[A-Z]:\\Users\\)[A-Za-z0-9_.-]+"),  # privacy-ok
  "device recording path": re.compile(r"/data/media/0/realdata"),  # privacy-ok
  "private IP address": re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"),  # privacy-ok
}


def tracked_files() -> list[Path]:
  out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
  return [REPO / p for p in out.splitlines()]


def scan(paths: list[Path]) -> list[str]:
  hits = []
  for path in paths:
    if path.suffix.lower() in BINARY or not path.is_file():
      continue
    try:
      text = path.read_text()
    except UnicodeDecodeError:
      continue
    for n, line in enumerate(text.splitlines(), 1):
      if line.rstrip().endswith("privacy-ok"):
        continue
      for name, pat in PATTERNS.items():
        m = pat.search(line)
        if m:
          rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
          hits.append(f"{rel}:{n}: {name}: {m.group(0)[:40]}")
  return hits


def main() -> int:
  paths = [Path(p).resolve() for p in sys.argv[1:]] or tracked_files()
  hits = scan(paths)
  for h in hits:
    print(h)
  print(f"privacy check: {len(hits)} finding(s) in {len(paths)} file(s)")
  return 1 if hits else 0


if __name__ == "__main__":
  raise SystemExit(main())
