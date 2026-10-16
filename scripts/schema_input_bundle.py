"""Offline integrity/replay checks for explicitly pinned schema inputs.

This does not authenticate GitHub, Git ancestry, a reviewer, or current source
freshness. The caller must obtain the manifest digest and refs independently.
No Runtime facts or current price authority is supplied by this package.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

import yaml

from deferred_definitions import POLICY_PATH, REBINDING_PATH, load_deferred_definitions
from identity_compatibility import (PublishedHistory, operations, validate_namespace,
                                    validate_document_identities)
from runtime_consolidate_openapi import SKIP_FILES, validate_reference_closure
from runtime_registry import discover
from source_governance import source_report, timestamp
from source_json import checked_float
from presentation_page_bindings import MEMBER as PRESENTATION_MEMBER, validate_bindings

REVIEWED_BASELINE = '78ef376841ead8cde10a79651958790be5a0531c'
REVIEWED_BASELINE_SHA256 = 'e0ef2fdf591d0f6b400d6bf1107bf32a31cc1a3453784dc3962cb66a15d16dbd'
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
SPEC_NAME = r'[A-Za-z0-9_.-]+\.json'
MAX_FILE = 32 << 20
MAX_TOTAL = 192 << 20
MAX_FILES = 512
INPUT_CONTEXT_PATH = 'docs/schema-inputs/context.json'
INPUT_RECEIPTS_PATH = 'docs/schema-inputs/source-receipts.json'
INPUT_CONTEXT_MEMBER = 'evidence/reviewed-input-context.json'
INPUT_ROLES = {'registry', 'reviewed_deferral_policy', 'reviewed_deferral_rebinding', 'upstream_schema'}
AUTHORITY = {
    'purpose': 'offline_schema_and_compatibility_inputs_only',
    'runtime_facts_included': False,
    'current_runtime_authority': 'separate_authenticated_runtime_snapshot_required',
    'historical_documents': 'original_bytes_only_not_current_price_status_or_capability_authority',
    'verification': 'integrity_and_historical_replay_not_git_ancestry_or_review_authentication',
}
SINGLETONS = {
    'input/openapi/registry.yaml': 'registry',
    'input/openapi/coverage.json': 'historical_gap_inventory',
    'input/openapi/pending.json': 'historical_gap_inventory',
    'input/' + POLICY_PATH: 'reviewed_deferral_policy',
    'input/' + REBINDING_PATH: 'reviewed_deferral_rebinding',
    'input/docs/publication/current.json': 'historical_formal_pointer',
    'input/docs/publication/formal-contract-readiness.json': 'historical_formal_assessment',
    'baseline/openapi/coverage.json': 'independent_reviewed_gap_baseline',
    'evidence/source-receipts.json': 'original_source_review_receipts',
    'identity/aliases.json': 'historical_alias_index',
    'evidence/git-validation.json': 'build_git_validation_attestation',
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_float=checked_float,
                      parse_constant=invalid)


class UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key, deep=deep)
        require(isinstance(key, str) and key not in result, 'Duplicate or non-text registry key')
        result[key] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def safe_name(name):
    require(isinstance(name, str) and len(name) <= 255 and
            re.fullmatch(r'[A-Za-z0-9._/-]+', name) and
            not name.startswith('/') and all(p not in ('', '.', '..') for p in name.split('/')),
            'Unsafe bundle member path')
    return name


def role_for(name):
    safe_name(name)
    if name == INPUT_CONTEXT_MEMBER:
        return 'reviewed_input_context'
    if name == PRESENTATION_MEMBER:
        return 'historical_presentation_bindings'
    if name in SINGLETONS:
        return SINGLETONS[name]
    if re.fullmatch('input/openapi/upstream/' + SPEC_NAME, name):
        return 'upstream_schema'
    if re.fullmatch('input/openapi/' + SPEC_NAME, name) and Path(name).name not in SKIP_FILES:
        return 'historical_compatibility_document'
    if re.fullmatch(r'proofs/[0-9a-f]{40}/openapi/(?:zh/)?' + SPEC_NAME, name):
        return 'historical_alias_git_bytes'
    raise ValueError('Unsupported bundle member or role')


def reviewed_context(raw):
    """A reconstruction recipe, never a formal or current authorization receipt."""
    value = strict_json(raw)
    require(isinstance(value, dict) and set(value) == {'schema_version', 'kind',
            'historical_formal_ref', 'source_receipts_path', 'source_receipts_sha256', 'source_checked_at'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['kind'] == 'aisa-reviewed-schema-input-context'
            and isinstance(value['historical_formal_ref'], str) and HEX40.fullmatch(value['historical_formal_ref'])
            and value['source_receipts_path'] == INPUT_RECEIPTS_PATH
            and isinstance(value['source_receipts_sha256'], str) and HEX64.fullmatch(value['source_receipts_sha256'])
            and timestamp(value['source_checked_at']) is not None, 'Invalid reviewed input context')
    return value


def formal_input_paths(hashes):
    """The single selection rule for Git-bound Composer schema inputs."""
    return {name for name in hashes if
            name == 'openapi/registry.yaml' or name in (POLICY_PATH, REBINDING_PATH) or
            re.fullmatch('openapi/upstream/' + SPEC_NAME, name) or
            (re.fullmatch('openapi/' + SPEC_NAME, name) and
             (Path(name).name not in SKIP_FILES or Path(name).name in {'coverage.json', 'pending.json'}))}


def reject_unimplemented_inputs(registry, *, pointer_paths):
    require(isinstance(registry, dict) and isinstance(registry.get('providers'), dict), 'Invalid registry')
    for config in registry['providers'].values():
        require(config is None or isinstance(config, dict), 'Invalid registry provider')
        require(not any(key in (config or {}) for key in ('pin', 'pins', 'overlay', 'overlays')),
                'Pinned provider and overlay inputs are not supported by bundle v1')
    require(not any(str(name).removeprefix('input/').startswith('openapi/overlays/')
                    for name in pointer_paths), 'Overlay inputs are not supported by bundle v1')


def regular_read(root, name):
    safe_name(name)
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        require(not current.is_symlink(), 'Bundle symlink is forbidden')
    require(current.is_file(), 'Missing bundle member: ' + name)
    require(current.stat().st_size <= MAX_FILE, 'Bundle member exceeds size limit')
    with current.open('rb') as handle:
        raw = handle.read(MAX_FILE + 1)
    require(len(raw) <= MAX_FILE, 'Bundle member exceeds size limit')
    return raw


class BundleHistory:
    """Verify alias bytes/identities, deliberately without claiming ancestry."""
    verify = PublishedHistory.verify

    def __init__(self, root, members, index, verified_bytes=None):
        require(set(index) == {'canonical_ids', 'aliases'}, 'Invalid identity index fields')
        require(isinstance(index['canonical_ids'], list) and
                index['canonical_ids'] == sorted(set(index['canonical_ids'])) and
                isinstance(index['aliases'], dict), 'Invalid identity namespace')
        self.root, self.members = root, members
        self.verified_bytes = verified_bytes
        self.canonical_ids, self.aliases = set(index['canonical_ids']), index['aliases']
        self.used = set()
        for canonical_id, proofs in self.aliases.items():
            require(canonical_id in self.canonical_ids and isinstance(proofs, list) and proofs,
                    'Alias has no canonical owner')
            require(len({canonical(proof) for proof in proofs}) == len(proofs), 'Duplicate alias proof')
            for proof in proofs:
                self.verify(canonical_id, proof)
        validate_namespace(self.canonical_ids, self.aliases)

    def read(self, ref, filename):
        require(isinstance(ref, str) and HEX40.fullmatch(ref) and
                isinstance(filename, str) and re.fullmatch(r'openapi/(?:zh/)?' + SPEC_NAME, filename),
                'Invalid alias proof namespace')
        name = 'proofs/' + ref + '/' + filename
        require(name in self.members and self.members[name]['role'] == 'historical_alias_git_bytes',
                'Alias proof is outside the declared bundle')
        raw = self.verified_bytes[name] if self.verified_bytes is not None else regular_read(self.root, name)
        self.used.add(name)
        return strict_json(raw), sha(raw)


def load_bundle(root, *, expected_manifest_sha256, expected_docs_ref,
                    expected_baseline_ref=REVIEWED_BASELINE):
    """Validate against caller pins; pins still require an external trust source."""
    root = Path(root)
    require(not root.is_symlink() and root.is_dir(), 'Bundle root must be a real directory')
    require(isinstance(expected_manifest_sha256, str) and HEX64.fullmatch(expected_manifest_sha256)
            and isinstance(expected_docs_ref, str) and HEX40.fullmatch(expected_docs_ref),
            'Independent manifest digest and full Docs ref are required')
    require(expected_baseline_ref == REVIEWED_BASELINE, 'Baseline is not the independently reviewed anchor')
    raw = regular_read(root, 'manifest.json')
    require(sha(raw) == expected_manifest_sha256, 'Manifest differs from caller trust pin')
    manifest = strict_json(raw)
    version = manifest.get('schema_version')
    require(set(manifest) == {'schema_version', 'kind', 'docs_ref', 'baseline_ref', 'authority', 'files'} |
            ({'context'} if version == 3 else set()),
            'Unsupported manifest fields')
    require(type(version) is int and version in (1, 2, 3) and
            manifest['kind'] == 'aisa-schema-input-bundle' and canonical(manifest['authority']) == canonical(AUTHORITY),
            'Unsupported schema bundle authority')
    require(manifest['docs_ref'] == expected_docs_ref and
            manifest['baseline_ref'] == expected_baseline_ref and expected_docs_ref != expected_baseline_ref,
            'Bundle source or independent baseline differs')
    rows = manifest['files']
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, 'Invalid manifest member count')
    members, verified_bytes, total = {}, {}, 0
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'path', 'role', 'sha256', 'bytes'},
                'Unsupported member metadata')
        name = row['path']
        require(role_for(name) == row['role'] and name not in members, 'Duplicate member or role mismatch')
        require(type(row['bytes']) is int and 0 < row['bytes'] <= MAX_FILE and
                isinstance(row['sha256'], str) and HEX64.fullmatch(row['sha256']), 'Invalid member size/hash')
        content = regular_read(root, name)
        require(len(content) == row['bytes'] and sha(content) == row['sha256'], 'Member bytes differ: ' + name)
        total += len(content)
        require(total <= MAX_TOTAL, 'Bundle exceeds total size limit')
        if name.endswith('.json'):
            strict_json(content)
        members[name] = row
        verified_bytes[name] = content
    require(list(members) == sorted(members), 'Manifest members are not sorted')
    require(set(SINGLETONS) <= set(members), 'Required bundle inputs are missing')
    require((PRESENTATION_MEMBER in members) == (version in (2, 3)),
            'Presentation bindings require bundle v2 and are mandatory in v2')
    require((INPUT_CONTEXT_MEMBER in members) == (version == 3),
            'Reviewed input context requires bundle v3')
    context = reviewed_context(verified_bytes[INPUT_CONTEXT_MEMBER]) if version == 3 else None
    if context is not None:
        require(manifest['context'] == {'historical_formal_ref': context['historical_formal_ref']},
                'Reviewed history context differs')
        require(sha(verified_bytes['evidence/source-receipts.json']) == context['source_receipts_sha256'],
                'Reviewed input receipt bytes differ')
    present = set()
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Bundle symlink is forbidden')
        if path.is_file():
            present.add(path.relative_to(root).as_posix())
        else:
            require(path.is_dir(), 'Unsupported bundle filesystem member')
    require(present == {'manifest.json', *members}, 'Bundle contains missing or undeclared files')
    load = lambda name: strict_json(verified_bytes[name])
    registry = yaml.load(verified_bytes['input/openapi/registry.yaml'], Loader=UniqueLoader)
    require(isinstance(registry, dict) and isinstance(registry.get('providers'), dict), 'Invalid registry')
    reject_unimplemented_inputs(registry, pointer_paths=members)
    discover(copy.deepcopy(registry), {'apis': []})
    for provider, config in registry['providers'].items():
        require(version == 3 or 'input/openapi/' + provider + '.json' in members, 'Registry output missing')
        upstream = (config or {}).get('upstream')
        for item in upstream if isinstance(upstream, list) else [upstream]:
            if not item:
                continue
            filename = item.get('file', provider + '.json') if isinstance(item, dict) else provider + '.json'
            require(isinstance(filename, str) and re.fullmatch(SPEC_NAME, filename), 'Registry source escapes namespace')
            name = 'input/openapi/upstream/' + filename
            require(name in members, 'Registry upstream schema missing')
            url = item.get('url') if isinstance(item, dict) else item
            require(load(name)['info']['x-aisa-source']['url'] == url, 'Registry/source URL binding differs')
    docs = {}
    for name, row in members.items():
        if row['role'] in {'upstream_schema', 'historical_compatibility_document'}:
            document = load(name)
            require(isinstance(document, dict) and isinstance(document.get('paths'), dict), 'Invalid schema input')
            validate_reference_closure(document)
            if row['role'] == 'historical_compatibility_document':
                docs[Path(name).stem] = document
    require(docs and any(r['role'] == 'upstream_schema' for r in members.values()), 'Schema inventory is empty')
    history = BundleHistory(root, members, load('identity/aliases.json'), verified_bytes)
    canonical_ids = set()
    for doc in docs.values():
        for _, _, op in operations(doc):
            identity = op.get('operationId')
            require(isinstance(identity, str) and identity not in canonical_ids, 'Missing/duplicate canonical operation ID')
            canonical_ids.add(identity)
    require(canonical_ids == history.canonical_ids, 'Identity inventory differs from schema inputs')
    validate_document_identities(docs, history)
    require(history.used == {n for n, r in members.items() if r['role'] == 'historical_alias_git_bytes'},
            'Orphan alias proof file')
    attest = load('evidence/git-validation.json')
    refs = sorted({n.split('/')[1] for n in history.used})
    expected_attest = {'kind': 'exporter_checked_git_ancestry_not_offline_authentication',
                      'docs_ref': expected_docs_ref, 'ancestors': refs,
                      'independently_pinned_baseline': {'ref': expected_baseline_ref,
                          'path': 'openapi/coverage.json',
                          'sha256': members['baseline/openapi/coverage.json']['sha256']}}
    if context is not None:
        expected_attest.update(historical_formal_ref=context['historical_formal_ref'],
            input_files_sha256={name.removeprefix('input/'): row['sha256'] for name, row in members.items()
                                if row['role'] in INPUT_ROLES})
    require(attest == expected_attest,
            'Invalid build ancestry/baseline attestation')
    pointer = load('input/docs/publication/current.json')
    report_raw = verified_bytes['input/docs/publication/formal-contract-readiness.json']
    report = strict_json(report_raw)
    require(pointer.get('status') == 'passed' and report.get('status') == 'passed' and
            report.get('baseline_ref') == expected_baseline_ref and report.get('baseline_assessed') is True,
            'Historical formal assessment or reviewed baseline differs')
    require(pointer.get('formal_readiness') == {'path': 'docs/publication/formal-contract-readiness.json',
                                               'sha256': sha(report_raw)}, 'Historical formal report binding differs')
    core = {key: pointer.get(key) for key in ('schema_version', 'runtime', 'files_sha256')}
    require(sha(canonical(core).rstrip(b'\n')) == pointer.get('contract_release'), 'Historical formal identity differs')
    hashes = pointer['files_sha256']
    reject_unimplemented_inputs(registry, pointer_paths=hashes)
    expected_inputs = {'input/' + name for name in formal_input_paths(hashes)}
    actual_inputs = {n for n, row in members.items() if row['role'] in {
        'registry', 'reviewed_deferral_policy', 'reviewed_deferral_rebinding', 'upstream_schema',
        'historical_compatibility_document', 'historical_gap_inventory'}}
    # v3 approves new schema inputs independently of the old formal graph. Only
    # historical native/gap bytes still come from that exact old pointer.
    historical_inputs = {name for name in actual_inputs if members[name]['role'] not in INPUT_ROLES}
    compared = actual_inputs if version != 3 else historical_inputs
    expected_compared = expected_inputs if version != 3 else {
        name for name in expected_inputs if role_for(name) not in INPUT_ROLES}
    require(compared == expected_compared, 'Formal input membership differs')
    require(all(members[name]['sha256'] == hashes[name.removeprefix('input/')] for name in compared),
            'Input differs from historical formal file binding')
    if version in (2, 3):
        validate_bindings(load(PRESENTATION_MEMBER),
            context['historical_formal_ref'] if context else expected_docs_ref, hashes, docs)
    require(members['baseline/openapi/coverage.json']['sha256'] == REVIEWED_BASELINE_SHA256,
            'Independent reviewed baseline bytes differ')
    baseline = load('baseline/openapi/coverage.json')
    require(isinstance(baseline.get('providers'), dict), 'Reviewed gap baseline is invalid')
    saved = load('evidence/source-receipts.json')
    require(type(saved.get('schema_version')) is int and saved.get('schema_version') == 1 and isinstance(saved.get('receipts'), dict) and
            isinstance(saved.get('attempts', {}), dict), 'Invalid original receipt packet')
    governance = report.get('source_governance', {})
    checked_at = timestamp(context['source_checked_at'] if context else governance.get('checked_at'))
    require(checked_at is not None, 'Historical assessment clock missing')
    # Existing governance helpers take paths. Materialize a private copy from
    # verified bytes so they cannot reopen caller-mutated bundle members.
    with tempfile.TemporaryDirectory(prefix='verified-schema-input-') as folder:
        verified_root = Path(folder)
        for name, content in verified_bytes.items():
            if name.startswith('input/'):
                target = verified_root / name.removeprefix('input/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        load_deferred_definitions(verified_root)
        reproduced = source_report(verified_root, saved['receipts'], checked_at=checked_at, attempts=saved.get('attempts', {}))
    if context is None:
        require(canonical(reproduced) == canonical(governance), 'Original source receipts do not reproduce fixed formal governance')
    else:
        require(not reproduced['policy_errors'] and reproduced['status'] == 'passed',
                'Reviewed input source policy or original review evidence is invalid')
        governance = reproduced
    result = {'status': 'passed', 'scope': 'offline_integrity_and_historical_replay_only',
            'current_source_freshness': 'not_assessed', 'git_ancestry_and_review_authenticity': 'external_trust_required',
            'manifest_sha256': sha(raw), 'docs_ref': expected_docs_ref, 'baseline_ref': expected_baseline_ref,
            'source_checked_at': governance['checked_at'], 'files': len(members), 'bytes': total,
            'providers': len(registry['providers']), 'canonical_operations': len(canonical_ids),
            'alias_proofs': sum(len(v) for v in history.aliases.values()),
            'upstream_sources': sum(r['role'] == 'upstream_schema' for r in members.values())}

    if context is not None:
        result['input_provenance'] = {'kind': 'reviewed_git_input',
            'historical_formal_ref': context['historical_formal_ref'],
            'input_context_sha256': sha(verified_bytes[INPUT_CONTEXT_MEMBER]),
            'input_source_receipts_sha256': sha(verified_bytes['evidence/source-receipts.json'])}
    return VerifiedBundle(result, members, verified_bytes, history)


@dataclass(frozen=True)
class VerifiedBundle:
    validation: dict
    members: dict
    contents: dict
    history: BundleHistory


def validate_bundle(root, **pins):
    return load_bundle(root, **pins).validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--manifest-sha256', required=True, help='Independently trusted manifest digest')
    parser.add_argument('--docs-ref', required=True, help='Independently trusted full Docs SHA')
    parser.add_argument('--baseline-ref', required=True, help='Must equal the code-pinned reviewed baseline')
    args = parser.parse_args()
    try:
        result = validate_bundle(args.bundle, expected_manifest_sha256=args.manifest_sha256,
                                 expected_docs_ref=args.docs_ref, expected_baseline_ref=args.baseline_ref)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, 'Schema input bundle rejected: ' + str(exc) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
