"""Lossless interning of large publication provenance, never schema evidence removal."""
import copy
import hashlib
import json
import re

KEY = 'x-aisa-source-provenance'
PREFIX = '#/info/' + KEY + '/'
# Small identities remain inline for existing readers. Repeated reference-page
# evidence can dwarf the actual contract, so store that evidence once.
MIN_BYTES = 16_384
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace', 'x-aisa-any'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def source_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_slots(document):
    for item in document.get('paths', {}).values():
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            if isinstance(operation.get('x-aisa-source'), dict):
                yield operation, 'x-aisa-source'
            response = operation.get('x-aisa-response-source', {})
            if isinstance(response, dict) and isinstance(response.get('source'), dict):
                yield response, 'source'


def validate_map(document):
    entries = document.get('info', {}).get(KEY, {})
    if not isinstance(entries, dict):
        raise ValueError('invalid provenance map')
    for digest, source in entries.items():
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or not isinstance(source, dict) or source_hash(source) != digest:
            raise ValueError('provenance digest mismatch')
    return entries


def expand_source(source, document):
    if 'provenance_ref' not in source and 'provenance_sha256' not in source:
        return copy.deepcopy(source)
    digest = source.get('provenance_sha256')
    if not isinstance(digest, str) or source.get('provenance_ref') != PREFIX + digest:
        raise ValueError('invalid provenance locator')
    full = document.get('info', {}).get(KEY, {}).get(digest)
    if not isinstance(full, dict) or source_hash(full) != digest:
        raise ValueError('missing or altered provenance')
    summary = {k: v for k, v in source.items() if k not in {'provenance_ref', 'provenance_sha256'}}
    expected = {k: v for k, v in full.items() if not isinstance(v, (dict, list))}
    if summary != expected:
        raise ValueError('provenance identity summary mismatch')
    return copy.deepcopy(full)


def validate_document(document):
    validate_map(document)
    for parent, key in source_slots(document):
        expand_source(parent[key], document)


def merge_provenance(target, source):
    entries = validate_map(source)
    if not entries:
        return
    dest = target.setdefault('info', {}).setdefault(KEY, {})
    for digest, value in entries.items():
        if digest in dest and dest[digest] != value:
            raise ValueError('provenance hash collision')
        dest[digest] = copy.deepcopy(value)


def compact_document(document):
    """Intern large source records in place; repeat calls are idempotent."""
    validate_document(document)
    for parent, key in source_slots(document):
        source = parent[key]
        if 'provenance_ref' in source or len(canonical(source)) < MIN_BYTES:
            continue
        digest = source_hash(source)
        document.setdefault('info', {}).setdefault(KEY, {})[digest] = copy.deepcopy(source)
        parent[key] = {k: copy.deepcopy(v) for k, v in source.items() if not isinstance(v, (dict, list))}
        parent[key].update(provenance_ref=PREFIX + digest, provenance_sha256=digest)
    validate_document(document)
    return document


def expand_document(document):
    """Rehydrate publication metadata for audit/equality checks."""
    validate_document(document)
    result = copy.deepcopy(document)
    for parent, key in source_slots(result):
        parent[key] = expand_source(parent[key], document)
    result.get('info', {}).pop(KEY, None)
    return result
