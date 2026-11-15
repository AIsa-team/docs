#!/usr/bin/env python3
"""Capture the gateway's public catalog declarations at one immutable revision.

Spec #1285 R1: the sync-paid gateway's public declarations are no longer
pinned. This writes the capture consumed by ``prepare_treg_public_reference``:
every ``src/treg/catalog/*.yaml`` file at the resolved revision with its
SHA256 and git blob id, and every declared operation bound to its file.

No provider API is called. Only the public source repository is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

REPOSITORY = 'superdesigndev/treg'
CATALOG_DIRECTORY = 'src/treg/catalog'
GIT_URL = 'https://github.com/' + REPOSITORY + '.git'
REVISION = re.compile(r'[0-9a-f]{40}')
USER_AGENT = 'AIsa-contract-source-importer'


def raw_base(revision):
    if not REVISION.fullmatch(revision or ''):
        raise ValueError('a full 40-hex source revision is required')
    return 'https://raw.githubusercontent.com/' + REPOSITORY + '/' + revision + '/'


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def resolve_revision(ref='main', runner=subprocess.check_output):
    """Resolve a branch to its current commit with git ls-remote (no API quota)."""
    output = runner(['git', 'ls-remote', GIT_URL, 'refs/heads/' + ref], text=True, timeout=60)
    revisions = {line.split()[0] for line in output.splitlines() if line.strip()}
    if len(revisions) != 1 or not REVISION.fullmatch(next(iter(revisions))):
        raise ValueError('source branch did not resolve to exactly one revision')
    return revisions.pop()


def http_get(url, timeout=30):
    headers = {'User-Agent': USER_AGENT}
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token and url.startswith('https://api.github.com/'):
        headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        return response.read()


def list_catalog(revision, get=http_get):
    url = ('https://api.github.com/repos/' + REPOSITORY + '/contents/' + CATALOG_DIRECTORY
           + '?ref=' + quote(revision))
    entries = json.loads(get(url))
    if not isinstance(entries, list):
        raise ValueError('catalog listing is not a directory')
    return sorted(entry['path'] for entry in entries
                  if entry.get('type') == 'file' and entry.get('path', '').endswith('.yaml'))


def capture(revision, get=http_get, *, acquired_at=None, paths=None):
    """Return (capture, {file name: raw bytes}) for one immutable revision."""
    base = raw_base(revision)
    files, raw_files, operations = [], {}, {}
    for path in paths if paths is not None else list_catalog(revision, get):
        if not path.startswith(CATALOG_DIRECTORY + '/') or '/' in path[len(CATALOG_DIRECTORY) + 1:]:
            raise ValueError('catalog file outside the declared directory')
        raw = get(base + path)
        name = Path(path).name
        raw_files[name] = raw
        entry = {'path': path, 'url': base + path, 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': git_blob(raw)}
        files.append(entry)
        document = yaml.safe_load(raw)
        if not isinstance(document, dict):
            continue
        for operation in document.get('endpoints') or []:
            identity = operation.get('id')
            if not isinstance(identity, str) or identity in operations:
                raise ValueError('missing or duplicate upstream operation ID')
            operations[identity] = {'operation': json.loads(json.dumps(operation, default=str)),
                                    'source': {'url': entry['url'], 'git_blob': entry['git_blob'],
                                               'sha256': entry['sha256']}}
    result = {'schema_version': 1, 'repository': REPOSITORY, 'revision': revision,
              'acquired_at': acquired_at or datetime.now(timezone.utc).isoformat(),
              'files': files, 'operations': operations}
    return result, raw_files


def encode(document):
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()


def write(output, document, raw_files):
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in raw_files.items():
        (output / name).write_bytes(raw)
    raw = encode(document)
    (output / 'capture.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', help='Full source revision (default: current main)')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    revision = args.revision or resolve_revision()
    document, raw_files = capture(revision)
    digest = write(args.output_dir, document, raw_files)
    print(json.dumps({'revision': revision, 'files': len(document['files']),
                      'operations': len(document['operations']), 'capture_sha256': digest}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
