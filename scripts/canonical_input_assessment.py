"""Assess canonical build/schema input bindings; never import or publish artifacts.

The public Runtime's separately deployed compiler_inputs is the build trust
anchor. Historical Git provenance is authenticated by publication_origin. The
bundle digest itself is not recomputed from Git: its original external review
receipt packet is not a Git member. This module does not confer current source
or publication authorization; final projected metadata must be assessed later.
"""
from datetime import datetime, timezone
from pathlib import Path

import yaml

from export_contract_publication import acquired_input
from export_schema_input_bundle import GitSource
from publication_origin import inspect_publication
from runtime_contract_artifact import MANIFEST, PROTOCOL
from schema_input_bundle import (HEX40, HEX64, SINGLETONS, UniqueLoader, canonical,
    formal_input_paths, regular_read, reject_unimplemented_inputs, require,
    role_for, sha, strict_json)
from source_governance import source_report

BINDINGS = {'protocol_version', 'bundle_manifest_sha256', 'docs_ref',
            'composer_revision', 'source_manifest_sha256'}
CURRENT_INPUT_ROLES = {'registry', 'reviewed_deferral_policy',
                       'reviewed_deferral_rebinding', 'upstream_schema'}


def assess_canonical_inputs(root, facts, *, source_receipts=None, checked_at=None, repository=None):
    """Pure, replayable gate; production workflows do not yet call this function."""
    root, facts = Path(root), Path(facts)
    receipt, receipt_raw = acquired_input(facts)
    require(receipt.get('canonical_validation'), 'Canonical acquisition is required')
    before_raw = regular_read(facts, 'current-before.json')
    after_raw = regular_read(facts, 'current-after.json')
    before, after = strict_json(before_raw), strict_json(after_raw)
    require(canonical(before) == canonical(after), 'Live current binding changed')
    manifest_raw = regular_read(facts, MANIFEST)
    manifest = strict_json(manifest_raw)
    live = before.get('compiler_inputs')
    require(isinstance(live, dict) and set(live) == BINDINGS and
            live.get('protocol_version') == PROTOCOL, 'Live compiler input binding required')
    for key in BINDINGS - {'protocol_version'}:
        pattern = HEX40 if key in {'docs_ref', 'composer_revision'} else HEX64
        require(isinstance(live[key], str) and pattern.fullmatch(live[key]), 'Invalid live compiler pin')
    require(canonical(live) == canonical({key: manifest[key] for key in BINDINGS}),
            'Canonical artifact differs from live compiler input binding')

    docs_ref = live['docs_ref']
    # This uses the existing successful producer run/artifact and main ancestry
    # verification, not a caller-provided boolean or a self-described Git hash.
    repository = Path(repository) if repository else root
    provenance = inspect_publication(repository, docs_ref, historical=True)
    require(provenance.get('expected_docs_ref') == docs_ref, 'Formal source provenance differs')
    git = GitSource(repository, docs_ref)
    pointer_raw = git.read(docs_ref, 'docs/publication/current.json')
    pointer = strict_json(pointer_raw)
    require(pointer.get('contract_release') == provenance.get('contract_release'),
            'Authenticated formal pointer differs')
    hashes = pointer['files_sha256']
    registry = yaml.load(git.read(docs_ref, 'openapi/registry.yaml'), Loader=UniqueLoader)
    reject_unimplemented_inputs(registry, pointer_paths=git.trees[docs_ref])
    selected = formal_input_paths(hashes)
    required = {name.removeprefix('input/') for name, role in SINGLETONS.items()
                if role in CURRENT_INPUT_ROLES}
    require(required <= selected, 'Formal schema policy or registry binding missing')
    frozen_hashes, current_hashes = {}, {}
    for name in sorted(selected):
        raw = git.read(docs_ref, name)
        require(sha(raw) == hashes[name], 'Fixed Git schema input hash differs: ' + name)
        frozen_hashes[name] = hashes[name]
        if role_for('input/' + name) in CURRENT_INPUT_ROLES:
            require(sha(regular_read(root, name)) == hashes[name],
                    'Current schema or policy differs from compiled input: ' + name)
            current_hashes[name] = hashes[name]
    expected_sources = {name for name in current_hashes if role_for('input/' + name) == 'upstream_schema'}
    actual_sources = {path.relative_to(root).as_posix() for path in (root / 'openapi/upstream').glob('*.json')}
    require(expected_sources and expected_sources == actual_sources, 'Current source membership differs')
    current_registry = yaml.load(regular_read(root, 'openapi/registry.yaml'), Loader=UniqueLoader)
    reject_unimplemented_inputs(current_registry, pointer_paths=[p.relative_to(root).as_posix()
        for p in (root / 'openapi').rglob('*')])
    receipts_path = Path(source_receipts) if source_receipts else root / '.cache/source-reviews.json'
    saved_raw = regular_read(receipts_path.parent, receipts_path.name)
    saved = strict_json(saved_raw)
    require(type(saved.get('schema_version')) is int and saved['schema_version'] == 1 and
            isinstance(saved.get('receipts'), dict) and isinstance(saved.get('attempts', {}), dict),
            'Original source observation packet required')
    now = checked_at or datetime.now(timezone.utc)
    require(isinstance(now, datetime) and now.tzinfo is not None, 'Source observation time lacks timezone')
    observations = source_report(root, saved['receipts'], checked_at=now, attempts=saved.get('attempts', {}))
    require(not observations['policy_errors'], 'Current source policy is invalid')
    # Deliberately exclude provider attribution/expiry calculated from an old
    # projection. Final canonical native+coverage projection must recompute it.
    return {'schema_version': 1, 'status': 'passed',
        'scope': 'canonical_build_and_schema_inputs_only_not_publication_or_current_source_authorization',
        'compiler_inputs': live, 'runtime_acquisition_sha256': sha(receipt_raw),
        'runtime': {key: receipt[key] for key in ('artifact_revision', 'compiler_revision', 'source_digest', 'generation')},
        'canonical_manifest_sha256': sha(manifest_raw),
        'current_before_sha256': sha(before_raw), 'current_after_sha256': sha(after_raw),
        'source_formal_provenance': provenance, 'source_pointer_sha256': sha(pointer_raw),
        'frozen_input_files_sha256': frozen_hashes, 'current_input_files_sha256': current_hashes,
        'source_receipts_sha256': sha(saved_raw), 'source_checked_at': observations['checked_at'],
        'source_observations': observations['sources'],
        'remaining_gates': ['canonical_native_and_aggregate_projection',
            'final_provider_source_scope_and_expiry', 'publication_surfaces', 'payment_discovery']}
