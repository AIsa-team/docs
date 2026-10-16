import copy
import unittest

from audit_request_input_forwarding import audit_provider, missing_header_inputs, missing_query_inputs
from test_runtime_contracts import facts, mirror, operation


class RequestInputForwardingTests(unittest.TestCase):
    def test_optional_and_required_inputs_cannot_silently_disappear(self):
        for required in (False, True):
            with self.subTest(required=required):
                runtime, source = facts('mixed'), mirror()
                operation(source)['parameters'].append({'in': 'query', 'name': 'cursor', 'required': required})
                rows = audit_provider('example', runtime, source, {}, {})
                self.assertEqual(rows[0]['status'], 'blocked')
                self.assertEqual(rows[0]['missing_query_inputs'], ['cursor'])

    def test_auth_excluded_case_sensitive_business_inputs_preserved(self):
        runtime = operation(facts('mixed'))
        source = {'parameters': [{'in': 'query', 'name': n} for n in ('provider_token', 'pageSize', 'pagesize')]}
        runtime['parameters'].append({'in': 'query', 'name': 'pagesize'})
        self.assertEqual(missing_query_inputs(runtime, source, {}, ['provider_token']), ['pageSize'])
        runtime['x-aisa-query-policy'] = {'request_wins': True}
        self.assertEqual(missing_query_inputs(runtime, source, {}), [])

    def test_inherited_source_and_runtime_fields_and_refs(self):
        runtime, source = facts('mixed'), mirror()
        source['components']['parameters'] = {'Cursor': {'in': 'query', 'name': 'cursor', 'schema': {'type': 'string'}}}
        source['paths']['/provider/test']['parameters'] = [{'$ref': '#/components/parameters/Cursor'}]
        rows = audit_provider('example', runtime, source, {}, {})
        self.assertEqual(rows[0]['missing_query_inputs'], ['cursor'])
        runtime['paths']['/apis/v1/similarweb/test']['parameters'] = [copy.deepcopy(source['components']['parameters']['Cursor'])]
        self.assertEqual(audit_provider('example', runtime, source, {}, {})[0]['status'], 'passed')

    def test_missing_source_not_counted_as_success(self):
        self.assertEqual(audit_provider('example', facts('mixed'), None, {}, {})[0]['status'], 'source_unverified')

    def test_any_expansion_and_public_mirror_inputs_are_checked(self):
        runtime = facts('mixed', 'x-aisa-any')
        path = '/apis/v1/similarweb/test'
        mirrors = {(path, 'get'): {'operation': {'parameters': [{'in': 'query', 'name': 'cursor'}]}, 'source': {}}}
        rows = audit_provider('example', runtime, None, mirrors, {})
        self.assertEqual([(r['method'], r['status'], r['missing_query_inputs']) for r in rows],
                         [('GET', 'blocked', ['cursor'])])

    def test_bound_missing_source_cannot_pass_using_public_mirror(self):
        runtime, source = facts('mixed'), mirror()
        path = '/apis/v1/similarweb/test'
        source['paths'] = {}
        mirrors = {(path, 'post'): {'operation': {}, 'source': {}}}
        rows = audit_provider('example', runtime, source, mirrors,
                              {path: source['info']['x-aisa-source']['url']})
        self.assertEqual(rows[0]['status'], 'source_unverified')

    def test_typed_header_without_forwarding_declaration_is_blocked(self):
        runtime, source = facts('mixed'), mirror()
        header = {'in': 'header', 'name': 'Parallel-Beta', 'schema': {'type': 'string'}}
        operation(source)['parameters'].append(header)
        operation(runtime)['parameters'].append(copy.deepcopy(header))
        rows = audit_provider('example', runtime, source, {}, {}, include_headers=True)
        self.assertEqual(rows[0]['missing_header_inputs'], ['Parallel-Beta'])
        self.assertEqual(rows[0]['status'], 'blocked')
        operation(runtime)['x-aisa-caller-headers'] = ['parallel-beta']
        self.assertEqual(audit_provider('example', runtime, source, {}, {}, include_headers=True)[0]['status'], 'passed')

    def test_header_auth_ownership_and_accept_remain_distinct(self):
        source = {'parameters': [{'in': 'header', 'name': n} for n in
                  ('Accept', 'X-API-Key', 'provider-secret', 'POLY_BUILDER_SIGNATURE')]}
        self.assertEqual(missing_header_inputs({}, source, {}, ['provider-secret']), ['POLY_BUILDER_SIGNATURE'])
        with self.assertRaisesRegex(ValueError, 'invalid Runtime caller-header'):
            missing_header_inputs({'x-aisa-caller-headers': 'Parallel-Beta'}, source, {})


if __name__ == '__main__':
    unittest.main()
