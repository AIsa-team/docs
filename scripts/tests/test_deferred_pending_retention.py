"""Exactly approved deferred pending routes keep their published identity, never as active."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_readiness import _pending_key, check_readiness
from deferred_definitions import (DeferredDefinitions, FASTMOSS_DEFERRAL, FASTMOSS_DEFERRAL_PATH,
                                  FASTMOSS_DEFERRAL_SHA256, RELAYER_DEFERRAL, RELAYER_DEFERRAL_PATH,
                                  RELAYER_DEFERRAL_SHA256, _apply_fastmoss_policy, _apply_relayer_policy,
                                  canonical_key, fastmoss_deferral_digest, load_deferred_definitions,
                                  relayer_deferral_digest)
from pull_openapi import assert_identities, retain_pending_history, stage
from readiness_rejection import _policy
from test_full_registry import contract

ROOT = Path(__file__).resolve().parents[2]


def approval(provider, keys):
    return DeferredDefinitions({'policy_id': 'synthetic unit fixture', 'scope': {'request': len(keys)},
                                'items': [{'provider': provider, 'kind': 'request', 'gate_identity': key}
                                          for key in keys]})


class AssertIdentitiesTests(unittest.TestCase):
    def doc(self, routes):
        return {'paths': {path: {method: {'operationId': oid}} for (path, method), oid in routes.items()}}

    def test_only_an_exempt_missing_route_is_not_an_identity_change(self):
        old = self.doc({('/a', 'get'): 'a', ('/b', 'get'): 'b'})
        current = self.doc({('/a', 'get'): 'a'})
        with self.assertRaisesRegex(ValueError, 'changed or disappeared: b'):
            assert_identities(old, current)
        assert_identities(old, current, {('/b', 'get')})
        assert_identities(old, current, {('/b', 'any')})
        with self.assertRaisesRegex(ValueError, 'changed or disappeared: b'):
            assert_identities(old, current, {('/b', 'post'), ('/other', 'any')})

    def test_changed_identity_on_an_exempt_route_still_fails(self):
        old = self.doc({('/b', 'get'): 'b'})
        with self.assertRaisesRegex(ValueError, 'changed or disappeared: b'):
            assert_identities(old, self.doc({('/b', 'get'): 'renamed'}), {('/b', 'get'), ('/b', 'any')})


class RetainPendingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.facts = contract('alpha')
        self.history = copy.deepcopy(self.facts)
        self.history['paths']['/apis/v1/alpha/test']['get']['summary'] = 'Published'
        self.document = {'openapi': '3.1.0', 'info': {'x-aisa-document': {'document_hash': 'sha256:composed'}},
                         'servers': [{'url': 'https://api.aisa.one'}], 'paths': {}, 'components': {}}
        self.pending = [{'operation_id': 'alpha_test', 'path': '/apis/v1/alpha/test', 'method': 'GET',
                         'reason': 'source header parameters are not forwarded by runtime: KEY'}]

    def test_retained_copy_is_disabled_pending_with_the_real_reason(self):
        rows = retain_pending_history(self.document, self.facts, self.history, self.pending)
        self.assertEqual(rows, [{'path': '/apis/v1/alpha/test', 'method': 'GET', 'operation_id': 'alpha_test',
                                 'reason': self.pending[0]['reason']}])
        op = self.document['paths']['/apis/v1/alpha/test']['get']
        self.assertEqual((op['operationId'], op['summary']), ('alpha_test', 'Published'))
        self.assertEqual(op['x-aisa-status'], 'disabled')
        self.assertEqual(op['x-aisa-contract-state'], 'retained_pending')
        self.assertEqual(op['x-aisa-contract-pending'], self.pending[0]['reason'])
        self.assertNotEqual(self.document['info']['x-aisa-document']['document_hash'], 'sha256:composed')

    def test_route_filter_composed_route_and_absent_runtime_path_are_not_retained(self):
        self.assertEqual(retain_pending_history(copy.deepcopy(self.document), self.facts, self.history,
                                                self.pending, set()), [])
        composed = copy.deepcopy(self.document)
        composed['paths']['/apis/v1/alpha/test'] = {'get': {'operationId': 'alpha_test'}}
        self.assertEqual(retain_pending_history(composed, self.facts, self.history, self.pending), [])
        gone = copy.deepcopy(self.facts); gone['paths'] = {}
        self.assertEqual(retain_pending_history(copy.deepcopy(self.document), gone, self.history, self.pending), [])


class StageDeferredPendingTests(unittest.TestCase):
    """Published alpha_test becomes pending; only an exact approval unblocks alpha."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('openapi', 'facts'):
            (self.root / name).mkdir()
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
            {'language': lang, 'tabs': [{'tab': title, 'groups': []}]} for lang, title in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
        self.published = contract('alpha')
        (self.root / 'openapi/alpha.json').write_text(json.dumps(self.published))
        current = {'alpha': contract('alpha', validation='provider'), 'beta': contract('beta')}
        (self.root / 'facts/category.json').write_text(json.dumps({'apis': [{'id': key} for key in current]}))
        for key, doc in current.items():
            (self.root / f'facts/{key}.json').write_text(json.dumps(doc))

    def tearDown(self):
        self.temp.cleanup()

    def run_stage(self, policy):
        context = {'baseline_coverage': {'providers': {}}}
        with patch('deferred_definitions.load_deferred_definitions', return_value=policy):
            changes, summary = stage(self.root, self.root / 'facts', 'unused', with_pages=False,
                                     readiness_context=context)
        return changes, summary, context

    def key(self):
        _, summary, context = self.run_stage(None)
        self.assertIn('changed or disappeared', summary['alpha']['blocked'])
        row = next(row for row in context['coverage']['providers']['alpha'] if row['path'] == '/apis/v1/alpha/test')
        return _pending_key({**row, 'runtime_status': 'enabled'})

    def test_unapproved_pending_route_keeps_blocking_and_files_untouched(self):
        key = self.key()
        changes, summary, context = self.run_stage(approval('alpha', [[*key[:-1], 'disabled']]))
        self.assertIn('blocked', summary['alpha'])
        self.assertNotIn(self.root / 'openapi/alpha.json', changes)
        self.assertIn('alpha', context['report']['blocked_providers'])

    def test_approved_pending_route_is_retained_disabled_and_deferred(self):
        key = self.key()
        self.assertEqual(key[5], 'upstream_operation_missing')
        changes, summary, context = self.run_stage(approval('alpha', [list(key)]))
        self.assertNotIn('blocked', summary['alpha'])
        staged = json.loads(changes[self.root / 'openapi/alpha.json'])
        op = staged['paths']['/apis/v1/alpha/test']['get']
        self.assertEqual(op['operationId'], 'alpha_test')
        self.assertEqual((op['x-aisa-status'], op['x-aisa-contract-state'], op['x-aisa-contract-pending']),
                         ('disabled', 'retained_pending', 'upstream operation missing'))
        result = context['report']['providers']['alpha']
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual([row['operation_id'] for row in result['deferred_pending']], ['alpha_test'])
        self.assertEqual(result['new_pending'], [])
        self.assertEqual(result['errors'], [])
        self.assertNotIn('alpha', context['report']['blocked_providers'])
        # The retained copy is not a complete publication.
        published = copy.deepcopy(context['documents'])
        published['alpha']['paths']['/apis/v1/alpha/test']['get'].pop('x-aisa-contract-pending')
        report = check_readiness(context['facts_by_provider'], published, context['coverage'],
                                 baseline_coverage={'providers': {}}, deferred_definitions=approval('alpha', [list(key)]))
        self.assertIn('pending_published_as_complete', {e['code'] for e in report['providers']['alpha']['errors']})


class CanonicalRetainedPendingTests(unittest.TestCase):
    def setUp(self):
        self.facts = contract('alpha')
        self.native = {'paths': {'/apis/v1/alpha/test': {'get': {
            'operationId': 'alpha_test', 'x-aisa-status': 'disabled', 'x-aisa-contract-state': 'retained_pending',
            'x-aisa-contract-pending': 'source header parameters are not forwarded by runtime: KEY'}}}}
        self.row = {'path': '/apis/v1/alpha/test', 'method': 'GET', 'operation_id': 'alpha_test',
                    'reason': 'source header parameters are not forwarded by runtime: KEY',
                    'reason_code': 'unforwarded_source_header'}

    def test_retained_pending_is_the_producer_row_not_an_extra_declaration(self):
        from canonical_import import diagnostic_pending
        rows = diagnostic_pending('alpha', self.facts, self.native, {'deferred_pending': [self.row]}, None, {})
        self.assertEqual(rows, [{key: self.row[key] for key in ('path', 'method', 'operation_id', 'reason')}])

    def test_retained_pending_without_matching_producer_row_is_rejected(self):
        from canonical_import import diagnostic_pending
        for readiness in ({}, {'deferred_pending': [{**self.row, 'reason': 'other'}]},
                          {'deferred_pending': [{**self.row, 'operation_id': 'renamed'}]}):
            with self.assertRaisesRegex(ValueError, 'Retained pending operation differs'):
                diagnostic_pending('alpha', self.facts, self.native, readiness, None, {})


class RelayerDeferralRecordTests(unittest.TestCase):
    def test_loaded_with_cr003_and_exactly_three_relayer_request_keys(self):
        policy = load_deferred_definitions(ROOT)
        self.assertEqual(policy.metadata['policy_id'], 'CR003-exact-enabled-definitions-20261010')
        self.assertEqual(policy.metadata['effective_scope'], {'request': 7, 'response': 53})
        self.assertEqual(policy.metadata['additional_policies'], [{
            'policy_id': 'CR004-polymarket-relayer-20261019', 'path': RELAYER_DEFERRAL_PATH,
            'sha256': RELAYER_DEFERRAL_SHA256, 'scope': {'request': 3, 'response': 0}}, {
            'policy_id': 'CR005-fastmoss-20261030', 'path': FASTMOSS_DEFERRAL_PATH,
            'sha256': FASTMOSS_DEFERRAL_SHA256, 'scope': {'request': 2, 'response': 0}}])
        self.assertEqual(relayer_deferral_digest(), RELAYER_DEFERRAL_SHA256)
        _policy(policy.metadata)
        ids = sorted(item['gate_identity'][1] for item in RELAYER_DEFERRAL['items'])
        self.assertEqual(ids, ['any_polymarket_relayer_apis_v1_polymarket_relayer_f3537f',
                               'any_polymarket_relayer_apis_v1_polymarket_submit',
                               'any_polymarket_relayer_apis_v1_polymarket_transactions'])
        for item in RELAYER_DEFERRAL['items']:
            key = item['gate_identity']
            self.assertTrue(policy.matches('polymarket-relayer', 'request', key))
            self.assertFalse(policy.matches('polymarket-relayer', 'response', key))
            self.assertFalse(policy.matches('polymarket-bridge', 'request', key))
            for index in range(len(key)):
                changed = list(key); changed[index] = 'changed'
                self.assertFalse(policy.matches('polymarket-relayer', 'request', changed), index)

    def test_edited_or_widened_record_fails_closed(self):
        base = approval('other', [['x'] * 8])
        widened = copy.deepcopy(RELAYER_DEFERRAL)
        widened['items'].append({**widened['items'][0], 'provider': 'polymarket-bridge'})
        for record in (widened, {**RELAYER_DEFERRAL, 'policy_id': 'CR005'}):
            with self.assertRaisesRegex(ValueError, 'Relayer deferral record differs'):
                _apply_relayer_policy(copy.deepcopy(base), record)
        overlap = approval('polymarket-relayer', [RELAYER_DEFERRAL['items'][0]['gate_identity']])
        with self.assertRaisesRegex(ValueError, 'Invalid Relayer deferral scope'):
            _apply_relayer_policy(overlap)

    def test_rejection_metadata_requires_closed_additional_policy_rows(self):
        metadata = load_deferred_definitions(ROOT).metadata
        for bad in ([], [{**metadata['additional_policies'][0], 'extra': 1}],
                    [{**metadata['additional_policies'][0], 'sha256': 'x'}]):
            with self.assertRaises(ValueError):
                _policy({**metadata, 'additional_policies': bad})


class FastMossDeferralRecordTests(unittest.TestCase):
    def test_loaded_after_cr004_with_exactly_two_fastmoss_request_keys(self):
        policy = load_deferred_definitions(ROOT)
        self.assertEqual(fastmoss_deferral_digest(), FASTMOSS_DEFERRAL_SHA256)
        self.assertEqual(policy.metadata['additional_policies'][-1]['policy_id'], 'CR005-fastmoss-20261030')
        _policy(policy.metadata)
        self.assertEqual(sorted(item['gate_identity'][2] for item in FASTMOSS_DEFERRAL['items']),
                         ['/apis/v1/fastmoss/creator/productList', '/apis/v1/fastmoss/creator/rank/topEcommerce'])
        for item in FASTMOSS_DEFERRAL['items']:
            key = item['gate_identity']
            self.assertTrue(policy.matches('fastmoss', 'request', key))
            self.assertFalse(policy.matches('fastmoss', 'response', key))
            self.assertFalse(policy.matches('other', 'request', key))
            for index in range(len(key)):
                changed = list(key); changed[index] = 'changed'
                self.assertFalse(policy.matches('fastmoss', 'request', changed), index)

    def test_edited_or_widened_record_fails_closed(self):
        base = approval('other', [['x'] * 8])
        widened = copy.deepcopy(FASTMOSS_DEFERRAL)
        widened['items'].append({**widened['items'][0], 'provider': 'other'})
        for record in (widened, {**FASTMOSS_DEFERRAL, 'policy_id': 'CR006'}):
            with self.assertRaisesRegex(ValueError, 'FastMoss deferral record differs'):
                _apply_fastmoss_policy(copy.deepcopy(base), record)
        overlap = approval('fastmoss', [FASTMOSS_DEFERRAL['items'][0]['gate_identity']])
        with self.assertRaisesRegex(ValueError, 'Invalid FastMoss deferral scope'):
            _apply_fastmoss_policy(overlap)


if __name__ == '__main__':
    unittest.main()
