import copy
import hashlib
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from close_polymarket_catalog import (PROVIDERS, SERVER_ORIGINS, SPEC_URLS,
                                      build_candidate, load_frozen_facts,
                                      load_official_sources, load_official_sources_archive, main)
from compose_openapi import digest
from identity_compatibility import metadata, localize_identities
from source_governance import initial_policy, validate_receipt
from datetime import datetime, timezone
from test_runtime_contracts import facts, operation
from catalog_fixture import ARCHIVE

ROOT = Path(__file__).resolve().parents[2]


def small_catalog():
    plan, snapshots, sources = {'decisions': []}, {}, {}
    for number, provider in enumerate(PROVIDERS, 1):
        snapshot = facts('provider', 'x-aisa-any')
        op = operation(snapshot)
        op.update(operationId=provider + '_candidate', **{
            'x-aisa-upstream-path': '/route', 'x-aisa-passthrough': True,
            'x-aisa-query-policy': {'request_wins': True}})
        snapshot['paths'] = {'/apis/v1/' + provider + '/route': {'x-aisa-any': op}}
        snapshots[provider] = snapshot
        source = {'openapi': '3.1.0', 'info': {'title': provider},
                  'servers': [{'url': origin} for origin in sorted(SERVER_ORIGINS[provider])],
                  'paths': {'/route': {'get': {'parameters': [
                      {'name': 'limit', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 1}}],
                      'responses': {'200': {'description': 'Official response',
                          'content': {'application/json': {'schema': {'type': 'object',
                              'properties': {'result': {'type': 'string'}}}}}}}}}}}
        source['info']['x-aisa-source'] = initial_policy({'kind': 'provider_openapi',
            'url': SPEC_URLS[provider], 'content_hash': digest(source),
            'fetched_at': '2026-10-08T05:30:00+00:00', 'converter': 'fixture'})
        sources[provider] = source
        plan['decisions'].append({'endpoint_id': number, 'provider_key': provider,
            'public_path': '/apis/v1/' + provider + '/route', 'endpoint_status': 'enabled',
            'code': 'unpublished_identity_requires_separate_review',
            'evidence': {'contract_method': 'ANY'}})
    return plan, snapshots, sources


class PolymarketCandidateTests(unittest.TestCase):
    def test_default_cli_writes_nothing_and_opt_in_creates_fresh_evidence_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'scripts/tests/fixtures/polymarket-official-sources-20261008.tar.gz'
            source.parent.mkdir(parents=True)
            source.write_bytes((ROOT / 'scripts/tests/fixtures/polymarket-official-sources-20261008.tar.gz').read_bytes())
            arguments = ['close_polymarket_catalog.py', '--root', str(root), '--plan',
                str(ROOT / 'scripts/tests/fixtures/polymarket-targets-snapshot-20261008.json'),
                '--archive', str(ARCHIVE), '--current-mapping',
                str(ROOT / 'scripts/tests/fixtures/polymarket-current-binding-map-20261008.json')]
            evidence = root / 'docs/polymarket-closure-20261008'
            with patch('sys.argv', arguments), redirect_stdout(io.StringIO()) as output:
                main()
            self.assertFalse(evidence.exists())
            self.assertFalse(json.loads(output.getvalue())['candidate_files_written'])
            with patch('sys.argv', arguments + ['--write-candidates']), redirect_stdout(io.StringIO()) as output:
                main()
            summary = json.loads(output.getvalue())
            self.assertTrue(summary['candidate_files_written'])
            self.assertEqual(summary['counts']['current_routing_metadata_verified'], 89)
            candidate = json.loads((evidence / 'closure-candidates-NOT-APPROVED.json').read_text())
            self.assertEqual(candidate['approval_status'], 'UNAPPROVED')
            self.assertFalse(candidate['apply_authorized'])
            self.assertEqual(len(list((evidence / 'candidates-NOT-APPROVED').glob('*.json'))), 5)
            self.assertEqual(len(list((evidence / 'candidates-NOT-APPROVED/zh').glob('*.json'))), 5)
            self.assertFalse((root / 'openapi').exists())
            self.assertFalse((root / 'facts').exists())

    def test_complete_official_methods_requests_responses_without_input_mutations(self):
        plan, frozen, sources = small_catalog()
        sources['polymarket-clob']['paths']['/route']['post'] = {
            'requestBody': {'required': True, 'content': {'application/json': {
                'schema': {'type': 'object', 'properties': {'size': {'type': 'integer'}},
                           'required': ['size']}}}},
            'responses': copy.deepcopy(sources['polymarket-clob']['paths']['/route']['get']['responses'])}
        before = copy.deepcopy((plan, frozen, sources))
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            report, documents = build_candidate(plan, frozen, sources, {})
        self.assertEqual(before, (plan, frozen, sources))
        self.assertEqual(report['counts']['frozen_source_method_verified_candidates'], 5)
        self.assertEqual(report['counts']['candidate_method_identities'], 6)
        self.assertEqual(report['counts']['response_pending'], 0)
        self.assertFalse(report['apply_authorized'])
        self.assertEqual(report['approval_status'], 'UNAPPROVED')
        self.assertEqual(report['readiness'], 'blocked')
        clob = next(row for row in report['decisions'] if row['provider_key'] == 'polymarket-clob')
        self.assertEqual(clob['official_declared_methods'], ['GET', 'POST'])
        self.assertEqual({row['operation_id'] for row in clob['method_identity_candidates']},
                         {'get_polymarket-clob_candidate', 'post_polymarket-clob_candidate'})
        for provider, document in documents.items():
            for path, item in document['paths'].items():
                for op in item.values():
                    original = frozen[provider]['paths'][path]['x-aisa-any']
                    for field in ['x-aisa-pricing', 'x-aisa-status', 'x-aisa-revision']:
                        self.assertEqual(op.get(field), original.get(field))
                    self.assertIn('x-aisa-source', op)
                    self.assertIn('x-aisa-response-source', op)
        self.assertTrue(documents['polymarket-clob']['paths'][clob['public_path']]['post']['requestBody']['required'])

    def test_missing_path_cannot_be_repaired_by_prefix_or_another_source(self):
        plan, frozen, sources = small_catalog()
        for provider, public_tail, stored, official in [
                ('polymarket-clob', 'order/{orderID}', '/order/{orderID}', '/data/order/{orderID}'),
                ('polymarket-data', 'public-search', '/public-search', '/public-search')]:
            original = frozen[provider]['paths'].pop('/apis/v1/' + provider + '/route')
            original['x-aisa-any']['x-aisa-upstream-path'] = stored
            path = '/apis/v1/polymarket/' + public_tail
            frozen[provider]['paths'][path] = original
            next(r for r in plan['decisions'] if r['provider_key'] == provider)['public_path'] = path
            owner = provider if provider == 'polymarket-clob' else 'polymarket-gamma'
            sources[owner]['paths'][official] = copy.deepcopy(sources[owner]['paths']['/route'])
        before = copy.deepcopy(frozen)
        report, _ = build_candidate(plan, frozen, sources, {})
        blocked = [r for r in report['decisions'] if r['disposition'] == 'blocked']
        self.assertEqual(len(blocked), 2)
        for row in blocked:
            self.assertEqual(row['official_declared_methods'], [])
            self.assertEqual(row['method_identity_candidates'], [])
            self.assertIsNone(row['canonical_base_candidate'])
            self.assertIn('conflict_evidence', row)
            self.assertFalse(row['new_identity_approved'])
        self.assertEqual(frozen, before)
        self.assertTrue(next(r for r in blocked if r['provider_key'] == 'polymarket-data')['conflict_evidence']['different_provider_server'])

    def test_published_canonical_and_alias_metadata_preserved_with_bound_hash(self):
        plan, frozen, sources = small_catalog()
        provider = 'polymarket-gamma'
        path = next(iter(frozen[provider]['paths']))
        canonical = 'established_gamma_identity'
        proof = {'operation_id': 'oldGammaLocale', 'locale': 'zh', 'published_ref': 'a' * 40,
                 'source_file': 'openapi/zh/gamma.json', 'source_sha256': 'b' * 64,
                 'canonical_source_file': 'openapi/gamma.json', 'canonical_source_sha256': 'c' * 64,
                 'public_path': path, 'method': 'GET'}
        previous = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
                    'paths': {path: {'get': {'operationId': canonical,
                        'responses': sources[provider]['paths']['/route']['get']['responses'],
                        'x-aisa-identity': metadata(canonical, [proof])}}}}
        report, documents = build_candidate(plan, frozen, sources, {'gamma': previous})
        current = documents[provider]['paths'][path]['get']
        self.assertEqual(current['operationId'], canonical)
        self.assertEqual(current['x-aisa-identity'], previous['paths'][path]['get']['x-aisa-identity'])
        self.assertEqual(localize_identities(documents[provider])['paths'][path]['get']['operationId'], proof['operation_id'])
        document_meta = documents[provider]['info']['x-aisa-document']
        self.assertIn('identity_compatibility_hash', document_meta)
        self.assertEqual(document_meta['document_hash'], digest({
            'document_hash': document_meta['identity_base_document_hash'],
            'identity_compatibility_hash': document_meta['identity_compatibility_hash']}))
        self.assertEqual(report['published_compatibility_metadata_preserved'], [canonical])

    def test_bad_target_or_namespace_fail_closed(self):
        for variant in ['duplicate_route', 'disabled', 'method', 'missing_fact', 'wrong_authority', 'canonical_collision', 'alias_collision', 'zero_id', 'bool_id', 'duplicate_id', 'foreign_duplicate_id']:
            with self.subTest(variant=variant):
                plan, frozen, sources = small_catalog()
                publications = {}
                if variant == 'zero_id':
                    plan['decisions'][0]['endpoint_id'] = 0
                elif variant == 'bool_id':
                    plan['decisions'][0]['endpoint_id'] = True
                elif variant == 'duplicate_id':
                    plan['decisions'][1]['endpoint_id'] = plan['decisions'][0]['endpoint_id']
                elif variant == 'foreign_duplicate_id':
                    plan['decisions'].append({'endpoint_id': 1, 'provider_key': 'other'})
                elif variant == 'duplicate_route':
                    plan['decisions'].append(copy.deepcopy(plan['decisions'][0]))
                elif variant == 'disabled':
                    plan['decisions'][0]['endpoint_status'] = 'disabled'
                elif variant == 'method':
                    plan['decisions'][0]['evidence']['contract_method'] = 'GET'
                elif variant == 'missing_fact':
                    plan['decisions'][0]['public_path'] += '/different'
                elif variant == 'wrong_authority':
                    sources[PROVIDERS[0]]['info']['x-aisa-source']['url'] = SPEC_URLS['polymarket-gamma']
                else:
                    identity = operation(frozen[PROVIDERS[0]])['operationId']
                    op = {'operationId': identity if variant == 'canonical_collision' else 'different_owner'}
                    if variant == 'alias_collision':
                        op['x-aisa-identity'] = metadata('different_owner', [{
                            'operation_id': identity, 'locale': 'zh', 'published_ref': 'a' * 40,
                            'source_file': 'openapi/zh/different.json', 'source_sha256': 'b' * 64,
                            'canonical_source_file': 'openapi/different.json', 'canonical_source_sha256': 'c' * 64,
                            'public_path': '/another/route', 'method': 'GET'}])
                    publications['different'] = {'paths': {'/another/route': {'get': op}}}
                with self.assertRaises(ValueError):
                    build_candidate(plan, frozen, sources, publications)

    def test_actual_89_targets_source_proofs_and_exact_three_debts(self):
        from runtime_registry import published_documents
        plan = json.loads((ROOT / 'scripts/tests/fixtures/polymarket-targets-snapshot-20261008.json').read_text())
        sources, acquisitions = load_official_sources_archive(ROOT / 'scripts/tests/fixtures/polymarket-official-sources-20261008.tar.gz')
        snapshot = load_frozen_facts(ARCHIVE)
        before = copy.deepcopy(snapshot)
        report, documents = build_candidate(plan, snapshot, sources, published_documents(ROOT))
        self.assertEqual(snapshot, before)
        self.assertEqual(report['counts'], {
            'target_endpoints': 89, 'current_routing_metadata_verified': 0, 'frozen_source_method_verified_candidates': 86,
            'blocked_endpoints': 3, 'candidate_method_identities': 92,
            'composed_operations_including_established_routes': 95,
            'request_pending': 3, 'response_pending': 0})
        self.assertEqual({row['public_path'] for row in report['decisions'] if row['disposition'] == 'blocked'},
            {'/apis/v1/polymarket/order/{orderID}', '/apis/v1/polymarket/trades', '/apis/v1/polymarket/public-search'})
        established = {(path, op['operationId']) for document in documents.values()
                       for path, item in document['paths'].items() for op in item.values()
                       if op['operationId'] in {'get_polymarket_markets', 'get_polymarket_events', 'get_polymarket_activity'}}
        self.assertEqual(len(established), 3)
        for provider in PROVIDERS:
            self.assertTrue(validate_receipt(sources[provider]['info']['x-aisa-source'], acquisitions[provider],
                                           datetime(2026, 10, 8, 5, 31, tzinfo=timezone.utc)))
            localized = localize_identities(documents[provider])
            self.assertEqual(localized['paths'], documents[provider]['paths'])

    def test_scoped_servers_cannot_bypass_declared_production_authority(self):
        for context in ('path', 'operation'):
            for servers in ([], [{'url': 'https://unrelated.invalid'}],
                            [{'url': 'https://clob-staging.polymarket.com'}],
                            [{'url': 'https://clob.polymarket.com/private'}]):
                with self.subTest(context=context, servers=servers):
                    plan, frozen, sources = small_catalog()
                    item = sources['polymarket-clob']['paths']['/route']
                    target = item if context == 'path' else item['get']
                    target['servers'] = servers
                    with self.assertRaises(ValueError):
                        build_candidate(plan, frozen, sources, {})
            plan, frozen, sources = small_catalog()
            item = sources['polymarket-clob']['paths']['/route']
            target = item if context == 'path' else item['get']
            target['servers'] = [{'url': 'https://clob.polymarket.com'}]
            self.assertEqual(build_candidate(plan, frozen, sources, {})[0]['counts']['candidate_method_identities'], 5)

    def test_actual_current89_metadata_matches_but_three_route_conflicts_remain(self):
        from runtime_registry import published_documents
        plan = json.loads((ROOT / 'scripts/tests/fixtures/polymarket-targets-snapshot-20261008.json').read_text())
        current = json.loads((ROOT / 'scripts/tests/fixtures/polymarket-current-binding-map-20261008.json').read_text())
        sources, _ = load_official_sources_archive(ROOT / 'scripts/tests/fixtures/polymarket-official-sources-20261008.tar.gz')
        frozen = load_frozen_facts(ARCHIVE)
        report, _ = build_candidate(plan, frozen, sources, published_documents(ROOT), current)
        self.assertEqual(report['counts']['current_routing_metadata_verified'], 89)
        self.assertEqual(report['counts']['blocked_endpoints'], 3)
        self.assertEqual(report['counts']['candidate_method_identities'], 92)
        self.assertTrue(all(row['current_routing_metadata_verified'] for row in report['decisions']))
        self.assertFalse(any(row['current_binding_verified'] for row in report['decisions']))
        self.assertFalse(report['apply_authorized'])
        self.assertIn('full ValidateBinding', report['blocking_boundaries'][0])
        for variant in ('staging', 'authority', 'metadata', 'target', 'method', 'public_route',
                        'upstream_route', 'missing', 'duplicate', 'foreign_duplicate',
                        'zero_id', 'bad_hash', 'revision', 'writes', 'query'):
            with self.subTest(variant=variant):
                changed = copy.deepcopy(current)
                row = next(r for r in changed['rows'] if r['provider_key'] == 'polymarket-clob')
                if variant == 'staging':
                    row['upstream_origin_sha256'] = hashlib.sha256(b'https://clob-staging.polymarket.com').hexdigest()
                elif variant in ('authority', 'metadata', 'target'):
                    row[{'authority': 'authority_equal_expected', 'metadata': 'profile_binding_metadata_matches',
                         'target': 'target_matches_endpoint'}[variant]] = False
                elif variant == 'method': row['contract_method'] = 'GET'
                elif variant == 'public_route': row['public_path'] += '/changed'
                elif variant == 'upstream_route': row['upstream_path'] += '/changed'
                elif variant == 'missing': changed['rows'].pop()
                elif variant == 'duplicate': changed['rows'].append(copy.deepcopy(row))
                elif variant == 'foreign_duplicate': changed['rows'].append({'endpoint_id': row['endpoint_id'], 'provider_key': 'other'})
                elif variant == 'zero_id': row['endpoint_id'] = 0
                elif variant == 'bad_hash': row['profile_contract_sha256'] = 'invalid'
                elif variant == 'revision': row['compiled_contract_revision'] += 1
                elif variant == 'writes': changed['production_writes'] = 1
                elif variant == 'query': row['target_has_query'] = True
                with self.assertRaises(ValueError):
                    build_candidate(plan, frozen, sources, published_documents(ROOT), changed)



class PolymarketOfficialBytesTests(unittest.TestCase):
    def test_recorded_official_byte_drift_origin_and_redirect_fail_closed(self):
        _, _, sources = small_catalog()
        for variant in ['valid', 'changed_byte', 'duplicate_record', 'wrong_url', 'redirect', 'missing_source', 'wrong_origin', 'timestamp']:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                (directory / 'raw').mkdir()
                records = []
                for provider, document in sources.items():
                    original = copy.deepcopy(document)
                    original['info'].pop('x-aisa-source')
                    raw = yaml.safe_dump(original).encode()
                    (directory / 'raw' / (provider + '.yaml')).write_bytes(raw)
                    records.append({'name': provider.removeprefix('polymarket-'),
                        'url': SPEC_URLS[provider], 'final_url': SPEC_URLS[provider],
                        'fetched_at': '2026-10-08T05:30:00+00:00',
                        'raw_sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                        'servers': original['servers']})
                if variant == 'changed_byte':
                    path = directory / 'raw' / (PROVIDERS[0] + '.yaml')
                    path.write_bytes(path.read_bytes() + b'\n')
                elif variant == 'duplicate_record':
                    records[-1] = records[0]
                elif variant == 'wrong_url':
                    records[0]['url'] = SPEC_URLS['polymarket-gamma']
                elif variant == 'redirect':
                    records[0]['final_url'] = 'https://unrelated.invalid/spec.yaml'
                elif variant == 'missing_source':
                    records.pop()
                elif variant == 'wrong_origin':
                    records[0]['servers'] = [{'url': 'https://other.invalid'}]
                elif variant == 'timestamp':
                    records[0]['fetched_at'] = 'not-a-timestamp'
                (directory / 'official-fetch-receipt.json').write_text(json.dumps(records))
                if variant == 'valid':
                    loaded, _ = load_official_sources(directory)
                    self.assertEqual(set(loaded), set(PROVIDERS))
                else:
                    with self.assertRaises(ValueError):
                        load_official_sources(directory)


if __name__ == '__main__':
    unittest.main()
