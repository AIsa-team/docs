#!/usr/bin/env python3
"""Reproduce the pinned official beta events contract without changing its route."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from compose_openapi import digest

SOURCE_URL = 'https://raw.githubusercontent.com/parallel-web/parallel-llms-txt/8b7c637e75390bf1588eabc3a646dca1080719e4/public/docs/docs-legacy-openapi.json.md'
OPERATION_PATH = '/v1beta/tasks/runs/{run_id}/events'


def extract(source):
    """Keep the exact operation and all transitively referenced components."""
    original = json.loads(source)
    item = original['paths'][OPERATION_PATH]
    if set(item) != {'get'} or 'text/event-stream' not in item['get']['responses']['200']['content']:
        raise ValueError('official beta events contract has changed shape')
    document = {key: deepcopy(original[key]) for key in ('openapi', 'info', 'servers', 'security') if key in original}
    document['paths'] = {OPERATION_PATH: deepcopy(item)}
    components = document['components'] = {}

    def visit(value):
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and value.startswith('#/components/'):
            parts = value.split('/')
            if len(parts) != 4:
                raise ValueError('unsupported component reference')
            _, _, section, name = parts
            selected = components.setdefault(section, {})
            if name not in selected:
                selected[name] = deepcopy(original['components'][section][name])
                visit(selected[name])

    visit(document['paths'])
    for scheme in document.get('security', []):
        for name in scheme:
            components.setdefault('securitySchemes', {})[name] = deepcopy(original['components']['securitySchemes'][name])
    document['info']['x-aisa-source'] = {
        'kind': 'provider_openapi', 'url': SOURCE_URL,
        'content_hash': digest(document),
        'source_sha256': 'sha256:' + hashlib.sha256(source).hexdigest(),
        'converter': 'scripts/import_parallel_legacy_events.py@1',
        'selected_paths': [OPERATION_PATH],
        'source_revision': '8b7c637e75390bf1588eabc3a646dca1080719e4',
        'lifecycle': 'legacy',
        'note': 'Exact archived beta route; its presence does not prove current authenticated service availability.',
    }
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Use a previously fetched official source')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    source = args.source.read_bytes() if args.source else urlopen(Request(SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
    document = extract(source)
    if args.write:
        destination = Path(__file__).resolve().parents[1] / 'openapi/upstream/parallel-legacy-events.json'
        destination.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'operations': 1, 'source': document['info']['x-aisa-source'], 'written': args.write}))
