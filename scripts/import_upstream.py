#!/usr/bin/env python3
"""Import a configured provider OpenAPI source for review; never publishes it."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import urlopen
import yaml
from compose_openapi import digest
from runtime_registry import KEY


def import_source(provider, url):
    if not KEY.fullmatch(provider) or not url.startswith('https://'):
        raise ValueError('provider id and HTTPS source URL are required')
    with urlopen(url, timeout=30) as response:
        raw = response.read()
    document = yaml.safe_load(raw)
    if not isinstance(document, dict) or not str(document.get('openapi', '')).startswith('3.') or not isinstance(document.get('paths'), dict):
        raise ValueError('source is not an OpenAPI 3 document')
    source_hash = digest(document)
    document.setdefault('info', {})['x-aisa-source'] = {
        'kind': 'provider_openapi', 'url': url,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'content_hash': source_hash, 'converter': 'scripts/import_upstream.py@1',
    }
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--provider', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    document = import_source(args.provider, args.url)
    if args.write:
        destination = args.root / 'openapi/upstream' / (args.provider + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'provider': args.provider, 'operations': sum(len([m for m in item if m in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}]) for item in document['paths'].values()), 'source': document['info']['x-aisa-source'], 'written': args.write}))
