#!/usr/bin/env python3
"""Compare actual consumer adapters plus actual Docs conversion to frozen W0.

Each supplied native result is assessed independently. This coordinates actual
exports; it does not infer native results from producer input or expected graphs.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs-root', type=Path, required=True)
    parser.add_argument('--native-output', action='append', required=True, metavar='LABEL=PATH')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--acceptance-root', type=Path, default=Path(__file__).resolve().parents[2],
                        help='Root of the unchanged W0 package, which may be a public test fixture checkout')
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('--output-dir must be a new directory')
    args.output_dir.mkdir(parents=True)
    scripts = Path(__file__).resolve().parent
    docs_path = args.output_dir / 'docs-conversion.json'
    subprocess.run([sys.executable, str(scripts / 'export_docs_conversion.py'),
                    '--docs-root', str(args.docs_root), '--output', str(docs_path),
                    '--fixtures-root', str(args.acceptance_root / 'scripts/api-contract-acceptance/fixtures')], check=True)
    conversion = json.loads(docs_path.read_text())
    results = {}
    for entry in args.native_output:
        label, separator, filename = entry.partition('=')
        if not separator or not re.fullmatch('[a-z][a-z0-9_-]*', label) or label in results:
            parser.error('native output must have a unique safe LABEL=PATH')
        native = json.loads(Path(filename).read_text())
        if not isinstance(native, dict) or len(native) != 20 or set(native) & set(conversion):
            parser.error('native output must contain 18 native cases and two negative cases, without Docs conversion')
        actual_path = args.output_dir / (label + '-actual.json')
        actual_path.write_text(json.dumps({**native, **conversion}, indent=2, sort_keys=True) + '\n')
        verifier = args.acceptance_root / 'scripts/api-contract-acceptance/verify.py'
        run = subprocess.run([sys.executable, str(verifier), '--consumer-output', str(actual_path)],
                             capture_output=True, text=True)
        (args.output_dir / (label + '-verifier.log')).write_text(run.stdout + run.stderr)
        results[label] = {'status': 'passed' if run.returncode == 0 else 'failed',
                          'exit_code': run.returncode, 'actual_output': actual_path.name,
                          'scope': 'actual adapter output plus actual Docs conversion against immutable W0'}
    report = {'status': 'passed' if all(r['status'] == 'passed' for r in results.values()) else 'failed',
              'consumers': results, 'production_activation': 'not_assessed'}
    (args.output_dir / 'receipt.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
