"""Preserve published locale machine IDs with immutable, hash-bound Git proofs.

Aliases are identity compatibility only. They never create another route/tool or
change request, response, admission, pricing or runtime canonical identity.
"""
from __future__ import annotations
import copy
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from compose_openapi import METHODS, digest

KEY = 'x-aisa-identity'
IDENTITY = re.compile(r'[A-Za-z0-9_.-]{1,255}')
FILE = re.compile(r'openapi/(?:zh/)?[A-Za-z0-9_.-]+\.json')
PROOF_FIELDS = {'operation_id', 'locale', 'published_ref', 'source_file', 'source_sha256',
                'public_path', 'method', 'canonical_source_file', 'canonical_source_sha256'}


def operations(document):
    prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield prefix + path, method.upper(), operation


class PublishedHistory:
    """Read only committed source bytes reachable from a fixed publication base."""
    def __init__(self, root, published_ref=None):
        self.root = Path(root)
        self.cache = {}
        self.ancestors = set()
        self.aliases = {}
        self.canonical_ids = set()
        self.ref = published_ref
        if self.ref is None:
            result = self.git('rev-parse', '--verify', 'origin/main', check=False)
            self.ref = result.stdout.strip() if result.returncode == 0 else self.git('rev-parse', 'HEAD').stdout.strip()
        if not re.fullmatch('[0-9a-f]{40}', self.ref):
            raise ValueError('identity history requires a full published Git SHA')

    def git(self, *arguments, check=True):
        return subprocess.run(['git', *arguments], cwd=self.root, capture_output=True, text=True, check=check)

    def read(self, ref, filename):
        if not re.fullmatch('[0-9a-f]{40}', str(ref)) or not FILE.fullmatch(str(filename)):
            raise ValueError('invalid identity history source')
        if ref not in self.ancestors:
            if self.git('merge-base', '--is-ancestor', ref, self.ref, check=False).returncode != 0:
                raise ValueError('identity history is not reachable from publication base')
            self.ancestors.add(ref)
        key = (ref, filename)
        if key not in self.cache:
            raw = subprocess.check_output(['git', 'show', f'{ref}:{filename}'], cwd=self.root, stderr=subprocess.DEVNULL)
            self.cache[key] = (json.loads(raw), hashlib.sha256(raw).hexdigest())
        return self.cache[key]

    def verify(self, canonical, proof):
        if not isinstance(proof, dict) or set(proof) != PROOF_FIELDS:
            raise ValueError('invalid historical identity proof fields')
        if not IDENTITY.fullmatch(str(proof['operation_id'])) or proof['operation_id'] == canonical or proof['locale'] != 'zh':
            raise ValueError('invalid historical locale identity')
        if not proof['source_file'].startswith('openapi/zh/') or proof['canonical_source_file'].startswith('openapi/zh/'):
            raise ValueError('historical identity proof has wrong locale source')
        if proof['method'] not in {method.upper() for method in METHODS}:
            raise ValueError('invalid historical identity method')
        for filename_key, hash_key, expected_id in (
                ('source_file', 'source_sha256', proof['operation_id']),
                ('canonical_source_file', 'canonical_source_sha256', canonical)):
            document, actual_hash = self.read(proof['published_ref'], proof[filename_key])
            if actual_hash != proof[hash_key]:
                raise ValueError('historical identity source hash mismatch')
            matches = [op for path, method, op in operations(document)
                       if (path, method) == (proof['public_path'], proof['method'])]
            if len(matches) != 1 or matches[0].get('operationId') != expected_id:
                raise ValueError('historical identity does not match published source')

    def collect(self):
        files = self.git('ls-tree', '-r', '--name-only', self.ref, '--', 'openapi').stdout.splitlines()
        roots = [filename for filename in files if FILE.fullmatch(filename) and not filename.startswith('openapi/zh/')]
        for filename in roots:
            document, root_hash = self.read(self.ref, filename)
            locale_file = 'openapi/zh/' + Path(filename).name
            locale, locale_hash = self.read(self.ref, locale_file) if locale_file in files else ({}, None)
            localized = {(path, method): op for path, method, op in operations(locale)}
            for path, method, operation in operations(document):
                canonical = operation.get('operationId')
                if not isinstance(canonical, str):
                    continue
                self.canonical_ids.add(canonical)
                existing = operation.get(KEY)
                if existing is not None:
                    validate_metadata(operation, self)
                    self.aliases.setdefault(canonical, []).extend(copy.deepcopy(existing['historical_aliases']))
                    # Keep original immutable proofs; current publication SHA
                    # must not cause every release to rewrite provenance.
                    continue
                old_id = localized.get((path, method), {}).get('operationId')
                if isinstance(old_id, str) and old_id != canonical:
                    proof = dict(operation_id=old_id, locale='zh', published_ref=self.ref,
                        source_file=locale_file, source_sha256=locale_hash,
                        canonical_source_file=filename, canonical_source_sha256=root_hash,
                        public_path=path, method=method)
                    self.verify(canonical, proof)
                    self.aliases.setdefault(canonical, []).append(proof)
        for canonical, aliases in self.aliases.items():
            unique = {json.dumps(alias, sort_keys=True): alias for alias in aliases}
            self.aliases[canonical] = sorted(unique.values(), key=lambda row: row['operation_id'])
        validate_namespace(self.canonical_ids, self.aliases)
        return self


def published_history(root, published_ref=None):
    """Non-Git offline fixtures carry no claim about historical publication."""
    if not (Path(root) / '.git').exists():
        return None
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root, capture_output=True, text=True)
    if result.returncode != 0 or Path(result.stdout.strip()).resolve() != Path(root).resolve():
        return None
    if published_ref is None:
        candidate = subprocess.run(['git', 'rev-parse', '--verify', 'origin/main'], cwd=root, capture_output=True, text=True)
        published_ref = candidate.stdout.strip() if candidate.returncode == 0 else subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    # Only immutable Git source bytes are cached, never current working files.
    return _history_snapshot(str(Path(root).resolve()), published_ref)


@lru_cache(maxsize=16)
def _history_snapshot(root, published_ref):
    return PublishedHistory(root, published_ref).collect()


def validate_namespace(canonical_ids, aliases):
    owners = {}
    for canonical, proofs in aliases.items():
        locale_ids = set()
        for proof in proofs:
            alias = proof['operation_id']
            if alias in canonical_ids:
                raise ValueError('historical identity shadows canonical operation: ' + alias)
            if alias in owners and owners[alias] != canonical:
                raise ValueError('historical identity has conflicting owners: ' + alias)
            owners[alias] = canonical
            locale_ids.add(alias)
        if len(locale_ids) > 1:
            raise ValueError('multiple historical ZH machine identities require explicit disposition: ' + canonical)


def metadata(canonical, proofs):
    value = {'schema_version': 1, 'canonical_operation_id': canonical,
             'historical_aliases': copy.deepcopy(proofs)}
    return {**value, 'sha256': digest(value)}


def validate_metadata(operation, history, *, localized=False):
    value = operation.get(KEY)
    if not isinstance(value, dict) or set(value) != {'schema_version', 'canonical_operation_id', 'historical_aliases', 'sha256'}:
        raise ValueError('invalid identity compatibility metadata')
    canonical = value['canonical_operation_id']
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or not isinstance(canonical, str) or not IDENTITY.fullmatch(canonical) or not isinstance(value['historical_aliases'], list) or not value['historical_aliases']:
        raise ValueError('invalid identity compatibility declaration')
    if value != metadata(canonical, value['historical_aliases']):
        raise ValueError('identity compatibility hash mismatch')
    for proof in value['historical_aliases']:
        history.verify(canonical, proof)
    expected = {proof['operation_id'] for proof in value['historical_aliases']} if localized else {canonical}
    if operation.get('operationId') not in expected:
        raise ValueError('operation ID is not its proved canonical/locale identity')
    validate_namespace({canonical}, {canonical: value['historical_aliases']})
    return canonical


def attach_history(document, history):
    if history is None:
        return
    bindings = {}
    for _, _, operation in operations(document):
        canonical = operation['operationId']
        if canonical in history.aliases:
            operation[KEY] = metadata(canonical, history.aliases[canonical])
            bindings[canonical] = operation[KEY]
        elif KEY in operation:
            raise ValueError('unproved identity metadata cannot enter composition')
    if bindings:
        meta = document.get('info', {}).get('x-aisa-document', {})
        if meta.get('document_hash'):
            base = meta.setdefault('identity_base_document_hash', meta['document_hash'])
            bound = digest(bindings)
            if meta.get('identity_compatibility_hash') != bound:
                meta['identity_compatibility_hash'] = bound
                meta['document_hash'] = digest({'document_hash': base, 'identity_compatibility_hash': bound})


def localize_identities(document):
    result = copy.deepcopy(document)
    for _, _, operation in operations(result):
        if KEY in operation:
            operation['operationId'] = operation[KEY]['historical_aliases'][0]['operation_id']
    return result


def canonicalize_localized(document, history):
    result = copy.deepcopy(document)
    for _, _, operation in operations(result):
        if KEY in operation:
            if history is None:
                raise ValueError('localized identity has no immutable publication history')
            operation['operationId'] = validate_metadata(operation, history, localized=True)
    return result


def validate_document_identities(documents, history):
    canonical_ids, aliases = set(), {}
    for document in documents.values():
        generated = bool(document.get('info', {}).get('x-aisa-document', {}).get('document_hash'))
        bindings = {}
        for _, _, operation in operations(document):
            canonical = operation.get('operationId')
            if canonical:
                canonical_ids.add(canonical)
            if generated and history is not None and canonical in history.aliases and KEY not in operation:
                raise ValueError('published locale identity disappeared: ' + canonical)
            if KEY in operation:
                if history is None:
                    raise ValueError('identity compatibility has no immutable publication history')
                validate_metadata(operation, history)
                proofs = operation[KEY]['historical_aliases']
                if canonical in aliases and aliases[canonical] != proofs:
                    raise ValueError('conflicting historical identity declarations')
                aliases[canonical] = proofs
                bindings[canonical] = operation[KEY]
                if canonical in history.aliases and proofs != history.aliases[canonical]:
                    raise ValueError('published historical identities changed or disappeared')
        meta = document.get('info', {}).get('x-aisa-document', {})
        if generated and (bindings or 'identity_compatibility_hash' in meta):
            if meta.get('identity_compatibility_hash') != digest(bindings):
                raise ValueError('provider identity compatibility hash mismatch')
    validate_namespace(canonical_ids, aliases)
