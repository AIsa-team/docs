import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_request_input_forwarding import missing_query_inputs
from compose_openapi import compose
from runtime_registry import public_mirror_index

PATH = '/apis/v1/alpha/lookup'
MIRROR = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
          'info': {'title': 'Alpha reference', 'version': '1', 'x-aisa-source': {
              'kind': 'manual', 'path_space': 'public', 'url': 'https://alpha.example/catalog',
              'fetched_at': '2026-11-01T00:00:00Z', 'content_hash': 'sha256:alpha', 'converter': 'fixture'}},
          'paths': {PATH: {'get': {'operationId': 'alpha_lookup', 'parameters': [
              {'name': 'company', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]}}}}


def runtime(policy):
    return {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
            'info': {'title': 'Alpha', 'version': '1', 'x-aisa-document': {'facts_hash': 'sha256:alpha'}},
            'paths': {PATH: {'get': {'operationId': 'alpha_lookup', 'x-aisa-validation': 'provider',
                                     'x-aisa-status': 'enabled', 'x-aisa-upstream-path': '/lookup',
                                     'x-aisa-query-policy': policy, 'x-aisa-pricing': {'default_request_estimate_usd': 0.01},
                                     'responses': {'200': {'description': 'Successful response'}}}}}}


class OpenQueryForwardingTests(unittest.TestCase):
    def compose(self, policy):
        with tempfile.TemporaryDirectory() as root:
            mirrors = public_mirror_index(Path(root), {'alpha-public.json': copy.deepcopy(MIRROR)})
        return compose(runtime(policy), public_mirrors=mirrors)

    def test_closed_query_runtime_keeps_source_query_pending(self):
        document, pending = self.compose({'request_wins': False, 'ignore_undeclared': False})
        self.assertIn('not forwarded by runtime', ' '.join(row['reason'] for row in pending))
        self.assertNotIn(PATH, {path for path, item in document['paths'].items() if not item.get('get', {}).get('x-aisa-contract-pending')})

    def test_open_query_runtime_publishes_source_query(self):
        document, pending = self.compose({'request_wins': False, 'ignore_undeclared': False, 'open_query': True})
        self.assertEqual(pending, [])
        parameters = document['paths'][PATH]['get']['parameters']
        self.assertEqual([(p['name'], p['in'], p['required']) for p in parameters], [('company', 'query', True)])

    def test_audit_treats_open_query_as_forwarded(self):
        source = MIRROR['paths'][PATH]['get']
        self.assertEqual(missing_query_inputs({'x-aisa-query-policy': {'open_query': True}}, source, MIRROR), [])
        self.assertEqual(missing_query_inputs({'x-aisa-query-policy': {}}, source, MIRROR), ['company'])


if __name__ == '__main__':
    unittest.main()
