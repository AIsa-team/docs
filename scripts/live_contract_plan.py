#!/usr/bin/env python3
"""Decide whether the Docs contract mirrors need a rebuild.

The input key combines three hashes, so a tick with nothing new is a no-op:
- the live Services contract content: the sorted "name sha256" pairs listed by
  /public/api-contract/current, excluding generation and other metadata;
- the live category content (/info/apis/category without cached_at), which
  the generator also reads;
- Docs' own generator inputs: every tracked file except the generated mirror
  outputs, with openapi/registry.yaml counted as an input.

Network failures are retried and then reported with exit status 2, so the
workflow can warn and try again on the next tick.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

CURRENT = '/public/api-contract/current'
CATEGORY = '/info/apis/category'
HEX64 = re.compile(r'[0-9a-f]{64}')
# Paths the compose job writes and commits. Everything else that Git tracks is a
# generator input; registry.yaml is both and counts as an input.
OUTPUTS = ('openapi/', 'api-reference/', 'zh/api-reference/', 'docs.json', 'llms.txt',
           'openapi.yaml', 'docs/publication/', 'discovery/payment-evidence.json',
           'discovery/openapi.json')
INPUT_OVERRIDES = ('openapi/registry.yaml',)
MAX_BYTES = 16 << 20


class Unavailable(Exception):
    """The live contract could not be read; retry on the next tick."""


def fetch(base_url, path, attempts=3, timeout=30, sleep=time.sleep):
    opener = build_opener(ProxyHandler({}))
    last = None
    for attempt in range(attempts):
        try:
            request = Request(base_url.rstrip('/') + path, headers={'Accept': 'application/json'})
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise Unavailable(path + ' exceeds the byte limit')
            return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            if attempt + 1 < attempts:
                sleep(5 * (attempt + 1))
    raise Unavailable(f'{path}: {type(last).__name__}')


def content_hash(index):
    """sha256 over the sorted "name sha256" lines of every listed file."""
    files = index.get('files') if isinstance(index, dict) else None
    if not isinstance(files, list) or not files:
        raise ValueError('contract index lists no files')
    rows = set()
    for row in files:
        name, digest = (row.get('name'), row.get('sha256')) if isinstance(row, dict) else (None, None)
        if not isinstance(name, str) or not name or not HEX64.fullmatch(str(digest)):
            raise ValueError('invalid contract index entry')
        rows.add((name, digest))
    if len(rows) != len(files) or len({name for name, _ in rows}) != len(rows):
        raise ValueError('duplicate contract index entry')
    digest = hashlib.sha256()
    for name, sha in sorted(rows):
        digest.update(f'{name} {sha}\n'.encode())
    return digest.hexdigest()


def category_hash(category):
    """Same content rule as fetch_runtime_release.category_content."""
    if not isinstance(category, dict) or not isinstance(category.get('apis'), list):
        raise ValueError('invalid category response')
    content = {key: value for key, value in category.items() if key != 'cached_at'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def is_input(path):
    return path in INPUT_OVERRIDES or not path.startswith(OUTPUTS)


def docs_inputs(root):
    listing = subprocess.check_output(['git', 'ls-tree', '-r', 'HEAD'], cwd=root, text=True, timeout=120)
    kept = [line for line in listing.splitlines() if is_input(line.split('\t', 1)[1])]
    return hashlib.sha256(('\n'.join(kept) + '\n').encode()).hexdigest()


def input_key(contract, category, docs):
    return hashlib.sha256(f'contract {contract}\ncategory {category}\ndocs {docs}\n'.encode()).hexdigest()


def plan(index, category, docs):
    contract, live_category = content_hash(index), category_hash(category)
    return {'input_key': input_key(contract, live_category, docs), 'contract_hash': contract,
            'category_hash': live_category, 'docs_inputs': docs,
            'artifact_revision': index.get('artifact_revision', ''),
            'generation': index.get('generation', 0)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://api.aisa.one')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--github-output', type=Path, help='append key=value outputs for GitHub Actions')
    args = parser.parse_args(argv)
    try:
        result = plan(fetch(args.base_url, CURRENT), fetch(args.base_url, CATEGORY), docs_inputs(args.root))
    except Unavailable as exc:
        print(json.dumps({'available': False, 'reason': str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    if args.github_output:
        with args.github_output.open('a') as output:
            for key in ('input_key', 'contract_hash', 'artifact_revision', 'generation'):
                output.write(f'{key}={result[key]}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
