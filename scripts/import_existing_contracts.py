#!/usr/bin/env python3
"""Import committed AIsa contracts as explicitly manual public-route mirrors."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
from compose_openapi import digest


def import_existing(root: Path, revision: str = 'HEAD') -> dict:
    commit = subprocess.check_output(['git', 'rev-parse', revision], cwd=root, text=True).strip()
    observed = subprocess.check_output(['git', 'show', '-s', '--format=%cI', commit], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-tree', '--name-only', f'{commit}:openapi'], cwd=root, text=True).splitlines()
    changes = {}
    for name in names:
        if not name.endswith('.json') or name in {'openapi.json', 'pending.json', 'coverage.json', 'coverage-sources.json'}:
            continue
        raw = subprocess.check_output(['git', 'show', f'{commit}:openapi/{name}'], cwd=root, text=True)
        source = json.loads(raw)
        if source.get('info', {}).get('x-aisa-document', {}).get('document_hash'):
            raise ValueError(f'{name}: choose a pre-projection revision for manual import')
        document = copy.deepcopy(source)
        document['info']['x-aisa-source'] = {
            'kind': 'manual', 'url': f'https://github.com/AIsa-team/docs/blob/{commit}/openapi/{name}',
            'fetched_at': observed, 'content_hash': digest(source),
            'converter': 'scripts/import_existing_contracts.py@1', 'path_space': 'public',
        }
        changes[root / 'openapi/upstream' / name] = json.dumps(document, indent=2, ensure_ascii=False) + '\n'
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    changes = import_existing(args.root, args.revision)
    if args.write:
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print(json.dumps({'manual_mirrors': len(changes), 'written': args.write}))
