#!/usr/bin/env python3
"""Build review-only Polymarket contracts from frozen facts and official bytes.

No network, Runtime mutation or publication occurs here. The real Docs composer
supplies request/response contracts and complete ANY method expansion. Missing
upstream paths stay blocked: source bindings cannot repair a different server or
silently prepend /data/. --write-candidates writes only this package's review
directory, never the production OpenAPI, registry, pages or activation flags.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile
from types import SimpleNamespace
from urllib.parse import urlsplit

import yaml

from compose_openapi import METHODS, compose, digest
from import_upstream import OfficialSourceLoader
from identity_compatibility import attach_history, localize_identities, PROOF_FIELDS
from runtime_registry import previous_for_facts, published_documents
from source_governance import initial_policy, acquisition_receipt, timestamp
from source_json import loads as source_loads

SOURCE_FIXTURE_SHA256 = 'b673b06cb1063fd1650f4363b174695e4ec9f60078d6a94247f7b98d668cff6f'
ARCHIVE_SHA256 = 'f2b35c81df49b3a31053f3b4e8978778e52556d2d36536c23f4d7f28f8e0f02f'
PROVIDERS = ('polymarket-bridge', 'polymarket-clob', 'polymarket-data',
             'polymarket-gamma', 'polymarket-relayer')
SPEC_URLS = {provider: 'https://docs.polymarket.com/api-spec/' +
             provider.removeprefix('polymarket-') + '-openapi.yaml' for provider in PROVIDERS}
SERVER_ORIGINS = {
    'polymarket-bridge': {'https://bridge.polymarket.com'},
    'polymarket-clob': {'https://clob.polymarket.com', 'https://clob-staging.polymarket.com'},
    'polymarket-data': {'https://data-api.polymarket.com'},
    'polymarket-gamma': {'https://gamma-api.polymarket.com'},
    'polymarket-relayer': {'https://relayer-v2.polymarket.com'},
}
SHA256 = re.compile(r'[0-9a-f]{64}')
IDENTITY = re.compile(r'[A-Za-z0-9_.-]{1,255}')


PRODUCTION_ORIGIN = {provider: next(iter(origins)) for provider, origins in SERVER_ORIGINS.items()
                     if provider != 'polymarket-clob'}
PRODUCTION_ORIGIN['polymarket-clob'] = 'https://clob.polymarket.com'


def _server_origins(servers):
    if not isinstance(servers, list) or not servers:
        raise ValueError('official source requires nonempty declared servers')
    origins = set()
    for server in servers:
        if not isinstance(server, dict) or not isinstance(server.get('url'), str):
            raise ValueError('invalid official server declaration')
        parsed = urlsplit(server['url'])
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or server.get('variables'):
            raise ValueError('unsupported official server declaration')
        origins.add(parsed.scheme + '://' + parsed.netloc)
    return origins


def _validate_server_scopes(provider, source):
    if _server_origins(source.get('servers')) != SERVER_ORIGINS[provider]:
        raise ValueError('official source server role changed')
    for item in source['paths'].values():
        if not isinstance(item, dict):
            raise ValueError('invalid official Path Item')
        if '$ref' in item:
            raise ValueError('referenced Path Item authority unsupported')
        scoped = [item] + [op for method, op in item.items() if method in METHODS]
        for context in scoped:
            if not isinstance(context, dict):
                raise ValueError('invalid official operation')
            if 'servers' in context:
                origins = _server_origins(context['servers'])
                if not origins <= SERVER_ORIGINS[provider] or PRODUCTION_ORIGIN[provider] not in origins:
                    raise ValueError('official scoped server bypasses production authority')


def _current_mapping_index(mapping, targets):
    if mapping is None:
        return {}
    if not isinstance(mapping, dict) or not isinstance(mapping.get('rows'), list) or timestamp(mapping.get('observed_at_utc')) is None:
        raise ValueError('dated complete current public binding metadata required')
    for field in ('production_writes', 'profile_compilations', 'profile_rebindings'):
        if type(mapping.get(field)) is not int or mapping[field] != 0:
            raise ValueError('current evidence must be read-only with no Profile mutations')
    all_rows = {}
    for row in mapping['rows']:
        if not isinstance(row, dict) or type(row.get('endpoint_id')) is not int or row['endpoint_id'] <= 0 or row['endpoint_id'] in all_rows:
            raise ValueError('current endpoint IDs must be globally unique positive integers')
        all_rows[row['endpoint_id']] = row
    expected = {row['endpoint_id'] for row in targets}
    selected = {identity: row for identity, row in all_rows.items() if row.get('provider_key') in PROVIDERS}
    if set(selected) != expected:
        raise ValueError('complete exact current 89-target inventory required')
    for target in targets:
        row = selected[target['endpoint_id']]
        if any(row.get(field) != target[field] for field in ('provider_key', 'public_path', 'endpoint_status')) or row.get('contract_method') != 'ANY':
            raise ValueError('current public route, provider, status or stored method drift')
        if row.get('provider_status') != 'enabled' or row.get('profile_status') != 'verified' or row.get('target_has_query') is not False:
            raise ValueError('current provider, Profile status or query-bearing target unsupported')
        if any(row.get(field) is not True for field in ('authority_equal_expected', 'profile_binding_metadata_matches', 'target_matches_endpoint')):
            raise ValueError('current authority, metadata tuple or target mismatch')
        if row.get('upstream_origin_sha256') != hashlib.sha256(PRODUCTION_ORIGIN[row['provider_key']].encode()).hexdigest():
            raise ValueError('current origin is not the exact production server')
        for field in ('binding_sha256', 'profile_canonical_sha256', 'profile_contract_sha256', 'target_sha256'):
            if not isinstance(row.get(field), str) or not SHA256.fullmatch(row[field]):
                raise ValueError('complete current opaque binding hashes required')
        for field in ('profile_revision', 'compiled_contract_revision'):
            if type(row.get(field)) is not int or row[field] <= 0:
                raise ValueError('current immutable Profile revisions required')
        if row['profile_revision'] != row['compiled_contract_revision']:
            raise ValueError('current immutable Profile revision mismatch')
    return selected


def load_official_sources(directory: Path):
    """Require all five independently acquired exact raw files and origins."""
    records = source_loads((directory / 'official-fetch-receipt.json').read_bytes())
    if not isinstance(records, list) or len(records) != len(PROVIDERS):
        raise ValueError('complete five-source official acquisition receipt required')
    indexed = {}
    for record in records:
        if not isinstance(record, dict) or record.get('name') not in {p.removeprefix('polymarket-') for p in PROVIDERS}:
            raise ValueError('unknown official source in acquisition receipt')
        provider = 'polymarket-' + record['name']
        if provider in indexed:
            raise ValueError('duplicate official source acquisition receipt')
        indexed[provider] = record
    sources, receipts = {}, {}
    for provider in PROVIDERS:
        record = indexed[provider]
        if record.get('url') != SPEC_URLS[provider] or record.get('final_url') != SPEC_URLS[provider]:
            raise ValueError('official source authority or redirect changed')
        if not isinstance(record.get('raw_sha256'), str) or not SHA256.fullmatch(record['raw_sha256']):
            raise ValueError('exact official raw source hash required')
        raw = (directory / 'raw' / (provider + '.yaml')).read_bytes()
        if len(raw) > 8 << 20 or hashlib.sha256(raw).hexdigest() != record['raw_sha256'] or len(raw) != record.get('bytes'):
            raise ValueError('official raw source byte inventory changed')
        document = yaml.load(raw, Loader=OfficialSourceLoader)
        if not isinstance(document, dict) or not str(document.get('openapi', '')).startswith('3.') or not isinstance(document.get('paths'), dict):
            raise ValueError('official source is not OpenAPI 3')
        servers = document.get('servers', [])
        _validate_server_scopes(provider, document)
        if servers != record.get('servers'):
            raise ValueError('official source recorded servers changed')
        acquired_at = timestamp(record.get('fetched_at'))
        if acquired_at is None:
            raise ValueError('official acquisition timestamp required')
        if 'x-aisa-source' in document.get('info', {}):
            raise ValueError('official source cannot carry repository review provenance')
        source_hash = digest(document)
        source = initial_policy({'kind': 'provider_openapi', 'url': SPEC_URLS[provider],
                                 'fetched_at': record['fetched_at'], 'content_hash': source_hash,
                                 'converter': 'scripts/import_upstream.py@2'})
        document.setdefault('info', {})['x-aisa-source'] = source
        sources[provider] = document
        # This proves the recorded official GET acquisition only, never a
        # compatibility review, current Runtime binding or publication approval.
        receipts[provider] = acquisition_receipt(source, acquired_at)
    return sources, receipts


def load_official_sources_archive(archive: Path):
    """Replay exact public official GET bytes, without network or approval."""
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_FIXTURE_SHA256:
        raise ValueError('immutable official source fixture hash mismatch')
    expected = {'official-fetch-receipt.json'} | {'raw/' + provider + '.yaml' for provider in PROVIDERS}
    with tempfile.TemporaryDirectory() as temp, tarfile.open(archive) as handle:
        members = handle.getmembers()
        if len(members) != len(expected) or {member.name for member in members} != expected:
            raise ValueError('complete exact official source fixture inventory required')
        root = Path(temp)
        for member in members:
            if not member.isfile() or member.size > 8 << 20:
                raise ValueError('invalid official source fixture member')
            path = root / member.name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(handle.extractfile(member).read())
        return load_official_sources(root)


def load_frozen_facts(archive: Path):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('immutable sanitized W0 catalog archive hash mismatch')
    facts = {}
    with tarfile.open(archive) as handle:
        for provider in PROVIDERS:
            member = handle.getmember('input/facts/' + provider + '.json')
            if not member.isfile() or member.size > 8 << 20:
                raise ValueError('invalid frozen Polymarket fact member')
            facts[provider] = source_loads(handle.extractfile(member).read())
        registry = yaml.load(handle.extractfile('input/openapi/registry.yaml').read(), Loader=OfficialSourceLoader)
    for provider in PROVIDERS:
        entry = registry['providers'][provider]['upstream']
        if not isinstance(entry, dict) or entry.get('url') != SPEC_URLS[provider]:
            raise ValueError('frozen Polymarket source authority changed')
    return facts


def _operations(document):
    prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield prefix + path, method.upper(), operation


def _reserve_namespace(documents):
    identities = {}
    for document in documents.values():
        for path, method, operation in _operations(document):
            owner = (path, method)
            canonical = operation.get('operationId')
            if not isinstance(canonical, str) or not IDENTITY.fullmatch(canonical):
                raise ValueError('invalid published operation identity')
            value = operation.get('x-aisa-identity')
            reserved = [canonical]
            if value is not None:
                if not isinstance(value, dict) or set(value) != {'schema_version', 'canonical_operation_id', 'historical_aliases', 'sha256'}:
                    raise ValueError('invalid existing identity compatibility metadata')
                unhashed = {k: v for k, v in value.items() if k != 'sha256'}
                if value['canonical_operation_id'] != canonical or value['sha256'] != digest(unhashed):
                    raise ValueError('existing identity compatibility owner or hash changed')
                proofs = value.get('historical_aliases')
                if type(value.get('schema_version')) is not int or value['schema_version'] != 1 or not isinstance(proofs, list) or not proofs:
                    raise ValueError('invalid existing identity compatibility declaration')
                if any(not isinstance(proof, dict) or set(proof) != PROOF_FIELDS or
                       proof['locale'] != 'zh' or proof['public_path'] != path or
                       proof['method'] != method or proof['operation_id'] == canonical
                       for proof in proofs):
                    raise ValueError('existing alias proof has a different owner')
                reserved += [proof['operation_id'] for proof in value['historical_aliases']]
            for identity in reserved:
                if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
                    raise ValueError('invalid published alias identity')
                if identity in identities and identities[identity] != owner:
                    raise ValueError('published canonical/alias namespace collision')
                identities[identity] = owner
    return identities


def build_candidate(plan, facts, sources, publications, current_mapping=None):
    """Compose evidence-backed frozen candidates without changing any inputs."""
    if not isinstance(plan, dict) or not isinstance(plan.get('decisions'), list):
        raise ValueError('complete public decision inventory required')
    inventory_ids = set()
    for row in plan['decisions']:
        if not isinstance(row, dict) or type(row.get('endpoint_id')) is not int or row['endpoint_id'] <= 0 or row['endpoint_id'] in inventory_ids:
            raise ValueError('decision endpoint IDs must be globally unique positive integers')
        inventory_ids.add(row['endpoint_id'])
    targets = [row for row in plan['decisions'] if row.get('provider_key') in PROVIDERS and
               row.get('code') == 'unpublished_identity_requires_separate_review']
    if not targets or any(row.get('endpoint_status') != 'enabled' for row in targets):
        raise ValueError('explicit enabled unpublished Polymarket target set required')
    by_route, endpoint_ids = {}, set()
    for target in targets:
        if type(target.get('endpoint_id')) is not int or target['endpoint_id'] <= 0 or target['endpoint_id'] in endpoint_ids:
            raise ValueError('target endpoint IDs must be globally unique positive integers')
        endpoint_ids.add(target['endpoint_id'])
        key = (target['provider_key'], target['public_path'])
        if key in by_route:
            raise ValueError('duplicate Polymarket target route')
        if target.get('evidence', {}).get('contract_method') != 'ANY':
            raise ValueError('historical target method changed; refresh the facts')
        by_route[key] = target
    current_rows = _current_mapping_index(current_mapping, targets)
    reserved = _reserve_namespace(publications)
    documents, decisions, provider_summaries, compatibility_preserved = {}, [], {}, []
    for provider in PROVIDERS:
        original = facts[provider]
        source = sources[provider]
        if source['info']['x-aisa-source']['url'] != SPEC_URLS[provider]:
            raise ValueError('provider source binding has the wrong authority')
        _validate_server_scopes(provider, source)
        previous = previous_for_facts(original, publications, provider)
        document, pending = compose(original, source, previous=previous)
        previous_index = {(path, method): op for path, method, op in _operations(previous)}
        retained_aliases = {}
        for path, method, operation in _operations(document):
            old = previous_index.get((path, method))
            if old:
                if old['operationId'] != operation['operationId']:
                    raise ValueError('published Polymarket identity changed')
                if 'x-aisa-identity' in old:
                    retained_aliases[operation['operationId']] = copy.deepcopy(old['x-aisa-identity']['historical_aliases'])
                    compatibility_preserved.append(operation['operationId'])
            identity = operation['operationId']
            if not IDENTITY.fullmatch(identity) or (identity in reserved and reserved[identity] != (path, method)):
                raise ValueError('candidate shadows a published canonical/alias identity')
            reserved[identity] = (path, method)
        # Existing metadata is retained byte-for-byte; the real compatibility
        # helper also binds it into the document hash. No new proof is created,
        # and this candidate path makes no Git ancestry approval claim.
        if retained_aliases:
            attach_history(document, SimpleNamespace(aliases=retained_aliases))
        documents[provider] = document
        provider_summaries[provider] = {'fact_routes': len(original['paths']),
                                        'composed_routes': len(document['paths']),
                                        'composed_operations': sum(1 for _ in _operations(document)),
                                        'pending': pending,
                                        'response_pending': document['info']['x-aisa-document']['response_pending']}
        for path, item in original['paths'].items():
            target = by_route.get((provider, path))
            if not target:
                continue
            runtime = item.get('x-aisa-any')
            if not isinstance(runtime, dict) or runtime.get('x-aisa-status') != 'enabled':
                raise ValueError('frozen Polymarket target status or method changed')
            upstream_path = runtime.get('x-aisa-upstream-path')
            if not isinstance(upstream_path, str) or not upstream_path.startswith('/') or '?' in upstream_path or '#' in upstream_path:
                raise ValueError('invalid frozen upstream path')
            current = current_rows.get(target['endpoint_id'])
            if current and current.get('upstream_path') != upstream_path:
                raise ValueError('current upstream path differs from frozen candidate; no implicit rewrite')
            source_methods = sorted(set(source['paths'].get(upstream_path, {})) & METHODS)
            composed = document['paths'].get(path, {})
            complete = bool(source_methods) and set(composed) & METHODS == set(source_methods)
            reasons = [row for row in pending if row['path'] == path]
            decision = {'endpoint_id': target['endpoint_id'], 'provider_key': provider,
                        'public_path': path, 'contract_method': 'ANY',
                        'frozen_upstream_path': upstream_path,
                        'current_binding_verified': False,
                        'current_routing_metadata_verified': bool(current),
                        'current_binding_validation_scope': 'routing and metadata tuple only; not full ValidateBinding or full current wire facts',
                        'current_binding_evidence': copy.deepcopy(current),
                        'source_url': SPEC_URLS[provider],
                        'source_content_hash': source['info']['x-aisa-source']['content_hash'],
                        'official_declared_methods': [m.upper() for m in source_methods],
                        'disposition': 'candidate' if complete else 'blocked',
                        'code': 'frozen_exact_upstream_method_set_composed' if complete else
                                ('official_upstream_path_missing' if not source_methods else 'composition_incomplete'),
                        'canonical_base_candidate': runtime['operationId'] if complete else None,
                        'method_identity_candidates': [{'method': method.upper(),
                                                        'operation_id': composed[method]['operationId'],
                                                        'upstream_path': upstream_path}
                                                       for method in source_methods if method in composed],
                        'pending': reasons,
                        'new_identity_approved': False,
                        'source_compatibility_review_approved': False}
            if not source_methods:
                # Evidence locations explain the debt. They are alternatives
                # for review, never a rewrite of frozen Runtime target mapping.
                if provider == 'polymarket-clob' and upstream_path in ('/order/{orderID}', '/trades'):
                    alternative = '/data' + upstream_path
                    decision['conflict_evidence'] = {'official_path': alternative,
                        'source_url': SPEC_URLS[provider],
                        'methods': sorted(m.upper() for m in set(source['paths'].get(alternative, {})) & METHODS),
                        'runtime_target_rewrite_performed': False}
                elif provider == 'polymarket-data' and upstream_path == '/public-search':
                    other = sources['polymarket-gamma']
                    decision['conflict_evidence'] = {'official_path': upstream_path,
                        'source_url': SPEC_URLS['polymarket-gamma'],
                        'methods': sorted(m.upper() for m in set(other['paths'].get(upstream_path, {})) & METHODS),
                        'different_provider_server': True,
                        'runtime_source_rebinding_performed': False}
            decisions.append(decision)
    if len(decisions) != len(targets):
        raise ValueError('target route absent from frozen facts; current public mapping required')
    decisions.sort(key=lambda row: row['endpoint_id'])
    counts = {'target_endpoints': len(targets),
              'current_routing_metadata_verified': len(current_rows),
              'frozen_source_method_verified_candidates': sum(row['disposition'] == 'candidate' for row in decisions),
              'blocked_endpoints': sum(row['disposition'] == 'blocked' for row in decisions),
              'candidate_method_identities': sum(len(row['method_identity_candidates']) for row in decisions),
              'composed_operations_including_established_routes': sum(row['composed_operations'] for row in provider_summaries.values()),
              'request_pending': sum(len(row['pending']) for row in provider_summaries.values()),
              'response_pending': sum(len(row['response_pending']) for row in provider_summaries.values())}
    report = {'schema_version': 1, 'approval_status': 'UNAPPROVED', 'apply_authorized': False,
              'scope': 'Official source contracts and frozen W0 mapping replay; not current production contracts, source compatibility approval, identity import or publication.',
              'frozen_snapshot_date': '2026-10-01', 'current_production_read_performed': False,
              'current_production_read_evidence_included': bool(current_rows),
              'current_binding_observed_at_utc': current_mapping['observed_at_utc'] if current_rows else None,
              'facts_rewritten': False, 'production_profile_or_sql_mutations': 0,
              'counts': counts, 'providers': provider_summaries, 'decisions': decisions,
              'published_compatibility_metadata_preserved': compatibility_preserved,
              'readiness': 'blocked',
              'blocking_boundaries': ['Full current public wire facts and full ValidateBinding not verified' if current_rows else 'Current upstream binding and full current public wire facts not verified',
                                      'Unmatched upstream paths cannot be repaired by selecting another source or guessing HTTP methods',
                                      'New canonical IDs and official source compatibility require review; no publication approval']}
    return report, documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--current-mapping', type=Path)
    parser.add_argument('--write-candidates', action='store_true')
    args = parser.parse_args()
    directory = args.root / 'docs/polymarket-closure-20261008'
    sources, acquisitions = load_official_sources_archive(args.root / 'scripts/tests/fixtures/polymarket-official-sources-20261008.tar.gz')
    report, documents = build_candidate(source_loads(args.plan.read_bytes()), load_frozen_facts(args.archive),
                                        sources, published_documents(args.root),
                                        source_loads(args.current_mapping.read_bytes()) if args.current_mapping else None)
    report['input_hashes'] = {'plan_sha256': hashlib.sha256(args.plan.read_bytes()).hexdigest(),
                             'frozen_archive_sha256': ARCHIVE_SHA256,
                             'official_source_fixture_sha256': SOURCE_FIXTURE_SHA256}
    if args.current_mapping:
        report['input_hashes']['current_mapping_sha256'] = hashlib.sha256(args.current_mapping.read_bytes()).hexdigest()
    if args.write_candidates:
        destination = directory / 'candidates-NOT-APPROVED'
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'zh').mkdir(exist_ok=True)
        for provider, document in documents.items():
            (destination / (provider + '.json')).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
            (destination / 'zh' / (provider + '.json')).write_text(json.dumps(localize_identities(document), indent=2, ensure_ascii=False) + '\n')
        (directory / 'source-acquisition-receipts.json').write_text(json.dumps(acquisitions, indent=2) + '\n')
        (directory / 'closure-candidates-NOT-APPROVED.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'approval_status': report['approval_status'], 'readiness': report['readiness'],
                      'counts': report['counts'], 'candidate_files_written': args.write_candidates}))


if __name__ == '__main__':
    main()
