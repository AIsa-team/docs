"""Frozen full-catalog acceptance must account for guarded retention, not hide drops."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import yaml  # noqa: E402

from prepare_full_catalog import reconcile  # noqa: E402

SERVER = [{'url': 'https://api.aisa.one'}]
SEARCH, ITEM, LIST = '/apis/v1/beta/search', '/apis/v1/beta/item', '/apis/v1/alpha/list'
QUERY = {'in': 'query', 'name': 'q', 'schema': {'type': 'string'}}
LEGACY_HEADER = {'in': 'header', 'name': 'x-legacy', 'schema': {'type': 'string'}}
GUARD = 'source header parameters are not forwarded by runtime: x-legacy'


def document(paths):
    return {'openapi': '3.1.0', 'servers': SERVER, 'paths': paths,
            'info': {'title': 'fixture', 'x-aisa-document': {'composer_version': 'fixture', 'document_hash': 'sha256:fixture'}}}


def operation(operation_id, *parameters):
    return {'operationId': operation_id, 'x-aisa-status': 'enabled', 'parameters': list(parameters)}


def row(path, method, operation_id, status='composed', **extra):
    return {'catalog': path.split('/')[3], 'path': path, 'method': method, 'operation_id': operation_id,
            'status': status, 'reason': None, **extra}


def retained(path, method, operation_id):
    return row(path, method, operation_id, 'pending', publication_state='retained',
               reason="published identity changed or disappeared: get_any_beta_search (('/apis/v1/beta/search', 'get'))")


class FullSetReconciliationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = self.root = Path(directory.name)
        self.facts = {
            'alpha': {'openapi': '3.1.0', 'servers': SERVER, 'info': {'x-aisa-document': {'facts_hash': 'a'}},
                      'paths': {LIST: {'get': operation('get_alpha_list', {'in': 'query', 'name': 'limit'})}}},
            'beta': {'openapi': '3.1.0', 'servers': SERVER, 'info': {'x-aisa-document': {'facts_hash': 'b'}},
                     'paths': {SEARCH: {'x-aisa-any': operation('any_beta_search', QUERY)},
                               ITEM: {'get': operation('get_beta_item')}}}}
        # Last-good beta already published an unforwarded header before the
        # merged guard existed; the stricter guard now rejects its recomposition.
        self.documents = {
            'alpha': document({'/apis/v1/alpha/list': {'get': operation('get_alpha_list', {'in': 'query', 'name': 'limit'})}}),
            'beta': document({SEARCH: {'get': operation('get_any_beta_search', QUERY, LEGACY_HEADER),
                                       'post': operation('post_any_beta_search', QUERY)},
                              ITEM: {'get': operation('get_beta_item')}})}
        self.frozen_coverage = {'schema_version': 2, 'providers': {
            'alpha': [row(LIST, 'GET', 'get_alpha_list')],
            'beta': [row(SEARCH, 'GET', 'get_any_beta_search'), row(SEARCH, 'POST', 'post_any_beta_search'),
                     row(ITEM, 'GET', 'get_beta_item')]}}
        self.coverage = {'schema_version': 2, 'providers': {
            'alpha': [row(LIST, 'GET', 'get_alpha_list')],
            'beta': [retained(SEARCH, 'ANY', 'any_beta_search'), retained(ITEM, 'GET', 'get_beta_item')]}}
        self.frozen_pending = {'providers': {'alpha': [], 'beta': []}}
        self.pending = {'providers': {'alpha': [], 'beta': [
            {'operation_id': 'any_beta_search', 'path': SEARCH, 'method': 'GET', 'reason': GUARD},
            {'operation_id': 'any_beta_search', 'path': SEARCH, 'method': 'POST', 'reason': GUARD},
            {'reason': "published identity changed or disappeared: get_any_beta_search (('/apis/v1/beta/search', 'get'))"}]}}
        self.registry = {'auto_register': True, 'providers': {'alpha': {}, 'beta': {}}}

    def write(self, root, documents, coverage=None, pending=None):
        (root / 'openapi').mkdir(parents=True, exist_ok=True)
        for name, value in documents.items():
            (root / f'openapi/{name}.json').write_text(json.dumps(value))
        if coverage is not None:
            (root / 'openapi/coverage.json').write_text(json.dumps(coverage))
        if pending is not None:
            (root / 'openapi/pending.json').write_text(json.dumps(pending))

    def run_reconcile(self, candidate_documents=None, expected_documents=None):
        candidate_documents = candidate_documents or self.documents
        self.write(self.root / 'expected', expected_documents or candidate_documents,
                   self.frozen_coverage, self.frozen_pending)
        self.write(self.root / 'input', self.documents)
        candidate = self.root / 'candidate'
        self.write(candidate, candidate_documents, self.coverage, self.pending)
        (candidate / 'openapi/registry.yaml').write_text(yaml.safe_dump(self.registry))
        (candidate / 'facts').mkdir()
        for name, value in self.facts.items():
            (candidate / f'facts/{name}.json').write_text(json.dumps(value))
        return reconcile(self.root / 'expected', candidate, self.coverage, last_good_root=self.root / 'input')

    def codes(self, result):
        return {error[0] for error in result.get('coverage_ledger', {}).get('errors', [])}

    def test_guarded_retention_accounts_for_every_frozen_and_candidate_row(self):
        result = self.run_reconcile()
        ledger = result['coverage_ledger']
        self.assertEqual(result['status'], 'passed', ledger['errors'])
        self.assertFalse(result['coverage_identity_sets_equal'])  # raw difference stays visible
        self.assertTrue(result['operation_identity_sets_equal'])
        self.assertEqual((ledger['frozen_rows'], ledger['candidate_rows'], ledger['unchanged_rows']), (4, 3, 1))
        self.assertEqual((ledger['retained_frozen_rows'], ledger['retained_candidate_rows']), (3, 2))
        self.assertEqual(ledger['frozen_rows'], ledger['unchanged_rows'] + ledger['retained_frozen_rows'])
        self.assertEqual(ledger['candidate_rows'], ledger['unchanged_rows'] + ledger['retained_candidate_rows'])
        self.assertEqual(ledger['any_collapsed_routes'], [('beta', SEARCH, ['GET', 'POST'])])
        self.assertEqual(ledger['source_guard_block_causes'], {'beta': [f'{SEARCH} GET', f'{SEARCH} POST']})
        # Already-published exposure is retained unchanged and reported, never fresh.
        self.assertEqual(ledger['retained_preexisting_unforwarded_inputs'], 1)

    def test_identical_ledger_passes_without_retention_rules(self):
        self.coverage = copy.deepcopy(self.frozen_coverage)
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'passed')
        self.assertNotIn('coverage_ledger', result)

    def test_retained_document_dropping_operation_is_rejected(self):
        dropped = copy.deepcopy(self.documents)
        del dropped['beta']['paths'][SEARCH]['post']
        result = self.run_reconcile(candidate_documents=dropped, expected_documents=self.documents)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['operation_identity_sets_equal'])
        self.assertTrue({'retained_document_not_last_good'} <= self.codes(result))

    def test_last_good_missing_operation_cannot_hide_behind_any_collapse(self):
        self.documents['beta']['paths'][SEARCH].pop('post')
        expected = copy.deepcopy(self.documents)
        expected['beta']['paths'][SEARCH]['post'] = operation('post_any_beta_search', QUERY)
        result = self.run_reconcile(candidate_documents=self.documents, expected_documents=expected)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue({'any_collapse_hides_retained_operation', 'retained_operation_missing',
                         'unaccounted_frozen_row'} <= self.codes(result))

    def test_dropped_coverage_row_is_rejected(self):
        self.coverage['providers']['beta'].pop()
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn(['unaccounted_frozen_row', 'beta', ITEM, 'GET', 'get_beta_item', 'composed'],
                      result['coverage_ledger']['errors'])

    def test_unblocked_provider_cannot_change_status_or_method(self):
        for changed in ({'status': 'pending', 'reason': 'operation_not_composed'}, {'method': 'POST'}):
            with self.subTest(changed=changed):
                self.root = Path(tempfile.mkdtemp(dir=self.base))
                self.coverage['providers']['alpha'] = [{**row(LIST, 'GET', 'get_alpha_list'), **changed}]
                result = self.run_reconcile()
                self.assertEqual(result['status'], 'failed')
                self.assertTrue({'unaccounted_frozen_row', 'unaccounted_candidate_row'} <= self.codes(result))

    def test_pending_cannot_become_complete(self):
        self.frozen_coverage['providers']['alpha'] = [row(LIST, 'GET', 'get_alpha_list', 'pending', reason='operation_not_composed')]
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('unaccounted_candidate_row', self.codes(result))

    def test_retained_row_claiming_fresh_composition_breaks_retention(self):
        self.coverage['providers']['beta'][1] = row(ITEM, 'GET', 'get_beta_item')
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('unaccounted_candidate_row', self.codes(result))

    def test_block_not_caused_by_source_guard_is_rejected(self):
        for entry in self.pending['providers']['beta'][:2]:
            entry['reason'] = 'upstream operation missing'
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue({'unaccepted_block_cause', 'retention_without_source_guard_block'} <= self.codes(result))

    def test_identity_block_unrelated_to_guarded_operation_is_rejected(self):
        self.pending['providers']['beta'][2]['reason'] = \
            "published identity changed or disappeared: get_beta_item (('/apis/v1/beta/item', 'get'))"
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('unaccepted_block_cause', self.codes(result))

    def test_any_collapse_requires_runtime_any_identity(self):
        self.facts['beta']['paths'][SEARCH] = {'get': operation('any_beta_search', QUERY)}
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('any_collapse_without_runtime_any', self.codes(result))

    def test_fresh_composition_cannot_expose_unforwarded_input(self):
        for parameter in (LEGACY_HEADER, {'in': 'query', 'name': 'cursor'}):
            with self.subTest(parameter=parameter['name']):
                self.root = Path(tempfile.mkdtemp(dir=self.base))
                self.documents['alpha']['paths'][LIST]['get']['parameters'] = [{'in': 'query', 'name': 'limit'}, parameter]
                result = self.run_reconcile()
                self.assertEqual(result['status'], 'failed')
                self.assertIn('unforwarded_input_exposed', self.codes(result))

    def test_declared_caller_header_or_query_passthrough_is_forwarded(self):
        self.facts['alpha']['paths'][LIST]['get']['x-aisa-caller-headers'] = ['X-Legacy']
        self.facts['alpha']['paths'][LIST]['get']['x-aisa-query-policy'] = {'request_wins': True}
        self.documents['alpha']['paths'][LIST]['get']['parameters'] += [LEGACY_HEADER, {'in': 'query', 'name': 'cursor'}]
        self.assertEqual(self.run_reconcile()['status'], 'passed')

    def test_retained_provider_cannot_add_new_unforwarded_exposure(self):
        exposed = copy.deepcopy(self.documents)
        exposed['beta']['paths'][ITEM]['get']['parameters'] = [LEGACY_HEADER]
        result = self.run_reconcile(candidate_documents=exposed)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue({'retained_document_not_last_good', 'unforwarded_input_exposed'} <= self.codes(result))

    def test_duplicate_candidate_rows_cannot_mask_drops(self):
        self.coverage['providers']['alpha'].append(row(LIST, 'GET', 'get_alpha_list'))
        result = self.run_reconcile()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('duplicate_coverage_row', self.codes(result))


if __name__ == '__main__':
    unittest.main()
