import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, has_response_contract, resolve
from gap_evidence import response_gap_rows, assess_response_gaps
from test_runtime_contracts import facts, mirror, operation


class ResponseSchemaCompletenessTests(unittest.TestCase):
    def compose_response(self, response):
        runtime, source = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        operation(source)['responses'] = {'200': copy.deepcopy(response)}
        document, pending = compose(runtime, source)
        self.assertEqual(pending, [])  # Request remains usable; response debt is separate.
        return runtime, source, document

    def assert_gap_blocks(self, runtime, document, status='200'):
        self.assertEqual(operation(document)['x-aisa-response-pending']['statuses'], [status])
        gaps = response_gap_rows(document, runtime, [])
        self.assertEqual(gaps[0]['statuses'], [status])
        self.assertEqual(gaps[0]['reason_code'], 'missing_success_payload')
        report = {'status': 'passed', 'blocked_providers': [], 'providers': {'p': {'errors': [], 'status': 'passed'}}}
        assess_response_gaps(report, {'p': runtime}, {'p': document},
                             {'schema_version': 2, 'providers': {'p': []}, 'response_gaps': {'p': gaps}}, None)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['blocked_providers'], ['p'])

    def test_single_and_named_example_only_are_retained_but_not_complete(self):
        for data in ({'example': {'value': True, '$ref': 'literal'}},
                     {'examples': {'one': {'value': {'value': True, '$ref': 'literal'}}}}):
            with self.subTest(data=data):
                runtime, source, document = self.compose_response({'description': 'Example only', 'content': {'application/json': data}})
                self.assertEqual(operation(document)['responses']['200']['content']['application/json'], data)
                self.assert_gap_blocks(runtime, document)
                repeated, pending = compose(runtime, source, previous=document)
                self.assertEqual(pending, [])
                self.assertEqual(document, repeated)

    def test_referenced_example_only_is_retained_for_source_and_history(self):
        runtime, source = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        source['components']['examples'] = {'Sample': {'summary': 'Example', 'value': {'status': True}}}
        operation(source)['responses'] = {'200': {'description': 'Example only', 'content': {
            'application/json': {'examples': {'one': {'$ref': '#/components/examples/Sample'}}}}}}
        first, pending = compose(runtime, source)
        self.assertEqual(pending, [])
        example = operation(first)['responses']['200']['content']['application/json']['examples']['one']
        self.assertEqual(resolve(example, first), source['components']['examples']['Sample'])
        self.assert_gap_blocks(runtime, first)
        historical_runtime = facts('runtime')
        second, pending = compose(historical_runtime, previous=first)
        self.assertEqual(pending, [])
        example = operation(second)['responses']['200']['content']['application/json']['examples']['one']
        self.assertEqual(resolve(example, second), source['components']['examples']['Sample'])
        self.assert_gap_blocks(historical_runtime, second)

    def test_every_declared_media_requires_a_schema_even_with_no_content_marker(self):
        for status in ['200', '204', '205']:
            for extra in ({}, {'x-aisa-no-content': True}):
                with self.subTest(status=status, extra=extra):
                    runtime, source = facts('provider'), mirror()
                    operation(runtime)['x-aisa-passthrough'] = True
                    media = {'application/json': {'schema': {'type': 'string'}, 'example': 'ok'},
                             'text/plain': {'example': 'ok'}}
                    operation(source)['responses'] = {status: {'description': 'Mixed', 'content': media, **extra}}
                    document, pending = compose(runtime, source)
                    self.assertEqual(pending, [])
                    self.assertEqual(operation(document)['responses'][status]['content'], media)
                    self.assert_gap_blocks(runtime, document, status)

    def test_explicit_dict_boolean_schemas_and_no_content_are_complete(self):
        for schema in ({}, True, False):
            with self.subTest(schema=schema):
                runtime, source, document = self.compose_response({'description': 'Declared', 'content': {
                    'application/json': {'schema': schema, 'example': True}}})
                self.assertNotIn('x-aisa-response-pending', operation(document))
                self.assertEqual(response_gap_rows(document, runtime, []), [])
                self.assertIs(type(operation(document)['responses']['200']['content']['application/json']['schema']), type(schema))
        for status in ['200', '204', '205']:
            runtime, source = facts('provider'), mirror()
            operation(runtime)['x-aisa-passthrough'] = True
            operation(source)['responses'] = {status: {'description': 'No content', **(
                {'x-aisa-no-content': True} if status == '200' else {})}}
            document, pending = compose(runtime, source)
            self.assertEqual(pending, [])
            self.assertNotIn('x-aisa-response-pending', operation(document))
            self.assertEqual(response_gap_rows(document, runtime, []), [])
            self.assertEqual(set(operation(document)['responses']), {status})
            repeated, _ = compose(runtime, source, previous=document)
            self.assertNotIn('x-aisa-response-pending', operation(repeated))

    def test_invalid_schema_types_do_not_count_as_complete(self):
        for value in (None, 0, 1, 'object', []):
            with self.subTest(value=value):
                self.assertFalse(has_response_contract({'content': {'application/json': {'schema': value}}}))
        self.assertFalse(has_response_contract({'content': {}}))

    def test_runtime_example_authority_cannot_be_replaced_to_hide_schema_debt(self):
        runtime, source = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        declared = {'description': 'Runtime wrapper', 'headers': {'X-Request-ID': {'schema': {'type': 'string'}}},
                    'content': {'application/json': {'example': {'wrapped': True}}}}
        operation(runtime)['responses']['200'] = copy.deepcopy(declared)
        operation(source)['responses'] = {'200': {'description': 'Provider', 'content': {
            'application/json': {'schema': {'type': 'integer'}}}}}
        document, pending = compose(runtime, source)
        self.assertEqual(pending, [])
        self.assertEqual(operation(document)['responses']['200'], declared)
        self.assert_gap_blocks(runtime, document)
        self.assertNotIn('x-aisa-response-source', operation(document))


if __name__ == '__main__':
    unittest.main()
