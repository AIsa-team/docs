"""Candidate-only canonical import/projection; no workflow or publication activation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from compose_openapi import incomplete_source_diagnostic
from gap_evidence import enrich_coverage, response_gap_rows
from pull_openapi import operations
from runtime_registry import (combine_facts, coverage_rows, discover, disabled_legacy_paths,
    legacy_coverage_row, public_mirror_index, published_documents, source_configurations)
from schema_input_bundle import UniqueLoader, canonical, regular_read, require, strict_json


def configured_inputs(root, provider, entry):
    configurations, bindings = source_configurations(provider, entry)
    documents = []
    for url, filename in configurations:
        path = root / 'openapi/upstream' / filename
        document = strict_json(regular_read(root, 'openapi/upstream/' + filename)) if path.exists() else None
        source = (document or {}).get('info', {}).get('x-aisa-source', {})
        require(not url or source.get('kind') in {'provider_openapi', 'manual'} and source.get('url') == url,
                'Fixed upstream source is unavailable or differs')
        if document and source.get('path_space') != 'public':
            documents.append(document)
    configured = entry.get('upstream')
    return (documents if isinstance(configured, list) else (documents[0] if documents else None)), bindings


def diagnostic_pending(provider, facts, native, readiness, upstream, bindings):
    """Preserve producer pending reasons; enrich only existing source diagnostics."""
    result, seen = [], set()
    sources = upstream if isinstance(upstream, list) else ([upstream] if upstream else [])
    for kind in ('existing_pending', 'deferred_pending', 'new_pending'):
        for row in readiness.get(kind, []):
            require(isinstance(row, dict) and all(row.get(key) for key in ('path', 'method', 'operation_id', 'reason')),
                    'Producer pending declaration incomplete')
            identity = (row['path'], row['method'])
            require(identity not in seen, 'Duplicate producer pending declaration')
            seen.add(identity)
            pending = {key: row[key] for key in ('path', 'method', 'operation_id', 'reason')}
            item = facts.get('paths', {}).get(row['path'], {})
            fact = item.get(row['method'].lower(), item.get('x-aisa-any'))
            require(isinstance(fact, dict), 'Producer pending declaration has no Runtime fact')
            if row.get('reason_code') == 'upstream_operation_missing':
                selected_url = bindings.get(row['path'])
                candidates = [source for source in sources if not selected_url or
                    source.get('info', {}).get('x-aisa-source', {}).get('url') == selected_url]
                diagnostic = incomplete_source_diagnostic(candidates, fact.get('x-aisa-upstream-path'),
                    row['method'], fact.get('x-aisa-upstream-selector'))
                require(not diagnostic or diagnostic['reason'] == row['reason'],
                        'Producer pending diagnostic differs from fixed source')
                pending.update(diagnostic)
            result.append(pending)
    for path, method, operation in operations(native):
        reason = operation.get('x-aisa-contract-pending')
        if not reason:
            continue
        require(operation.get('x-aisa-contract-state') == 'retained_legacy' and isinstance(reason, str),
                'Unsupported canonical pending declaration')
        identity = (path, method.upper())
        require(identity not in seen, 'Retained pending overlaps producer pending')
        seen.add(identity)
        result.append({'path': path, 'method': method.upper(),
                       'operation_id': operation['operationId'], 'reason': reason})
    return sorted(result, key=lambda row: (row['path'], row['method'], row['operation_id']))


def project_metadata(input_view, catalog_facts, index, category, native, producer_readiness):
    """Derive new metadata from verified inputs without composing or editing schema.

    The caller verifies these original bytes first. This internal pure projection
    returns objects only and is not an independent trust/authorization boundary.
    """
    from deferred_definitions import load_deferred_definitions
    root = Path(input_view)
    deferred = load_deferred_definitions(root)
    response_identity_v2 = bool(deferred and deferred.response_v2_keys)
    registry = yaml.load(regular_read(root, 'openapi/registry.yaml'), Loader=UniqueLoader)
    if registry.get('auto_register'):
        discover(registry, category)
        discover(registry, {'apis': [{'id': row['id']} for row in index.get('providers', [])
            + index.get('pending_providers', [])]})
    else:
        discover(registry, {'apis': []})
    require(producer_readiness.get('status') == 'passed' and
            not any(producer_readiness.get(key) for key in ('global_errors', 'blocked_providers', 'missing_inputs')),
            'Canonical producer readiness did not pass')
    require(set(registry['providers']) == set(producer_readiness.get('providers', {})),
            'Canonical readiness provider scope differs from derived registry')
    original = published_documents(root)
    mirrors = public_mirror_index(root)
    coverage = {'schema_version': 2, 'providers': {}, 'response_gaps': {}, 'legacy_operations': []}
    pending, facts_by_provider, moved = {'providers': {}}, {}, set()
    for provider, config in sorted(registry['providers'].items()):
        entry = copy.deepcopy(config or {})
        catalogs = entry.get('group', [provider])
        require(provider in native and all(name in catalog_facts for name in catalogs),
                'Canonical provider or Runtime group input missing')
        facts = combine_facts({name: catalog_facts[name] for name in catalogs}, provider)
        facts_by_provider[provider] = facts
        entry.update(display_name=facts.get('info', {}).get('title', provider),
                     description=facts.get('info', {}).get('description', ''))
        registry['providers'][provider] = entry
        upstream, bindings = configured_inputs(root, provider, entry)
        unresolved = diagnostic_pending(provider, facts, native[provider],
            producer_readiness['providers'][provider], upstream, bindings)
        pending['providers'][provider] = unresolved
        rows = coverage_rows(facts, native[provider], unresolved, catalogs)
        enrich_coverage(rows, facts, upstream, mirrors, bindings,
                        response_identity_v2=response_identity_v2)
        coverage['providers'][provider] = rows
        coverage['response_gaps'][provider] = response_gap_rows(native[provider], facts, rows,
            response_identity_v2=response_identity_v2)
        for path, method, operation in operations(native[provider]):
            if operation.get('x-aisa-contract-state') != 'retained_legacy':
                moved.add((path, method, operation['operationId'], provider))
    disabled = disabled_legacy_paths(registry, index, facts_by_provider)
    for name, document in original.items():
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        for path, method, operation in operations(document):
            targets = {owner for p, m, identity, owner in moved
                       if (p, m, identity) == (prefix + path, method, operation.get('operationId'))}
            if targets and name not in targets:
                for owner in targets:
                    entry = registry['providers'][owner]
                    entry['legacy_sources'] = sorted(set(entry.get('legacy_sources', [])) | {name})
            elif not targets:
                coverage['legacy_operations'].append(legacy_coverage_row(name, prefix + path, method,
                    operation.get('operationId'), prefix + path in disabled.get(name, set())))
    return {'registry': registry, 'coverage': coverage, 'pending': pending,
            'facts_by_provider': facts_by_provider, 'runtime_index': copy.deepcopy(index)}


def project_surfaces(input_view, native_raw, aggregate_raw, metadata):
    """Return byte outputs; native/full JSON stay the exact verified producer bytes."""
    from pull_openapi import (existing_page_references, generate_pages,
        refresh_legacy_page_blocks, refresh_localized_documents)
    from runtime_consolidate_openapi import publication_yaml, update_discovery_index
    from sales_catalog_projection import SALES_CATALOG_PATH, sales_catalog_bytes
    root = Path(input_view)
    native = {name: strict_json(raw) for name, raw in native_raw.items()}
    original = published_documents(root)
    changes = {}
    references = existing_page_references(root)
    for provider in sorted(metadata['registry']['providers']):
        require(provider in native, 'Missing canonical provider for page projection')
        generate_pages(root, provider, native[provider], changes, original.get(provider),
                       decorate_links=False, page_references=references, require_existing_links=True)
    translation_path = root / 'translations/openapi-zh.json'
    catalog = strict_json(translation_path.read_bytes()) if translation_path.exists() else {'entries': {}}
    refresh_localized_documents(root, native, changes, catalog)
    refresh_legacy_page_blocks(root, native, changes, catalog)
    require(all(canonical(native[name]) == canonical(strict_json(raw)) for name, raw in native_raw.items()),
            'Projection changed canonical native declarations')
    byte_changes = {path.relative_to(root).as_posix(): text.encode() for path, text in changes.items()}
    byte_changes.update({'openapi/' + name + '.json': raw for name, raw in native_raw.items()})
    byte_changes['openapi/openapi.json'] = aggregate_raw
    aggregate = strict_json(aggregate_raw)
    yaml_raw = publication_yaml(aggregate).encode()
    require(canonical(yaml.safe_load(yaml_raw)) == canonical(aggregate), 'YAML projection is not lossless')
    byte_changes['openapi.yaml'] = yaml_raw
    byte_changes['llms.txt'] = update_discovery_index(regular_read(root, 'llms.txt').decode(), yaml_raw).encode()
    byte_changes[SALES_CATALOG_PATH] = sales_catalog_bytes(aggregate, yaml_raw)
    byte_changes['openapi/registry.yaml'] = yaml.safe_dump(metadata['registry'], sort_keys=False, allow_unicode=True).encode()
    for name in ('coverage', 'pending'):
        byte_changes['openapi/' + name + '.json'] = (json.dumps(metadata[name], indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode()
    return byte_changes


def validate_derived_registry(frozen, current, frozen_native, previous_native):
    """Accept only proven prior Runtime projections, never arbitrary ignored keys.

    previous_native must be read from an authenticated prior formal Git graph.
    Its titles/catalog metadata establish prior derived values; no old coverage
    or pending is used to construct the next publication.
    """
    expected = copy.deepcopy(frozen)
    declared = set(frozen['providers'])
    additions = set(current['providers']) - declared
    require(not additions or frozen.get('auto_register') is True, 'Unexpected provider registration')
    for provider in sorted(additions):
        info = previous_native.get(provider, {}).get('info', {})
        require(info.get('x-aisa-provider') == provider and
                set(info.get('x-aisa-catalogs', {})) == {provider} and
                info.get('x-aisa-document', {}).get('facts_hash'),
                'New registry provider has no prior canonical Runtime derivation')
    discover(expected, {'apis': [{'id': name} for name in sorted(additions)]})
    moved = set()
    for provider, config in expected['providers'].items():
        info = previous_native.get(provider, {}).get('info', {})
        require(info.get('x-aisa-provider') == provider and
                info.get('x-aisa-document', {}).get('facts_hash'),
                'Registry derivation lacks prior canonical facts metadata')
        entry = copy.deepcopy(config or {})
        entry.update(display_name=info.get('title', provider), description=info.get('description', ''))
        expected['providers'][provider] = entry
        for path, method, operation in operations(previous_native[provider]):
            if operation.get('x-aisa-contract-state') != 'retained_legacy':
                moved.add((path, method, operation.get('operationId'), provider))
    for name, document in frozen_native.items():
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        for path, method, operation in operations(document):
            targets = {owner for p, m, identity, owner in moved
                       if (p, m, identity) == (prefix + path, method, operation.get('operationId'))}
            if targets and name not in targets:
                for owner in targets:
                    entry = expected['providers'][owner]
                    entry['legacy_sources'] = sorted(set(entry.get('legacy_sources', [])) | {name})
    require(canonical(current) == canonical(expected),
            'Registry differs from fixed schema configuration and proven Runtime projection')
    return copy.deepcopy(frozen)


def assess_projected_candidate(input_view, projected_view, native_raw, aggregate_raw,
                               metadata, *, baseline_coverage, published_ref,
                               source_receipts, checked_at):
    """Pure candidate gate, not accepted by any existing formal export/workflow."""
    from contract_readiness import check_readiness
    from deferred_definitions import load_deferred_definitions
    from export_contract_publication import source_expiry
    from generate_payment_discovery import verify_payment_catalog
    from publication_surface import publication_hashes, validate_surfaces
    from runtime_consolidate_openapi import discovery_index_block
    from sales_catalog_projection import verify_sales_catalog
    from source_governance import source_report
    from schema_input_bundle import sha
    root, projected = Path(input_view), Path(projected_view)
    from schema_input_bundle import POLICY_PATH, REBINDING_PATH
    source_names = {path.relative_to(root).as_posix() for path in (root / 'openapi/upstream').glob('*.json')}
    projected_sources = {path.relative_to(projected).as_posix() for path in (projected / 'openapi/upstream').glob('*.json')}
    require(source_names == projected_sources, 'Projected source membership differs from assessed inputs')
    for name in source_names | {POLICY_PATH, REBINDING_PATH}:
        require(regular_read(projected, name) == regular_read(root, name),
                'Projection changed schema or source authority inputs')
    actual = published_documents(projected)
    require(set(actual) == set(native_raw), 'Projected native file membership differs')
    for provider, raw in native_raw.items():
        require(regular_read(projected, 'openapi/' + provider + '.json') == raw,
                'Projected native bytes differ from Runtime: ' + provider)
    require(regular_read(projected, 'openapi/openapi.json') == aggregate_raw,
            'Projected aggregate bytes differ from Runtime')
    native = {name: strict_json(raw) for name, raw in native_raw.items()}
    aggregate = strict_json(aggregate_raw)
    for name in ('coverage', 'pending'):
        require(canonical(strict_json(regular_read(projected, 'openapi/' + name + '.json'))) == canonical(metadata[name]),
                'Projected metadata differs from new canonical graph: ' + name)
    require(canonical(yaml.load(regular_read(projected, 'openapi/registry.yaml'), Loader=UniqueLoader)) ==
            canonical(metadata['registry']), 'Projected registry differs')
    report = check_readiness(metadata['facts_by_provider'], native, metadata['coverage'],
        baseline_coverage=baseline_coverage, runtime_index=metadata['runtime_index'],
        deferred_definitions=load_deferred_definitions(root))
    yaml_raw = regular_read(projected, 'openapi.yaml')
    require(canonical(yaml.safe_load(yaml_raw)) == canonical(aggregate), 'Projected YAML differs')
    require(discovery_index_block(yaml_raw) in regular_read(projected, 'llms.txt').decode(),
            'Projected llms discovery binding differs')
    verify_sales_catalog(projected, aggregate, yaml_raw)
    report['publication_surfaces'] = validate_surfaces(projected, published_ref)
    report['payment_discovery'] = verify_payment_catalog(projected)
    sources = source_report(projected, source_receipts['receipts'], checked_at=checked_at,
                            attempts=source_receipts.get('attempts', {}))
    report['source_governance'] = sources
    if sources['sources'] and sources['status'] != 'passed':
        report['status'] = 'failed' if sources['status'] == 'failed' else 'not_assessed'
        report['missing_inputs'].append('current source-maintenance evidence')
    expiry, providers = source_expiry(report, checked_at)
    report['candidate_source_authorization'] = {'expires_at': expiry, 'providers': providers,
        'scope': 'derived_from_new_projected_metadata_only_not_published_authorization'}
    report['evaluation'] = 'actual_publication_graph_and_runtime_canonical'
    report['scope'] = 'candidate_only_not_accepted_by_production_formal_export'
    report['canonical_runtime_import'] = {'status': 'passed',
        'scope': 'exact_runtime_native_aggregate_bytes_and_independent_metadata_projection',
        'native_sha256': {name: sha(raw) for name, raw in native_raw.items()},
        'aggregate_sha256': sha(aggregate_raw)}
    report['publication_artifact'] = {'files_sha256': publication_hashes(projected),
        'openapi_sha256': sha(yaml_raw), 'published_ref': published_ref}
    return report


def schema_input_view_files(repository, current_view, docs_ref, previous_ref, *, compiler_inputs=None):
    """Restore fixed schema inputs only after checking current config and prior output.

    Returned bytes are for a private input view; no checkout is rewritten. The
    previous publication is authenticated independently, including native bytes
    used to explain legitimate registry changes across successive publications.
    """
    from export_schema_input_bundle import GitSource
    from publication_origin import inspect_publication
    from runtime_consolidate_openapi import SKIP_FILES
    from schema_input_bundle import formal_input_paths, role_for, sha
    current = Path(current_view)
    from schema_input_bundle import reject_unimplemented_inputs
    reject_unimplemented_inputs(yaml.load(regular_read(current, 'openapi/registry.yaml'), Loader=UniqueLoader),
        pointer_paths=[path.relative_to(current).as_posix() for path in (current / 'openapi').rglob('*')])
    previous = inspect_publication(Path(repository), previous_ref, historical=True)
    require(previous.get('expected_docs_ref') == previous_ref, 'Prior formal source differs')
    git = GitSource(repository, docs_ref)
    from schema_input_bundle import INPUT_CONTEXT_PATH, INPUT_RECEIPTS_PATH
    git.read(docs_ref, 'openapi/registry.yaml')
    reviewed = INPUT_CONTEXT_PATH in git.trees[docs_ref]
    if reviewed:
        from canonical_input_assessment import load_reviewed_inputs
        require(isinstance(compiler_inputs, dict) and compiler_inputs.get('docs_ref') == docs_ref,
                'Reviewed input requires the canonical compiler binding')
        bundle = load_reviewed_inputs(repository, docs_ref,
            compiler_inputs['bundle_manifest_sha256'])
        frozen_files = {name.removeprefix('input/'): raw for name, raw in bundle.contents.items()
                        if name.startswith('input/') and role_for(name) in {
                            'registry', 'upstream_schema', 'reviewed_deferral_policy',
                            'reviewed_deferral_rebinding', 'historical_compatibility_document',
                            'historical_gap_inventory'}}
        frozen_files.update({INPUT_CONTEXT_PATH: git.read(docs_ref, INPUT_CONTEXT_PATH),
                             INPUT_RECEIPTS_PATH: git.read(docs_ref, INPUT_RECEIPTS_PATH)})
    else:
        frozen_pointer = strict_json(git.read(docs_ref, 'docs/publication/current.json'))
        frozen_files = {name: git.read(docs_ref, name)
                        for name in formal_input_paths(frozen_pointer['files_sha256'])}
        require(all(sha(raw) == frozen_pointer['files_sha256'][name] for name, raw in frozen_files.items()),
                'Fixed schema input differs')
    previous_pointer = strict_json(git.read(previous_ref, 'docs/publication/current.json'))
    require(previous_pointer.get('contract_release') == previous.get('contract_release'),
            'Prior formal pointer differs')
    previous_native = {}
    for name, digest in previous_pointer['files_sha256'].items():
        if name.startswith('openapi/') and name.count('/') == 1 and name.endswith('.json') and Path(name).name not in SKIP_FILES:
            raw = git.read(previous_ref, name)
            require(sha(raw) == digest and regular_read(current, name) == raw,
                    'Prior native publication differs from current input view')
            previous_native[Path(name).stem] = strict_json(raw)
    require(set(published_documents(current)) == set(previous_native), 'Current native graph differs from prior formal graph')
    previous_registry = git.read(previous_ref, 'openapi/registry.yaml')
    current_registry = regular_read(current, 'openapi/registry.yaml')
    require(sha(previous_registry) == previous_pointer['files_sha256'].get('openapi/registry.yaml') and
            (current_registry == previous_registry or
             reviewed and current_registry == frozen_files['openapi/registry.yaml']),
            'Current registry is not the prior assessed projection')
    files = {}
    for name, raw in frozen_files.items():
        files[name] = raw
        if name.startswith('docs/schema-inputs/') or role_for('input/' + name) in {
                'upstream_schema', 'reviewed_deferral_policy', 'reviewed_deferral_rebinding'}:
            require(regular_read(current, name) == raw, 'Current schema authority configuration changed')
    expected_sources = {name for name in files if name.startswith('openapi/upstream/')}
    actual_sources = {path.relative_to(current).as_posix() for path in (current / 'openapi/upstream').glob('*.json')}
    require(expected_sources == actual_sources, 'Current source membership changed')
    frozen_native = {Path(name).stem: strict_json(raw) for name, raw in files.items()
                     if name.startswith('openapi/') and
                     role_for('input/' + name) == 'historical_compatibility_document'}
    # A new reviewed R may intentionally change upstream/group configuration.
    # Otherwise only exact, proven prior Runtime presentation metadata is legal.
    if not reviewed or current_registry != files['openapi/registry.yaml']:
        validate_derived_registry(yaml.load(files['openapi/registry.yaml'], Loader=UniqueLoader),
            yaml.load(current_registry, Loader=UniqueLoader), frozen_native, previous_native)
    return files, {'previous_formal_provenance': previous,
                   'previous_registry_sha256': sha(previous_registry),
                   'fixed_registry_sha256': sha(files['openapi/registry.yaml'])}


def acquired_members(acquired, assessment):
    """Read only bytes still matching the just-verified immutable acquisition."""
    from schema_input_bundle import sha
    before_raw = regular_read(acquired, 'current-before.json')
    require(sha(before_raw) == assessment['current_before_sha256'] and
            sha(regular_read(acquired, 'current-after.json')) == assessment['current_after_sha256'],
            'Acquisition current bytes changed after input assessment')
    before = strict_json(before_raw)
    contents = {}
    for row in before['files']:
        raw = regular_read(acquired, row['name'])
        require(sha(raw) == row['sha256'], 'Acquired immutable member changed after input assessment')
        contents[row['name']] = raw
    receipt_raw = regular_read(acquired, 'acquisition-receipt.json')
    require(sha(receipt_raw) == assessment['runtime_acquisition_sha256'], 'Acquisition receipt changed')
    category = regular_read(acquired, 'category.json')
    require(sha(category) == strict_json(receipt_raw)['category_sha256'], 'Acquired category changed')
    contents['category.json'] = category
    return contents


def assess_canonical_candidate(repository, current_view, projected_view, acquired, *,
                               previous_ref, source_receipts=None, checked_at=None):
    """Replay complete candidate gates, without writing or enabling publication."""
    from datetime import datetime, timezone
    import tempfile
    from canonical_input_assessment import assess_canonical_inputs
    from check_contract_candidate import load_baseline
    from runtime_contract_artifact import MANIFEST, AGGREGATE, READINESS, NATIVE
    from schema_input_bundle import REVIEWED_BASELINE
    repository, current, acquired = Path(repository), Path(current_view), Path(acquired)
    manifest = strict_json(regular_read(acquired, MANIFEST))
    files, lineage = schema_input_view_files(repository, current, manifest['docs_ref'], previous_ref,
                                             compiler_inputs=manifest)
    receipt_path = Path(source_receipts) if source_receipts else current / '.cache/source-reviews.json'
    receipt_raw = regular_read(receipt_path.parent, receipt_path.name)
    saved = strict_json(receipt_raw)
    now = checked_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix='canonical-input-view-') as folder:
        view = Path(folder)
        for name, raw in {**files, '.cache/source-reviews.json': receipt_raw}.items():
            target = view / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        input_assessment = assess_canonical_inputs(view, acquired, checked_at=now, repository=repository)
        contents = acquired_members(acquired, input_assessment)
        verified_manifest = strict_json(contents[MANIFEST])
        require(canonical(verified_manifest) == canonical(manifest), 'Canonical manifest changed during assessment')
        native_raw = {Path(name).stem: raw for name, raw in contents.items() if NATIVE.fullmatch(name)}
        native = {name: strict_json(raw) for name, raw in native_raw.items()}
        facts = {Path(name).stem: strict_json(raw) for name, raw in contents.items() if name.startswith('providers/')}
        metadata = project_metadata(view, facts, strict_json(contents['index.json']),
            strict_json(contents['category.json']), native, strict_json(contents[READINESS]))
        report = assess_projected_candidate(view, projected_view, native_raw, contents[AGGREGATE],
            metadata, baseline_coverage=load_baseline(repository, REVIEWED_BASELINE),
            published_ref=previous_ref, source_receipts=saved, checked_at=now)
    report['canonical_runtime_import']['inputs'] = input_assessment
    report['canonical_runtime_import']['registry_lineage'] = lineage
    report['baseline_ref'] = REVIEWED_BASELINE
    report['runtime'] = input_assessment['runtime']
    report['runtime_acquisition_sha256'] = input_assessment['runtime_acquisition_sha256']
    return report
