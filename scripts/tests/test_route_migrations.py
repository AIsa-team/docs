import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_route_migrations import (CURRENT_FIELDS, SDK_FILE, SOURCE_FILES, TARGETS,
                                     current_index, exact_alternative, prepare,
                                     sdk_request_evidence, source_bundle)
from compose_openapi import digest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'scripts/tests/fixtures/routing-debt-official-sources-20261008.tar.gz'


def synthetic_metadata():
    # Synthetic tuples test the validator, never serve as live capture evidence.
    rows = []
    for identity, provider, old, _, _, _ in TARGETS:
        public = ('/apis/v1/parallel' + old if provider == 'parallel.ai' else
                  '/apis/v1/financial' + old if provider == 'financial' else '/apis/v1/polymarket' + old)
        rows.append({'endpoint_id': identity, 'provider_key': provider, 'public_path': public,
            'upstream_path': old, 'stored_target_path': old, 'contract_method': 'ANY',
            'endpoint_status': 'enabled', 'provider_status': 'enabled', 'profile_status': 'verified',
            'profile_revision': 2, 'compiled_contract_revision': 2,
            'authority_equal_expected': True, 'profile_binding_metadata_matches': True,
            'target_matches_endpoint': True, 'target_has_query': False,
            'upstream_origin_sha256': hashlib.sha256(SOURCE_FILES[provider][2].encode()).hexdigest(),
            'binding_sha256': 'a' * 64, 'profile_canonical_sha256': 'b' * 64,
            'profile_contract_sha256': 'c' * 64, 'target_sha256': hashlib.sha256(old.encode()).hexdigest(),
            'profile_key': 'synthetic.test.' + str(identity), 'private_api_key': 'DO_NOT_COPY_PRIVATE_CANARY'})
    return {'rows': rows, 'production_writes': 0, 'profile_compilations': 0, 'profile_rebindings': 0}


class RouteMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources, cls.files = source_bundle(ARCHIVE)

    def test_seven_exact_alternatives_remain_intentional_unapproved_changes(self):
        current = synthetic_metadata()
        before = copy.deepcopy((current, self.sources, self.files))
        with patch('urllib.request.urlopen', side_effect=AssertionError('business/network calls forbidden')):
            report = prepare([current], self.sources, self.files)
        self.assertEqual(before, (current, self.sources, self.files))
        self.assertEqual(report['counts'], {'route_decisions': 10, 'current_metadata_verified': 10,
            'intentional_alternative_contracts': 7, 'legacy_crypto_request_shape_evidence': 2,
            'exact_current_earnings_press_contracts': 0, 'approved_routes': 0, 'executable_mutations': 0})
        self.assertNotIn('DO_NOT_COPY_PRIVATE_CANARY', json.dumps(report))
        self.assertFalse(report['apply_authorized'])
        self.assertEqual(report['approval_status'], 'UNAPPROVED')
        for row in report['decisions']:
            self.assertFalse(row['strict_profile_binding_validated'])
            self.assertFalse(row['approved'])
            self.assertFalse(row['executable_mutation_ready'])
            self.assertTrue(row['owner_decisions'])
            if row['alternative_contract']:
                contract = row['alternative_contract']
                self.assertFalse(contract['current_target_equivalence_proven'])
                self.assertEqual(contract['official_method_set'], ['GET'])
                for op in contract['operations']:
                    self.assertTrue(op['complete_success_schema'])
                    self.assertEqual(op['schema_hash'], digest({'operation': op['operation'], 'components': op['components']}))
                intent = row['proposed_mutation_intent']
                self.assertIsNone(intent['new_profile_binding'])
                self.assertFalse(intent['sql_execute_ready'])
                self.assertTrue(intent['requires_exact_sql_confirmation'])
        gamma = next(row for row in report['decisions'] if row['endpoint_id'] == 2251)
        self.assertEqual(gamma['alternative_contract']['provider_key'], 'polymarket-gamma')
        parallel = next(row for row in report['decisions'] if row['endpoint_id'] == 1801)
        self.assertEqual(parallel['existing_current_ga_endpoint_id'], 1793)
        self.assertNotEqual(parallel['current_upstream_path'], parallel['alternative_contract']['target_path'])

    def test_legacy_sdk_is_ast_only_and_does_not_invent_provider_constraints(self):
        with patch('builtins.exec', side_effect=AssertionError('SDK execution forbidden')):
            proofs = sdk_request_evidence(self.files[SDK_FILE])
        self.assertEqual(len(proofs), 3)
        history = next(proof for proof in proofs if proof['function'] == 'get_crypto_prices')
        self.assertEqual(history['literal_upstream_path'], '/crypto/prices/')
        query = {arg['name']: arg for arg in history['query_arguments']}
        self.assertEqual(set(query), {'ticker', 'start_date', 'end_date', 'interval', 'interval_multiplier'})
        self.assertTrue(query['ticker']['client_required'])
        self.assertEqual(query['interval']['client_default'], 'day')
        self.assertEqual(query['interval_multiplier']['client_default'], 1)
        for proof in proofs:
            for field in ('provider_constraints_proven', 'complete_any_method_set_proven', 'response_schema_proven', 'current_provider_support_proven'):
                self.assertFalse(proof[field])
            self.assertNotIn('parameters', proof)
        with self.assertRaisesRegex(ValueError, 'pinned'):
            sdk_request_evidence(self.files[SDK_FILE].replace(b'client.get(', b'client.post('))

    def test_no_migration_to_similar_route_or_silent_prefix_or_provider_rebinding(self):
        for provider, wrong in [('financial', '/company/facts/ticker'), ('financial', '/earnings/press-releases'),
                                ('polymarket-clob', '/order/{orderID}'), ('polymarket-data', '/public-search'),
                                ('parallel.ai', '/v1beta/tasks/runs/{run_id}/events')]:
            with self.subTest(provider=provider, path=wrong), self.assertRaisesRegex(ValueError, 'absent'):
                exact_alternative(self.sources, self.files, provider, wrong)
        report = prepare([], self.sources, self.files)
        self.assertEqual(report['counts']['current_metadata_verified'], 0)
        for row in report['decisions']:
            self.assertFalse(row['current_routing_metadata_verified'])
        press = next(row for row in report['decisions'] if row['endpoint_id'] == 1686)
        self.assertIsNone(press['alternative_contract'])
        self.assertNotIn('legacy_sdk_request_evidence', press)
        for identity in (1684, 1685):
            crypto = next(row for row in report['decisions'] if row['endpoint_id'] == identity)
            self.assertIsNone(crypto['alternative_contract'])
            self.assertFalse(crypto['literal_sdk_target_equal_current'])

    def test_effective_servers_and_complete_operation_inventory_fail_closed(self):
        for context in ('root', 'path', 'operation'):
            for declaration in (None, [], [{'url': 'https://unrelated.invalid'}],
                                [{'url': 'https://clob-staging.polymarket.com'}], [{'url': 'https://clob.polymarket.com/private'}]):
                with self.subTest(context=context, servers=declaration):
                    sources = copy.deepcopy(self.sources)
                    document = sources['polymarket-clob']
                    item = document['paths']['/data/trades']
                    place = document if context == 'root' else item if context == 'path' else item['get']
                    place['servers'] = declaration
                    with self.assertRaises((ValueError, TypeError)):
                        exact_alternative(sources, self.files, 'polymarket-clob', '/data/trades')
        sources = copy.deepcopy(self.sources)
        sources['polymarket-clob']['paths']['/data/trades']['post'] = copy.deepcopy(sources['polymarket-clob']['paths']['/data/trades']['get'])
        alternative = exact_alternative(sources, self.files, 'polymarket-clob', '/data/trades')
        self.assertEqual(alternative['official_method_set'], ['GET', 'POST'])

    def test_full_current_inventory_drift_missing_and_invalid_metadata_cannot_claim_ready(self):
        base = synthetic_metadata()
        for field, value in [('endpoint_status', 'disabled'), ('provider_status', 'disabled'), ('profile_status', 'pending'),
                             ('profile_revision', 0), ('profile_revision', True), ('compiled_contract_revision', 0),
                             ('compiled_contract_revision', True), ('target_matches_endpoint', False),
                             ('profile_binding_metadata_matches', False), ('authority_equal_expected', False),
                             ('upstream_origin_sha256', 'd' * 64), ('binding_sha256', 'bad'), ('contract_method', 'GET'),
                             ('profile_key', ''), ('stored_target_path', '/wrong'), ('target_sha256', 'd' * 64),
                             ('upstream_path_sha256', 'd' * 64)]:
            with self.subTest(field=field):
                current = copy.deepcopy(base)
                current['rows'][0][field] = value
                report = prepare([current], self.sources, self.files)
                self.assertFalse(report['decisions'][0]['current_routing_metadata_verified'])
        for field in ('public_path', 'provider_key', 'upstream_path'):
            current = copy.deepcopy(base)
            current['rows'][0][field] += '-changed'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'drift'):
                prepare([current], self.sources, self.files)
        for identity in (0, -1, True, '1683'):
            current = copy.deepcopy(base)
            current['rows'][0]['endpoint_id'] = identity
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'positive'):
                current_index([current])
        current = copy.deepcopy(base)
        current['rows'].append({'endpoint_id': current['rows'][0]['endpoint_id'], 'provider_key': 'foreign'})
        with self.assertRaisesRegex(ValueError, 'unique'):
            current_index([current])
        current = copy.deepcopy(base)
        current['profile_compilations'] = 1
        with self.assertRaisesRegex(ValueError, 'no writes'):
            current_index([current])

    def test_new_capture_independent_origin_hash_and_revision_identities(self):
        current = synthetic_metadata()
        for row in current['rows']:
            del row['authority_equal_expected']
            row['profile_revision'] = 4
            row['compiled_contract_revision'] = 5
        report = prepare([current], self.sources, self.files)
        self.assertEqual(report['counts']['current_metadata_verified'], 10)
        current['rows'][0]['upstream_origin_sha256'] = 'd' * 64
        report = prepare([current], self.sources, self.files)
        self.assertFalse(report['decisions'][0]['current_routing_metadata_verified'])
        self.assertFalse(report['decisions'][0]['strict_profile_binding_validated'])

    def test_raw_fixture_drift_and_example_only_responses_cannot_claim_schema_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.tar.gz'
            path.write_bytes(ARCHIVE.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'exact'):
                source_bundle(path)
        sources = copy.deepcopy(self.sources)
        sources['financial']['paths']['/company/facts']['get']['responses']['200'] = {
            'description': 'example only', 'content': {'application/json': {'example': {'ticker': 'AAPL'}}}}
        alternative = exact_alternative(sources, self.files, 'financial', '/company/facts')
        operation = alternative['operations'][0]
        self.assertFalse(operation['complete_success_schema'])
        self.assertEqual(operation['operation']['responses']['200']['content']['application/json']['example'], {'ticker': 'AAPL'})


if __name__ == '__main__':
    unittest.main()
