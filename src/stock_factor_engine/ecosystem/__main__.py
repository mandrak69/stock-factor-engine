import argparse
import json
from pathlib import Path
from .report import build_report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evidence-based AI relationship map; not consolidated accounts')
    parser.add_argument('--registry',type=Path,default=Path('research/ai-ecosystem'))
    parser.add_argument('--output',type=Path,default=Path('data/reports/ai-ecosystem-2026-11-20'))
    parser.add_argument('--as-of')
    args = parser.parse_args(argv)
    print(json.dumps(build_report(args.registry,args.output,args.as_of),default=str,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
