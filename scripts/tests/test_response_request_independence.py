"""Response debt must survive request edits without hiding response changes."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_readiness import binding_hash
from deferred_definitions import DeferredDefinitions
from gap_evidence import (assess_response_gaps, enrich_coverage, gap_key,
                          response_gap_rows, response_runtime_binding)


class ResponseRequestIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.independent = True
        self.fact = {
            'operationId': 'read', 'x-aisa-status': 'enabled',
            'x-aisa-validation': 'runtime', 'x-aisa-upstream-path': '/read',
            'x-aisa-revision': {'profile_ref': 'profile-v1', 'customer_pricing_ref': 'price-v1'},
            'parameters': [{'name': 'q', 'in': 'query', 'required': False,
                            'schema': {'$ref': '#/components/schemas/Query'}}],
            'requestBody': {'content': {'application/json': {'schema': {
                'type': 'object', 'properties': {'limit': {'type': 'integer'}}}}}},
            'responses': {'200': {'description': 'Unknown success payload'}},
        }
        self.facts = {
            'openapi': '3.1.0', 'servers': [{'url': 'https://api.example'}],
            'security': [{'bearerAuth': []}],
            'components': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer'}},
                           'schemas': {'Query': {'type': 'string'}}},
            'paths': {'/read': {'post': self.fact}},
        }
        self.upstream = {
            'openapi': '3.1.0', 'info': {'x-aisa-source': {
                'url': 'https://provider.example/spec', 'kind': 'provider_openapi'}},
            'paths': {'/read': {'post': copy.deepcopy(self.fact)}},
            'components': copy.deepcopy(self.facts['components']),
        }

    def evidence(self, independent=None):
        independent = self.independent if independent is None else independent
        row = {'path': '/read', 'method': 'POST', 'operation_id': 'read',
               'binding_hash': binding_hash(self.fact, self.facts)}
        rows = enrich_coverage([row], self.facts, self.upstream, {}, response_identity_v2=independent)
        return rows, response_gap_rows(self.facts, self.facts, rows, response_identity_v2=independent)

    def assessment(self, baseline):
        rows, gaps = self.evidence()
        report = {'status': 'passed', 'blocked_providers': [],
                  'providers': {'p': {'status': 'passed', 'errors': []}}}
        policy = DeferredDefinitions({'policy_id': 'synthetic mode fixture', 'scope': {}, 'items': []})
        if self.independent:
            policy.response_v2_keys = frozenset({'synthetic mode marker; not an exemption'})
        assess_response_gaps(report, {'p': self.facts}, {'p': self.facts},
                             {'schema_version': 2, 'providers': {'p': rows},
                              'response_gaps': {'p': gaps}},
                             {'response_gaps': {'p': baseline}}, policy)
        return report

    def test_parameter_type_required_enum_default_and_body_edits_propagate(self):
        rows, before = self.evidence()
        original_request = rows[0]['source_binding_hash']
        mutations = (
            lambda: self.facts['components']['schemas']['Query'].update(type='integer'),
            lambda: self.fact['parameters'][0].update(required=True),
            lambda: self.facts['components']['schemas']['Query'].update(enum=[1, 2]),
            lambda: self.facts['components']['schemas']['Query'].update(default=2),
            lambda: self.fact['requestBody'].update(required=True),
            lambda: self.fact['requestBody']['content']['application/json']['schema'].update(required=['limit']),
            lambda: self.fact['x-aisa-revision'].update(profile_ref='profile-v2'),
            lambda: self.upstream['paths']['/read']['post']['parameters'][0].update(required=True),
        )
        for change in mutations:
            change()
            after_rows, after = self.evidence()
            self.assertNotEqual(original_request, after_rows[0]['source_binding_hash'])
            self.assertEqual(gap_key(before[0]), gap_key(after[0]))
            report = self.assessment(before)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(len(report['providers']['p']['existing_response_pending']), 1)
            # The response is still unknown: passing this gate creates no schema.
            self.assertNotIn('content', self.fact['responses']['200'])

    def test_price_only_updates_preserve_response_identity(self):
        _, before = self.evidence()
        self.fact['x-aisa-pricing'] = {'kind': 'fixed_success', 'customer_unit_price_usd': 0.005}
        self.fact['x-aisa-revision']['customer_pricing_ref'] = 'price-v2'
        _, after = self.evidence()
        self.assertEqual(gap_key(before[0]), gap_key(after[0]))

    def test_response_route_selector_provider_and_public_auth_changes_are_new_debt(self):
        cases = (
            lambda: self.fact.update(operationId='other'),
            lambda: self.fact.update({'x-aisa-upstream-path': '/another'}),
            lambda: self.fact.update({'x-aisa-upstream-selector': {'Action': 'Other'}}),
            lambda: self.facts.update(info={'x-aisa-provider': 'other'}),
            lambda: self.fact.update({'x-aisa-lifecycle': {'kind': 'changed'}}),
            lambda: self.fact.update({'x-aisa-response-passthrough': True}),
            lambda: self.facts.update(security=[]),
            lambda: self.fact.update(security=[]),
            lambda: self.facts['components']['securitySchemes']['bearerAuth'].update(scheme='basic'),
            lambda: self.fact['responses'].update({'201': {'description': 'unknown'}}),
            lambda: self.upstream['info']['x-aisa-source'].update(url='https://other.example/spec'),
            lambda: self.upstream['paths']['/read']['post']['responses'].update({'202': {'content': {
                'application/json': {'schema': {'type': 'object'}}}}}),
        )
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                self.setUp()
                _, before = self.evidence()
                change()
                _, after = self.evidence()
                self.assertNotEqual(gap_key(before[0]), gap_key(after[0]))
                self.assertEqual(self.assessment(before)['status'], 'failed')

    def test_runtime_disabled_status_is_new_debt_that_does_not_block(self):
        _, before = self.evidence()
        self.fact.update({'x-aisa-status': 'disabled'})
        _, after = self.evidence()
        # The status is part of the gap identity, so the approved debt no longer
        # matches; the runtime serves nothing for a disabled operation, so the
        # new debt is recorded in disabled_response_pending without blocking.
        self.assertNotEqual(gap_key(before[0]), gap_key(after[0]))
        report = self.assessment(before)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual([row['runtime_status'] for row in report['providers']['p']['disabled_response_pending']], ['disabled'])
        self.assertEqual(report['providers']['p']['new_response_pending'], [])

    def test_public_method_and_path_are_bound_independently(self):
        original = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.assertNotEqual(original, response_runtime_binding(self.fact, self.facts, '/other', 'POST'))
        self.assertNotEqual(original, response_runtime_binding(self.fact, self.facts, '/read', 'GET'))

    def test_literal_security_names_and_selector_values_are_not_schema_prose(self):
        self.facts['security'] = [{'description': []}]
        self.facts['components']['securitySchemes']['description'] = {'type': 'http', 'scheme': 'bearer'}
        original = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.facts['components']['securitySchemes']['description']['scheme'] = 'basic'
        self.assertNotEqual(original, response_runtime_binding(self.fact, self.facts, '/read', 'POST'))
        self.fact['x-aisa-upstream-selector'] = {'query': {'description': 'selected-action'}}
        original = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.fact['x-aisa-upstream-selector']['query']['description'] = 'different-action'
        self.assertNotEqual(original, response_runtime_binding(self.fact, self.facts, '/read', 'POST'))

    def test_path_server_inheritance_and_operation_override_are_bound(self):
        original = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.facts['paths']['/read']['servers'] = [{'url': 'https://other.example'}]
        path = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.assertNotEqual(original, path)
        self.fact['servers'] = [{'url': 'https://operation.example'}]
        op = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.assertNotEqual(path, op)
        self.facts['paths']['/read']['servers'] = [{'url': 'https://ignored.example'}]
        self.assertEqual(op, response_runtime_binding(self.fact, self.facts, '/read', 'POST'))

    def test_old_policy_mode_keeps_legacy_request_sensitive_keys(self):
        self.independent = False
        _, before = self.evidence()
        self.assertNotIn('response_runtime_binding_hash', before[0])
        self.fact['parameters'][0]['required'] = True
        _, after = self.evidence()
        self.assertNotEqual(gap_key(before[0]), gap_key(after[0]))
        self.assertEqual(self.assessment(before)['status'], 'failed')

    def test_new_identity_version_never_automatically_inherits_old_debt(self):
        _, before = self.evidence(False)
        self.assertEqual(self.assessment(before)['status'], 'failed')

    def test_unresolved_auth_fail_closed(self):
        self.facts['security'] = [{'missingAuth': []}]
        with self.assertRaisesRegex(ValueError, 'security scheme'):
            self.evidence()

    def test_reachable_auth_definition_changes_are_bound(self):
        self.facts['components']['securitySchemes']['bearerAuth'] = {'$ref': '#/components/securitySchemes/Actual'}
        self.facts['components']['securitySchemes']['Actual'] = {'type': 'http', 'scheme': 'bearer'}
        original = response_runtime_binding(self.fact, self.facts, '/read', 'POST')
        self.facts['components']['securitySchemes']['Actual']['scheme'] = 'basic'
        self.assertNotEqual(original, response_runtime_binding(self.fact, self.facts, '/read', 'POST'))


if __name__ == '__main__':
    unittest.main()
