"""Runtime operations without reviewed inputs are published, marked and honest."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import (compose, is_unreviewed_request, UNREVIEWED_SUCCESS_DESCRIPTION,
                             UNREVIEWED_SUCCESS_SCHEMA)
from contract_readiness import _runtime_body_errors
from runtime_registry import previous_for_facts

SOURCE = {'kind': 'provider_openapi', 'url': 'https://example.invalid/openapi.json',
          'fetched_at': '2026-11-08T00:00:00Z', 'content_hash': 'sha256:' + '0' * 64, 'converter': 'synthetic'}
BODY = {'required': True, 'content': {'application/json': {'schema': {
    'type': 'object', 'required': ['q'], 'additionalProperties': False,
    'properties': {'q': {'type': 'string'}, 'mode': {'oneOf': [{'const': 'a'}, {'const': 'b'}]}}}}}}


def operation(operation_id, status='enabled', validation='provider', upstream_path='/v1/search', **extra):
    value = {'operationId': operation_id, 'summary': 'Search', 'x-aisa-validation': validation,
             'x-aisa-status': status, 'x-aisa-passthrough': True, 'x-aisa-upstream-path': upstream_path,
             'x-aisa-pricing': {'unit': 'request', 'unit_rate_usd': 0.01},
             'responses': {'200': {'description': 'Successful response'}}}
    value.update(extra)
    return value


def facts(paths):
    return {'openapi': '3.1.0', 'info': {'title': 'synthetic', 'x-aisa-document': {'facts_hash': 'synthetic'}},
            'servers': [{'url': 'https://api.aisa.one'}], 'paths': paths}


def upstream(paths):
    return {'openapi': '3.1.0', 'info': {'title': 'source', 'x-aisa-source': dict(SOURCE)}, 'paths': paths}


def ops(document):
    return {(path, method): value for path, item in document['paths'].items()
            for method, value in item.items() if isinstance(value, dict) and 'operationId' in value}


class UnreviewedRuntimePublicationTests(unittest.TestCase):
    def test_default_composition_still_leaves_missing_source_pending(self):
        runtime = facts({'/apis/v1/x/search': {'post': operation('x.search', requestBody=copy.deepcopy(BODY))}})
        document, pending = compose(runtime, upstream({}))
        self.assertEqual(ops(document), {})
        self.assertEqual([row['reason'] for row in pending], ['upstream operation missing'])

    def test_enabled_operation_is_published_from_runtime_binding(self):
        runtime = facts({'/apis/v1/x/search': {'post': operation('x.search', requestBody=copy.deepcopy(BODY))}})
        document, pending = compose(runtime, upstream({}), unreviewed_runtime=True)
        self.assertEqual(pending, [])
        published = ops(document)[('/apis/v1/x/search', 'post')]
        self.assertEqual(published['operationId'], 'x.search')
        self.assertEqual(published['x-aisa-status'], 'enabled')
        self.assertEqual(published['x-aisa-pricing'], {'unit': 'request', 'unit_rate_usd': 0.01})
        self.assertEqual(published['requestBody'], BODY)
        self.assertNotIn('x-aisa-source', published)
        self.assertEqual(published['x-aisa-review'],
                         {'status': 'unreviewed', 'request': 'runtime_binding', 'response': 'generic'})
        self.assertTrue(is_unreviewed_request(published))
        self.assertEqual(published['responses']['200'], {
            'description': UNREVIEWED_SUCCESS_DESCRIPTION,
            'content': {'application/json': {'schema': UNREVIEWED_SUCCESS_SCHEMA}}})
        self.assertNotIn('x-aisa-response-pending', published)
        self.assertEqual(document['info']['x-aisa-document']['response_pending'], [])
        # Generated public text names no supplier or upstream location.
        self.assertNotIn('example.invalid', json.dumps(published))
        self.assertNotIn('/v1/search', json.dumps({k: v for k, v in published.items() if k != 'x-aisa-upstream-path'}))

    def test_runtime_declared_query_parameters_are_retained(self):
        parameters = [{'in': 'query', 'name': 'q', 'required': True, 'schema': {'type': 'string'}}]
        runtime = facts({'/apis/v1/x/items': {'get': operation('x.items', parameters=copy.deepcopy(parameters))}})
        document, pending = compose(runtime, upstream({}), unreviewed_runtime=True)
        self.assertEqual(pending, [])
        self.assertEqual(ops(document)[('/apis/v1/x/items', 'get')]['parameters'][0]['name'], 'q')

    def test_disabled_operation_keeps_status_and_visible_response_debt(self):
        runtime = facts({'/apis/v1/x/search': {'post': operation('x.search', status='disabled')}})
        document, pending = compose(runtime, upstream({}), unreviewed_runtime=True)
        self.assertEqual(pending, [])
        published = ops(document)[('/apis/v1/x/search', 'post')]
        self.assertEqual(published['x-aisa-status'], 'disabled')
        self.assertEqual(published['x-aisa-review']['response'], 'pending')
        self.assertIn('x-aisa-response-pending', published)
        self.assertNotIn('content', published['responses']['200'])

    def test_reviewed_request_without_success_payload_gets_generic_response_only(self):
        source = upstream({'/v1/search': {'get': {'operationId': 'search', 'parameters': [
            {'in': 'query', 'name': 'q', 'schema': {'type': 'string'}}], 'responses': {'200': {'description': 'OK'}}}}})
        runtime = facts({'/apis/v1/x/search': {'get': operation(
            'x.search', parameters=[{'in': 'query', 'name': 'q', 'schema': {'type': 'string'}}])}})
        plain, _ = compose(runtime, source)
        document, pending = compose(runtime, source, unreviewed_runtime=True)
        self.assertEqual(pending, [])
        before, after = ops(plain)[('/apis/v1/x/search', 'get')], ops(document)[('/apis/v1/x/search', 'get')]
        self.assertIn('x-aisa-response-pending', before)
        self.assertEqual(after['x-aisa-review'],
                         {'status': 'unreviewed', 'request': 'reviewed_source', 'response': 'generic'})
        self.assertEqual(after['x-aisa-source'], before['x-aisa-source'])
        self.assertEqual(after['parameters'], before['parameters'])
        self.assertFalse(is_unreviewed_request(after))

    def test_official_examples_are_kept_when_the_payload_schema_is_generic(self):
        example = {'official_1': {'description': 'Official response example only.', 'value': {'id': 1}}}
        source = upstream({'/v1/search': {'get': {'operationId': 'search', 'responses': {'200': {
            'description': 'OK', 'content': {'application/json': {'examples': example},
                                             'text/xml': {'examples': example}}}}}}})
        runtime = facts({'/apis/v1/x/search': {'get': operation('x.search')}})
        plain, _ = compose(runtime, source)
        document, pending = compose(runtime, source, unreviewed_runtime=True)
        self.assertEqual(pending, [])
        before = ops(plain)[('/apis/v1/x/search', 'get')]['responses']['200']['content']
        after = ops(document)[('/apis/v1/x/search', 'get')]
        self.assertEqual(after['x-aisa-review']['response'], 'generic')
        self.assertEqual(after['responses']['200']['description'], UNREVIEWED_SUCCESS_DESCRIPTION)
        self.assertEqual(set(after['responses']['200']['content']), set(before))
        for media, item in after['responses']['200']['content'].items():
            self.assertEqual(item['examples'], before[media]['examples'])
            self.assertEqual(item['schema'], UNREVIEWED_SUCCESS_SCHEMA)

    def test_reviewed_operations_are_unchanged_except_document_identity(self):
        response = {'200': {'description': 'OK', 'content': {'application/json': {'schema': {'type': 'object'}}}}}
        source = upstream({'/v1/search': {'get': {'operationId': 'search', 'responses': response}}})
        runtime = facts({'/apis/v1/x/search': {'get': operation('x.search')}})
        plain, _ = compose(runtime, source)
        flagged, _ = compose(runtime, source, unreviewed_runtime=True)
        self.assertEqual(ops(plain), ops(flagged))
        self.assertNotEqual(plain['info']['x-aisa-document']['document_hash'],
                            flagged['info']['x-aisa-document']['document_hash'])

    def test_public_any_and_source_credentials_remain_pending(self):
        runtime = facts({'/apis/v1/x/any': {'x-aisa-any': operation('x.any')},
                         '/apis/v1/x/auth': {'post': operation('x.auth', **{'x-aisa-request-auth': {'kind': 'synthetic'}})}})
        try:
            document, pending = compose(runtime, upstream({}), unreviewed_runtime=True)
        except ValueError:
            return  # An invalid synthetic credential descriptor also fails closed.
        self.assertEqual(ops(document), {})
        self.assertEqual({row['path'] for row in pending}, {'/apis/v1/x/any', '/apis/v1/x/auth'})

    def test_readiness_compares_unreviewed_body_with_runtime_declaration(self):
        fact = operation('x.search', validation='mixed', requestBody=copy.deepcopy(BODY))
        runtime = facts({'/apis/v1/x/search': {'post': fact}})
        document, _ = compose(runtime, upstream({}), unreviewed_runtime=True)
        published = ops(document)[('/apis/v1/x/search', 'post')]
        self.assertEqual(_runtime_body_errors(fact, runtime, published, document), [])
        changed = copy.deepcopy(published)
        changed['requestBody']['content']['application/json']['schema']['required'] = []
        self.assertEqual([code for code, _ in _runtime_body_errors(fact, runtime, changed, document)],
                         ['runtime_body_contract_mismatch'])


class PreviousForFactsTests(unittest.TestCase):
    def test_selects_before_copy_without_mutating_history(self):
        runtime = facts({'/apis/v1/x/search': {'get': operation('x.search')},
                         '/apis/v1/x/moved': {'get': operation('x.moved')}})
        own = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}], 'components': {'schemas': {'A': {'type': 'object'}}},
               'paths': {'/apis/v1/x/search': {'get': {'operationId': 'x.search', 'responses': {}}},
                         '/apis/v1/x/legacy': {'get': {'operationId': 'x.legacy', 'responses': {}}}}}
        other = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one/apis/v1'}],
                 'paths': {'/x/moved': {'get': {'operationId': 'x.moved', 'responses': {}}},
                           '/y/other': {'get': {'operationId': 'y.other', 'responses': {}}}}}
        unrelated = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
                     'paths': {'/apis/v1/z/other': {'get': {'operationId': 'z.other', 'responses': {}}}}}
        documents = {'x': own, 'moved': other, 'z': unrelated}
        snapshot = copy.deepcopy(documents)
        result = previous_for_facts(runtime, documents, 'x')
        self.assertEqual(documents, snapshot)
        self.assertEqual(set(result['paths']), {'/apis/v1/x/search', '/apis/v1/x/legacy', '/apis/v1/x/moved'})
        self.assertEqual(result['paths']['/apis/v1/x/legacy']['get']['operationId'], 'x.legacy')
        self.assertNotIn('/apis/v1/z/other', result['paths'])
        self.assertNotIn('/apis/v1/y/other', result['paths'])


if __name__ == '__main__':
    unittest.main()
