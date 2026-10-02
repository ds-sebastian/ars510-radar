#!/usr/bin/env python3
"""Label allocation placeholders while preserving every row of a slots table."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slots', type=Path, nargs='?', default=REPO / 'data/analysis/slots.parquet')
    parser.add_argument('--output', type=Path, help='default: update the input table')
    parser.add_argument('--summary', type=Path, help='write anonymised dataset counts')
    args = parser.parse_args()
    frame = pd.read_parquet(args.slots)
    # The existing decoder withholds age-1 slots whose length and width codes
    # are both zero. Keep them available for raw transport/lifecycle analysis.
    frame['init_template'] = frame['age'].eq(1) & frame['UNK_56_7'].eq(0) & frame['UNK_216_6'].eq(0)
    assert frame.init_template.notna().all()
    output = args.output or args.slots
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.parquet', delete=False) as temporary:
        path = Path(temporary.name)
    try:
        frame.to_parquet(path, index=False)
        os.replace(path, output)
    finally:
        path.unlink(missing_ok=True)
    counts = dict(rows=len(frame), init_template_rows=int(frame.init_template.sum()),
        non_template_rows=int((~frame.init_template).sum()),
        rule='age == 1 and UNK_56_7 == 0 and UNK_216_6 == 0',
        by_drive={str(drive): dict(rows=len(group), init_template_rows=int(group.init_template.sum()))
            for drive, group in frame.groupby('drive', sort=True)},
        preserves_original_rows_and_columns=True)
    text = json.dumps(counts, indent=2) + '\n'
    if args.summary:
        args.summary.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
