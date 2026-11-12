"""Independent live evidence must survive a fresh legacy Runtime projection."""
import copy
import json
import unittest

from compose_openapi import compose
from runtime_registry import runtime_metadata_mirrors
from test_independent_response_sources import index, response_source
from test_runtime_contracts import facts, mirror, operation


PATH = '/apis/v1/similarweb/test'


def provider_inputs():
    runtime, official = facts('provider'), mirror()
    operation(runtime)['x-aisa-passthrough'] = True
    official['servers'] = [{'url': 'https://provider.example'}]
    operation(official)['servers'] = [{'url': 'https://provider.example'}]
    return runtime, official


def managed_inputs():
    runtime = facts('provider', 'x-aisa-any')
    operation(runtime)['x-aisa-passthrough'] = True
    operation(runtime)['x-aisa-query-policy'] = {'request_wins': True}
    operation(runtime)['description'] = json.dumps({'methods': [{
        'methodType': 'GET', 'requestParams': [{'name': 'q', 'type': 'string', 'required': True}]}]})
    fragment = {'path': '/provider/test', 'method': 'GET',
                'parameters': [{'name': 'q', 'in': 'query', 'schema': {'enum': ['first', 'second']}}],
                'missing_fields': {'q': ['required', 'type']},
                'official_reference_url': 'https://provider.example/reference',
                'official_reference_sha256': 'a' * 64}
    official = {'openapi': '3.1.0', 'paths': {}, 'servers': [{'url': 'https://provider.example'}],
                'info': {'x-aisa-source': {'kind': 'provider_openapi',
                    'url': 'https://provider.example/', 'fetched_at': '2026-11-12',
                    'content_hash': 'sha256:fragment', 'converter': 'fixture',
                    'operation_identity_evidence': [{'path': fragment['path'], 'method': 'GET',
                        'url': fragment['official_reference_url'], 'sha256': fragment['official_reference_sha256'],
                        'request_status': 'pending'}]}},
                'x-aisa-incomplete-request-definitions': {'/provider/test': fragment}}
    return runtime, official


class LegacyPassthroughResponseTests(unittest.TestCase):
    def test_fresh_provider_facts_bind_response_without_fabricating_runtime_descriptor(self):
        runtime, official = provider_inputs()
        baseline, pending = compose(runtime, official)
        self.assertEqual(pending, [])
        source = response_source()
        source['paths'][PATH]['post']['responses']['201'] = source['paths'][PATH]['post']['responses'].pop('200')
        result, pending = compose(runtime, official, public_mirrors=index(source))
        self.assertEqual(pending, [])
        actual = operation(result)
        self.assertEqual(set(actual['responses']), {'201'})
        self.assertNotIn('x-aisa-response-pending', actual)
        self.assertEqual(actual['x-aisa-response-source']['source']['content_hash'], 'sha256:response-fixture')
        for key, value in operation(baseline).items():
            if key not in {'responses', 'x-aisa-response-pending', 'x-aisa-response-source'}:
                self.assertEqual(actual[key], value, key)
        self.assertNotIn('x-aisa-response-passthrough', actual)
        self.assertNotIn('x-aisa-response-upstream-origin-sha256', actual)
        self.assertEqual(compose(runtime, official, public_mirrors=index(source), previous=result), (result, []))

    def test_origin_path_and_source_ambiguity_fail_closed_without_previous_response_fallback(self):
        runtime, official = provider_inputs()
        published, _ = compose(runtime, official, public_mirrors=index(response_source()))
        for change in ('origin', 'path', 'multiple_sources', 'multiple_servers', 'missing_server',
                       'server_origin', 'variable_server', 'relative_server', 'credential_server'):
            with self.subTest(change=change):
                source, request_source = response_source(), copy.deepcopy(official)
                if change == 'origin': source['info']['x-aisa-source']['upstream_origin_sha256'] = '0' * 64
                elif change == 'path': source['info']['x-aisa-source']['upstream_path_sha256'] = '0' * 64
                elif change == 'multiple_servers': operation(request_source)['servers'].append({'url': 'https://other.example'})
                elif change == 'missing_server': operation(request_source)['servers'] = []
                elif change == 'server_origin': operation(request_source)['servers'][0]['url'] = 'https://other.example'
                elif change == 'variable_server': operation(request_source)['servers'][0]['url'] = 'https://{tenant}.example'
                elif change == 'relative_server': operation(request_source)['servers'][0]['url'] = '/'
                elif change == 'credential_server': operation(request_source)['servers'][0]['url'] = 'https://user:pass@provider.example'
                sources = [source, copy.deepcopy(source)] if change == 'multiple_sources' else [source]
                result, pending = compose(runtime, request_source, public_mirrors=index(*sources), previous=published)
                self.assertEqual(pending, [])
                actual = operation(result)
                self.assertIn('ambiguous or changed', actual['x-aisa-response-pending']['reason'])
                self.assertNotIn('content', actual['responses']['200'])
                self.assertNotIn('x-aisa-response-source', actual)

    def test_path_item_server_overrides_document_server(self):
        runtime, official = provider_inputs()
        official['servers'][0]['url'] = 'https://wrong.example'
        operation(official).pop('servers')
        official['paths']['/provider/test']['servers'] = [{'url': 'https://provider.example'}]
        result, pending = compose(runtime, official, public_mirrors=index(response_source()))
        self.assertEqual(pending, [])
        self.assertNotIn('x-aisa-response-pending', operation(result))

    def test_explicit_response_descriptor_does_not_fall_back_to_legacy_binding(self):
        for descriptor in ({'x-aisa-response-passthrough': False},
                           {'x-aisa-response-passthrough': True},
                           {'x-aisa-response-upstream-path-sha256': '0' * 64}):
            with self.subTest(descriptor=descriptor):
                runtime, official = provider_inputs()
                operation(runtime).update(descriptor)
                result, pending = compose(runtime, official, public_mirrors=index(response_source()))
                self.assertEqual(pending, [])
                self.assertIn('x-aisa-response-pending', operation(result))
                self.assertNotIn('x-aisa-response-source', operation(result))

    def test_legacy_response_binding_requires_runtime_passthrough(self):
        for value in (None, False, 1):
            with self.subTest(value=value):
                runtime, official = provider_inputs()
                if value is None:
                    operation(runtime).pop('x-aisa-passthrough')
                else:
                    operation(runtime)['x-aisa-passthrough'] = value
                result, pending = compose(runtime, official, public_mirrors=index(response_source()))
                self.assertEqual(pending, [])
                self.assertIn('x-aisa-response-pending', operation(result))
                self.assertNotIn('x-aisa-response-source', operation(result))

    def test_managed_request_keeps_response_candidates_and_rebuilds_current_request(self):
        runtime, official = managed_inputs()
        mirrors = index(response_source('get'))
        first = runtime_metadata_mirrors(runtime, official, mirrors)
        result, pending = compose(runtime, official, public_mirrors=first)
        self.assertEqual(pending, [])
        actual = operation(result)
        self.assertEqual(actual['x-aisa-source']['kind'], 'runtime_metadata')
        self.assertNotIn('x-aisa-response-pending', actual)
        self.assertEqual(actual['x-aisa-response-source']['source']['content_hash'], 'sha256:response-fixture')
        self.assertEqual([p['name'] for p in actual['parameters']], ['q', 'switch'])
        self.assertTrue(actual['parameters'][0]['required'])
        operation(runtime)['description'] = operation(runtime)['description'].replace('true', 'false')
        changed, pending = compose(runtime, official, public_mirrors=first)
        self.assertEqual(pending, [])
        self.assertFalse(operation(changed)['parameters'][0]['required'])
        self.assertNotIn('x-aisa-response-pending', operation(changed))

    def test_response_only_never_establishes_missing_managed_request(self):
        for change in ('missing_metadata', 'missing_parent', 'ambiguous_parent', 'wrong_identity'):
            with self.subTest(change=change):
                runtime, official = managed_inputs()
                if change == 'missing_metadata': operation(runtime)['description'] = 'Request fields unknown'
                elif change == 'missing_parent': official = None
                elif change == 'ambiguous_parent': official = [official, copy.deepcopy(official)]
                else: official['info']['x-aisa-source']['operation_identity_evidence'] = []
                result, pending = compose(runtime, official, public_mirrors=index(response_source('get')))
                self.assertEqual(result['paths'], {})
                self.assertEqual(len(pending), 1)

    def test_managed_origin_mismatch_keeps_request_but_not_response(self):
        runtime, official = managed_inputs()
        official['servers'] = [{'url': 'https://other.example'}]
        result, pending = compose(runtime, official, public_mirrors=index(response_source('get')))
        self.assertEqual(pending, [])
        actual = operation(result)
        self.assertEqual(actual['x-aisa-source']['kind'], 'runtime_metadata')
        self.assertIn('ambiguous or changed', actual['x-aisa-response-pending']['reason'])
        self.assertNotIn('x-aisa-response-source', actual)


if __name__ == '__main__':
    unittest.main()
