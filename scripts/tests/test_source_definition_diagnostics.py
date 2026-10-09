import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from contract_readiness import _pending_key, reason_code
from gap_evidence import enrich_coverage
from runtime_registry import coverage_rows


class SourceDefinitionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.facts = {'openapi': '3.1.0', 'info': {'x-aisa-document': {'facts_hash': 'fixture'}},
                      'paths': {'/public': {'x-aisa-any': {
                          'operationId': 'stable_id', 'x-aisa-status': 'enabled',
                          'x-aisa-validation': 'provider', 'x-aisa-upstream-path': '/search'}}}}
        self.source = {'openapi': '3.1.0', 'paths': {}, 'info': {'x-aisa-source': {
            'kind': 'provider_openapi', 'url': 'https://official.invalid/reference',
            'fetched_at': '2026-10-09T00:00:00Z', 'content_hash': 'locked', 'converter': 'typed',
            'pending_references': [{'path': '/search', 'method': 'GET',
                                    'reason': 'search_text: required/optional is not stated'}]}}}

    def test_exact_incomplete_definition_explains_pending_without_any_authority(self):
        document, pending = compose(self.facts, self.source)
        self.assertEqual(document['paths'], {})
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['method'], 'ANY')
        self.assertTrue(pending[0]['reason'].startswith('source definition incomplete: search_text:'))
        self.assertEqual(pending[0]['source_definition_diagnostics'][0]['method'], 'GET')
        self.assertEqual(reason_code(pending[0]['reason']), 'upstream_operation_missing')
        before = [{k: v for k, v in pending[0].items() if k != 'source_definition_diagnostics'}]
        before[0]['reason'] = 'upstream operation missing'
        for status in ('enabled', 'disabled'):
            with self.subTest(status=status):
                self.facts['paths']['/public']['x-aisa-any']['x-aisa-status'] = status
                old = enrich_coverage(coverage_rows(self.facts, document, before, ['p']), self.facts, self.source, {})
                new = enrich_coverage(coverage_rows(self.facts, document, pending, ['p']), self.facts, self.source, {})
                self.assertEqual(_pending_key(old[0]), _pending_key(new[0]))
                self.assertEqual({k: v for k, v in old[0].items() if k != 'reason'},
                                 {k: v for k, v in new[0].items() if k != 'reason'})

    def test_concrete_method_requires_matching_pending_reference(self):
        operation = self.facts['paths']['/public'].pop('x-aisa-any')
        self.facts['paths']['/public']['get'] = operation
        self.assertTrue(compose(self.facts, self.source)[1][0]['reason'].startswith('source definition incomplete:'))
        self.facts['paths']['/public'] = {'post': operation}
        self.assertEqual(compose(self.facts, self.source)[1][0]['reason'], 'upstream operation missing')

    def test_unrelated_or_invalid_metadata_does_not_relabel_missing_operation(self):
        for references in ([], None, {}, [None], [{'path': '/other', 'method': 'GET', 'reason': 'incomplete'}],
                           [{'path': '/search', 'method': 'ANY', 'reason': 'incomplete'}],
                           [{'path': '/search', 'method': 'GET', 'reason': ''}]):
            with self.subTest(references=references):
                source = copy.deepcopy(self.source)
                source['info']['x-aisa-source']['pending_references'] = references
                pending = compose(self.facts, source)[1]
                self.assertEqual(pending[0]['reason'], 'upstream operation missing')
                self.assertNotIn('source_definition_diagnostics', pending[0])

    def test_response_only_and_unselected_sources_cannot_explain_request_authority(self):
        self.source['info']['x-aisa-source']['response_only'] = True
        self.assertEqual(compose(self.facts, self.source)[1][0]['reason'], 'upstream operation missing')
        self.source['info']['x-aisa-source'].pop('response_only')
        other = copy.deepcopy(self.source)
        other['info']['x-aisa-source'].update(url='https://other.invalid/spec', pending_references=[])
        pending = compose(self.facts, [self.source, other], source_bindings={'/public': 'https://other.invalid/spec'})[1]
        self.assertNotIn('source_definition_diagnostics', pending[0])
        self.assertIn('bound source does not match', pending[0]['reason'])

    def test_existing_complete_operation_is_not_downgraded_by_stale_diagnostic(self):
        self.source['paths']['/search'] = {'get': {'parameters': [],
                                                  'responses': {'204': {'description': 'No content'}}}}
        document, pending = compose(self.facts, self.source)
        self.assertEqual(pending, [])
        self.assertIn('get', document['paths']['/public'])

    def test_selector_failure_is_not_relabelled_by_path_only_evidence(self):
        self.facts['paths']['/public']['x-aisa-any']['x-aisa-upstream-selector'] = {
            'in': 'query', 'name': 'engine', 'value': 'google', 'mode': 'fixed'}
        pending = compose(self.facts, self.source)[1]
        self.assertEqual(pending[0]['reason'], 'upstream selector has no matching official operation')
        self.assertNotIn('source_definition_diagnostics', pending[0])


if __name__ == '__main__':
    unittest.main()
