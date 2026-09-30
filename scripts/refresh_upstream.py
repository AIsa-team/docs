#!/usr/bin/env python3
"""Stage official mirror updates for review, retaining removed published routes."""
import argparse
import copy
import json
from pathlib import Path
from compose_openapi import METHODS, digest
from consolidate_openapi import merge_components
from import_upstream import import_source


def preserve_removed(previous, updated, name):
    removed = [(path, method) for path, item in previous.get('paths', {}).items()
               for method in item if method in METHODS and method not in updated.get('paths', {}).get(path, {})]
    if not removed:
        return updated, []
    result, old = copy.deepcopy(updated), copy.deepcopy(previous)
    merge_components(result, old, name)
    for path, method in removed:
        result.setdefault('paths', {}).setdefault(path, {})[method] = old['paths'][path][method]
        for key in ('parameters', 'servers'):
            if key in old['paths'][path]:
                result['paths'][path].setdefault(key, old['paths'][path][key])
    source = result['info']['x-aisa-source']
    source['retained_operations'] = [f'{method.upper()} {path}' for path, method in removed]
    source['converter'] = 'scripts/refresh_upstream.py@1'
    return result, source['retained_operations']


def refresh(root, fetch=import_source):
    changes, report = {}, {'updated': {}, 'manual': [], 'pinned': {}, 'failed': {}}
    for path in sorted((root / 'openapi/upstream').glob('*.json')):
        previous = json.loads(path.read_text())
        source = previous.get('info', {}).get('x-aisa-source', {})
        if source.get('refresh_policy') == 'pinned':
            report['pinned'][path.stem] = source.get('refresh_reason', 'Explicitly pinned source; review a source revision update separately.')
            continue
        if source.get('kind') != 'provider_openapi' and source.get('refresh_policy') != 'automatic':
            report['manual'].append(path.stem)
            continue
        try:
            updated = fetch(path.stem, source['url'])
            if updated['info']['x-aisa-source']['content_hash'] == source.get('content_hash'):
                continue
            retained, removed = preserve_removed(previous, updated, path.name)
            changes[path] = json.dumps(retained, indent=2, ensure_ascii=False) + '\n'
            report['updated'][path.stem] = {'removed_upstream_but_retained': removed}
        except Exception as exc:
            report['failed'][path.stem] = type(exc).__name__
    return changes, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    changes, report = refresh(args.root)
    if args.write:
        for path, text in changes.items():
            path.write_text(text)
    rendered = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.write_text(rendered)
    print(rendered)
    raise SystemExit(1 if report['failed'] else 0)
