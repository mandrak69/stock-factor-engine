import argparse
from datetime import datetime
import json
from pathlib import Path
from .report import build_report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Reproducible CURRENT CompoundRank from archived raw evidence')
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--as-of', type=datetime.fromisoformat, default=datetime.fromisoformat('2026-11-20T21:30:00+00:00'))
    parser.add_argument('--previous-as-of', type=datetime.fromisoformat, default=datetime.fromisoformat('2026-11-13T21:30:00+00:00'))
    args = parser.parse_args(argv)
    summary = build_report(args.evidence_dir, as_of=args.as_of, previous_as_of=args.previous_as_of, output=args.output)
    print(json.dumps({key: summary[key] for key in ('scored', 'excluded', 'previous_scored', 'quant500_overlap', 'regime')}, default=str, indent=2))


if __name__ == '__main__':
    main()
