#!/usr/bin/env python3
"""Audit imported request-mirror availability against a public endpoint inventory.

This is a source audit, not evidence of runtime contract projection or validation.
"""
import argparse
import json
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit
import yaml
from runtime_registry import public_mirror_index


def audit(root: Path, inventory: Path):
    mirrors = public_mirror_index(root)
    sources = {}
    rows = []
    category = json.loads((inventory / 'category.json').read_text())
    for entry in category['apis']:
        catalog = entry['id']
        detail = json.loads((inventory / f'{catalog}.json').read_text())
        for group in detail['api'].get('endpoint_groups', []):
            for endpoint in group.get('endpoints', []):
                path = endpoint['path']
                matches = [(method, candidate) for (route, method), candidate in mirrors.items() if route == path]
                errors = [c['operation'].get('x-aisa-mirror-error') for _, c in matches if c['operation'].get('x-aisa-mirror-error')]
                state = 'manual_mirror_available' if matches and not errors else 'mirror_unsupported' if errors else 'mirror_missing'
                row = {'catalog': catalog, 'path': path, 'catalog_method': endpoint.get('method'),
                       'mirror_methods': sorted(m for m, _ in matches), 'status': state,
                       'reason': '; '.join(sorted(set(errors))) if errors else None,
                       'sources': sorted(set(c['source']['url'] for _, c in matches))}
                rows.append(row)
        sources[catalog] = dict(Counter(row['status'] for row in rows if row['catalog'] == catalog))
    return {'scope': 'public inventory versus exact public-route manual request mirrors; catalog methods are not compiled runtime facts',
            'catalogs': len(category['apis']), 'endpoints': len(rows), 'counts': dict(Counter(r['status'] for r in rows)), 'providers': sources, 'operations': rows}


def assign_legacy_sources(root: Path, inventory: Path):
    registry_path = root / 'openapi/registry.yaml'
    registry = yaml.safe_load(registry_path.read_text())
    owners = {catalog: output for output, entry in registry['providers'].items() for catalog in (entry or {}).get('group', [output])}
    route_owners = {}
    for catalog, owner in owners.items():
        detail_path = inventory / f'{catalog}.json'
        if not detail_path.exists():
            continue
        detail = json.loads(detail_path.read_text())
        for group in detail['api'].get('endpoint_groups', []):
            for endpoint in group.get('endpoints', []):
                route_owners.setdefault(endpoint['path'], set()).add(owner)
    for path in sorted((root / 'openapi/upstream').glob('*.json')):
        document = json.loads(path.read_text())
        if document.get('info', {}).get('x-aisa-source', {}).get('path_space') != 'public':
            continue
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        matches = set().union(*(route_owners.get(prefix + route, set()) for route in document.get('paths', {})))
        for owner in matches:
            entry = registry['providers'][owner] or {}
            entry['legacy_sources'] = sorted(set(entry.get('legacy_sources', [])) | {path.stem})
            registry['providers'][owner] = entry
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--assign-legacy-sources', action='store_true')
    args = parser.parse_args()
    if args.assign_legacy_sources:
        assign_legacy_sources(args.root, args.inventory)
    result = audit(args.root, args.inventory)
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text)
