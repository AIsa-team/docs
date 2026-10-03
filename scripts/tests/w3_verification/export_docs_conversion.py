#!/usr/bin/env python3
"""Export actual Docs OAS3.0 conversion results for the immutable W0 oracle.

Only oracle identity/source pointers select input. Expected values are never
used to produce actual output. The frozen verifier performs the comparison.
"""
import argparse
import json
from pathlib import Path
import sys


def pointer(document, path):
    value = document
    for token in path.lstrip('/').split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixtures-root', type=Path, default=Path(__file__).resolve().parents[1] /
                        'api-contract-acceptance/fixtures')
    args = parser.parse_args()
    sys.path.insert(0, str(args.docs_root / 'scripts'))
    import compose_openapi
    fixtures = args.fixtures_root
    cases = json.loads((fixtures / 'public-contract-3.0.expected.json').read_text())['consumer_expectations']
    actual = {}
    for case in cases:
        source = json.loads((fixtures / case['source_ref']['file']).read_text())
        actual[case['id']] = compose_openapi.schema_30_to_31(pointer(source, case['source_ref']['pointer']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(actual, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
