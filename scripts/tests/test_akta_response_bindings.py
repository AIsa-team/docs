"""Pinned official response source regression; Runtime inputs here are fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from prepare_akta_response_bindings import prepare, SOURCE_FILE, ORIGIN
from runtime_registry import public_mirror_index
from source_governance import policy_errors

ROOT = Path(__file__).resolve().parents[2]


def runtime(document, trailing_slash=False):
    path = next(iter(document['paths']))
    source = document['info']['x-aisa-source']
    path_hash = source['upstream_path_sha256']
    if trailing_slash:
        upstream = '/api/v1/' + path.removeprefix('/apis/v1/akta/') + '/'
        path_hash = hashlib.sha256(upstream.encode()).hexdigest()
    operation = {'operationId': 'fixed_akta_identity', 'x-aisa-status': 'enabled',
                 'x-aisa-validation': 'runtime', 'x-aisa-response-passthrough': True,
                 'x-aisa-response-upstream-path-sha256': path_hash,
                 'x-aisa-response-upstream-origin-sha256': source['upstream_origin_sha256'],
                 'x-aisa-pricing': {'default_request_estimate_usd': 0.001},
                 'parameters': [{'in': 'query', 'name': 'sentinel', 'required': False, 'schema': {'type': 'string'}}],
                 'responses': {'200': {'description': 'Successful response'}}}
    for parameter in document['paths'][path]['get'].get('parameters', []):
        operation['parameters'].append(copy.deepcopy(parameter))
    return {'openapi': '3.1.0', 'info': {'x-aisa-document': {'facts_hash': 'synthetic'}},
            'servers': [{'url': 'https://api.aisa.one'}], 'paths': {path: {'get': operation}}}


class AktaResponseBindingsTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / SOURCE_FILE).read_bytes()
        self.sources = prepare(self.raw)

    def test_frozen_sources_reproduce_and_preserve_official_responses(self):
        official = json.loads(self.raw)
        self.assertEqual(len(self.sources), 4)
        for filename, document in self.sources.items():
            self.assertEqual(json.loads((ROOT / 'openapi/upstream' / filename).read_text()), document)
            path = next(iter(document['paths']))
            upstream = '/v1/' + path.removeprefix('/apis/v1/akta/')
            operation = document['paths'][path]['get']
            self.assertEqual(operation['responses'], official['paths'][upstream]['get']['responses'])
            self.assertNotIn('requestBody', operation)
            self.assertTrue(all(p['in'] == 'path' for p in operation.get('parameters', [])))
            source = document['info']['x-aisa-source']
            self.assertTrue(source['response_only'])
            self.assertEqual(source['upstream_origin_sha256'], hashlib.sha256(ORIGIN.encode()).hexdigest())
            self.assertEqual(policy_errors(source), [])
            self.assertNotIn('reviewer', source)

    def test_changed_source_cannot_silently_rebind(self):
        with self.assertRaisesRegex(ValueError, 'source bytes changed'):
            prepare(self.raw + b' ')

    def test_new_canonical_targets_close_responses_without_request_or_price_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            mirrors = public_mirror_index(Path(temp), self.sources)
            for source in self.sources.values():
                facts = runtime(source)
                path = next(iter(facts['paths']))
                before, bp = compose(facts)
                after, ap = compose(facts, public_mirrors=mirrors)
                self.assertEqual(bp, ap)
                self.assertEqual(ap, [])
                self.assertEqual(len(before['info']['x-aisa-document']['response_pending']), 1)
                self.assertEqual(after['info']['x-aisa-document']['response_pending'], [])
                op = after['paths'][path]['get']
                self.assertTrue(op['responses']['200']['content']['application/json']['schema'])
                excluded = {'responses', 'x-aisa-response-pending', 'x-aisa-response-source'}
                self.assertEqual({k:v for k,v in before['paths'][path]['get'].items() if k not in excluded},
                                 {k:v for k,v in op.items() if k not in excluded})

    def test_old_trailing_slash_targets_and_wrong_origin_remain_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            mirrors = public_mirror_index(Path(temp), self.sources)
            for source in self.sources.values():
                for facts in [runtime(source, trailing_slash=True), runtime(source)]:
                    path = next(iter(facts['paths']))
                    if facts['paths'][path]['get']['x-aisa-response-upstream-path-sha256'] == source['info']['x-aisa-source']['upstream_path_sha256']:
                        facts['paths'][path]['get']['x-aisa-response-upstream-origin-sha256'] = '0' * 64
                    output, pending = compose(facts, public_mirrors=mirrors)
                    self.assertEqual(pending, [])
                    self.assertEqual(len(output['info']['x-aisa-document']['response_pending']), 1)
                    self.assertNotIn('content', output['paths'][path]['get']['responses']['200'])

    def test_response_source_cannot_choose_any_method(self):
        with tempfile.TemporaryDirectory() as temp:
            mirrors = public_mirror_index(Path(temp), self.sources)
            for source in self.sources.values():
                facts = runtime(source)
                path = next(iter(facts['paths']))
                facts['paths'][path]['x-aisa-any'] = facts['paths'][path].pop('get')
                output, pending = compose(facts, public_mirrors=mirrors)
                self.assertEqual(output['paths'], {})
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]['method'], 'ANY')
