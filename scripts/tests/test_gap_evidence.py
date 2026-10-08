import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gap_evidence import source_binding_evidence, response_gap_rows, gap_key, assess_response_gaps
from contract_readiness import _schema_contract


class GapEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fact = {'operationId': 'read', 'x-aisa-upstream-path': '/read',
                     'x-aisa-status': 'enabled', 'x-aisa-validation': 'provider'}
        self.facts = {'paths': {'/read': {'get': self.fact}}}
        self.source = {'openapi': '3.1.0', 'info': {'x-aisa-source': {'url': 'https://official.invalid/spec'}},
                       'paths': {'/read': {'get': {'parameters': [{'in': 'query', 'name': 'q',
                           'schema': {'$ref': '#/components/schemas/Q'}}]}}},
                       'components': {'schemas': {'Q': {'type': 'string'}, 'Unused': {'type': 'integer'}}}}

    def hash(self):
        return source_binding_evidence(self.fact, self.facts, self.source, {}, '/read', 'GET')

    def test_relevant_source_change_invalidates_without_global_churn(self):
        original = self.hash()
        self.source['info']['x-aisa-source'].update(content_hash='changed', fetched_at='later')
        self.source['components']['schemas']['Unused']['type'] = 'number'
        self.source['components']['schemas']['Q']['description'] = 'Editorial'
        self.assertEqual(original, self.hash())
        self.source['components']['schemas']['Q']['type'] = 'integer'
        self.assertNotEqual(original, self.hash())

    def test_private_error_change_does_not_change_request_debt(self):
        original = self.hash()
        self.source['paths']['/read']['get']['responses'] = {'401': {'description': 'private'}}
        self.assertEqual(original, self.hash())

    def test_protocol_maps_keep_names_that_match_annotation_keywords(self):
        declaration = {'responses': {'default': {'headers': {
            'description': {'schema': {'type': 'string'}}}, 'description': 'prose'}},
            'security': [{'description': ['scope']}],
            'links': {'description': {'operationId': 'next', 'parameters': {
                'x': {'description': 'literal', '$ref': 'literal'}}, 'description': 'prose'}}}
        contract = _schema_contract(declaration)
        self.assertEqual(contract['responses']['default']['headers']['description']['schema'], {'type': 'string'})
        self.assertEqual(contract['security'], [{'description': ['scope']}])
        self.assertEqual(contract['links']['description']['parameters']['x']['description'], 'literal')

    def test_ambiguous_response_candidates_cannot_keep_changed_debt(self):
        other = copy.deepcopy(self.source)
        other['paths']['/read']['get']['parameters'][0]['schema'] = {'type': 'integer'}
        self.source['paths']['/read']['get']['responses'] = {'200': {'content': {
            'application/json': {'schema': {'type': 'string'}}}}}
        other['paths']['/read']['get']['responses'] = {'200': {'content': {
            'application/json': {'schema': {'type': 'integer'}}}}}
        def fingerprint():
            return source_binding_evidence(self.fact, self.facts, [self.source, other], {}, '/read', 'GET', response=True)
        before = fingerprint()
        other['paths']['/read']['get']['responses']['200']['content']['application/json']['schema']['type'] = 'number'
        self.assertNotEqual(before, fingerprint())
        before = fingerprint()
        other['info']['x-aisa-source']['url'] = 'https://another.invalid/spec'
        self.assertNotEqual(before, fingerprint())

    def test_response_unknown_unconstrained_and_no_content_are_distinct(self):
        op = dict(self.fact, responses={'200': {'description': 'unknown'},
            '204': {'description': 'none'}, '2XX': {'content': {'application/json': {'schema': {}}}}})
        doc = {'paths': {'/read': {'get': op}}}
        row = {'path': '/read', 'method': 'GET', 'binding_hash': 'binding',
               'source_binding_hash': 'request', 'response_source_binding_hash': 'response'}
        gaps = response_gap_rows(doc, self.facts, [row])
        self.assertEqual(gaps[0]['statuses'], ['200'])
        key = gap_key(gaps[0])
        self.assertIsNotNone(key)
        changed = copy.deepcopy(gaps[0]); changed['operation_id'] = 'replacement'
        self.assertNotEqual(key, gap_key(changed))
        changed = copy.deepcopy(gaps[0]); changed['runtime_status'] = 'disabled'
        self.assertNotEqual(key, gap_key(changed))
        changed.pop('response_source_binding_hash')
        self.assertIsNone(gap_key(changed))
        op['responses']['204']['content'] = {'application/json': {}}
        self.assertEqual(response_gap_rows(doc, self.facts, [row])[0]['statuses'], ['200', '204'])

    def test_exact_response_debt_and_equal_count_replacement(self):
        doc = {'paths': {'/read': {'get': dict(self.fact, responses={'200': {'description': 'unknown'}})}}}
        rows = [{'path': '/read', 'method': 'GET', 'binding_hash': 'binding',
                 'source_binding_hash': 'request', 'response_source_binding_hash': 'response'}]
        gaps = response_gap_rows(doc, self.facts, rows)
        coverage = {'schema_version': 2, 'providers': {'p': rows}, 'response_gaps': {'p': gaps}}
        def run(baseline):
            report = {'status': 'passed', 'blocked_providers': [], 'providers': {'p': {'errors': [], 'status': 'passed'}}}
            assess_response_gaps(report, {'p': self.facts}, {'p': doc}, coverage, baseline)
            return report
        self.assertEqual(run({'response_gaps': {'p': gaps}})['status'], 'passed')
        changed = copy.deepcopy(gaps); changed[0]['operation_id'] = 'other'
        self.assertEqual(run({'response_gaps': {'p': changed}})['status'], 'failed')
        self.assertEqual(run({'response_gaps': {}})['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
