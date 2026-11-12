"""Validate and undo only the documented prose layer for older schema-history tests."""
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compose_openapi import digest


def before_tool_prose_amendment(root, name, document=None):
    root = Path(root)
    document = copy.deepcopy(document if document is not None else json.loads((root / name).read_text()))
    source = document.get('info', {}).get('x-aisa-source', {})
    amendment = source.get('editorial_manifest')
    if not amendment:
        return document
    if amendment.get('path') != 'docs/tool-prose-changes-20261112.json':
        raise ValueError('Unknown prose amendment')
    raw = (root / amendment['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != amendment['sha256']:
        raise ValueError('Prose manifest hash mismatch')
    current = {**document, 'info': {k: v for k, v in document['info'].items() if k != 'x-aisa-source'}}
    if digest(current) != source['content_hash']:
        raise ValueError('Current source content hash mismatch')
    prior = source['prior_source']
    for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
        if source.get(key) != prior.get(key):
            raise ValueError('Source clock or authority changed')
    edits = [row for row in json.loads(raw) if row['source_file'] == str(name)]
    if not edits:
        raise ValueError('Missing prose amendment entries')
    for row in edits:
        if 'pointer' in row:
            pointer = row['pointer']
            if not pointer or pointer[-1] not in ('summary', 'description'):
                raise ValueError('Non-prose amendment pointer')
            node = document
            for part in pointer[:-1]:
                node = node[part]
            if node[pointer[-1]] != row['after']:
                raise ValueError('Declaration prose differs from reviewed change table')
            node[pointer[-1]] = row['before']
            continue
        operation = document['paths'][row['source_path']][row['method']]
        for key in ('summary', 'description'):
            if operation.get(key) != row['after'][key]:
                raise ValueError('Prose differs from reviewed change table')
            if row['before'][key] is None:
                operation.pop(key, None)
            else:
                operation[key] = row['before'][key]
    document['info']['x-aisa-source'] = prior
    if digest(document) != amendment['base_document_hash']:
        raise ValueError('Non-prose source declarations changed')
    return document
