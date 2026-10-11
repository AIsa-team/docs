import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_provenance import (KEY, compact_document, expand_document, merge_provenance,
                               validate_document)
from runtime_registry import previous_for_facts
from pull_openapi import retain_unregistered_history
from runtime_localize_openapi_zh import iter_spec_strings


def fixture():
    source = {'kind': 'manual', 'url': 'https://official.example/reference',
              'content_hash': 'sha256:locked-input', 'operation_identity_evidence':
              [{'path': '/upstream', 'description': 'Evidence must not be translated',
                'evidence': 'x' * 17000}]}
    operation = {'operationId': 'get_test', 'x-aisa-source': source,
                 'x-aisa-response-source': {'kind': 'upstream_success_contract',
                                           'content_hash': 'sha256:payload', 'source': copy.deepcopy(source)},
                 'parameters': [{'name': 'q', 'in': 'query', 'required': True,
                                 'schema': {'type': 'string'}}],
                 'responses': {'200': {'description': 'Success', 'content': {'application/json': {
                     'schema': {'type': 'object'}, 'example': {'x-aisa-source': source}}}}}}
    return {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
            'info': {'title': 'Test', 'version': '1', 'x-aisa-document': {'document_hash': 'old'}},
            'paths': {'/test': {'get': operation}}}


class ProvenanceTests(unittest.TestCase):
    def test_lossless_idempotent_and_preserves_instance_data(self):
        original = fixture()
        actual = compact_document(copy.deepcopy(original))
        self.assertEqual(len(actual['info'][KEY]), 1)
        self.assertEqual(expand_document(actual), original)
        self.assertEqual(compact_document(copy.deepcopy(actual)), actual)
        op = actual['paths']['/test']['get']
        self.assertEqual(op['x-aisa-source']['kind'], 'manual')
        self.assertEqual(op['x-aisa-response-source']['source']['content_hash'], 'sha256:locked-input')
        self.assertEqual(op['responses'], original['paths']['/test']['get']['responses'])

    def test_tampering_and_missing_references_fail(self):
        document = compact_document(fixture())
        for mutate in [lambda d: d['info'].pop(KEY),
                       lambda d: next(iter(d['info'][KEY].values())).update(url='https://wrong.example'),
                       lambda d: d['paths']['/test']['get']['x-aisa-source'].update(kind='provider_openapi'),
                       lambda d: d['paths']['/test']['get']['x-aisa-source'].update(provenance_ref='#/wrong')]:
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(document)
                mutate(bad)
                with self.assertRaises(ValueError):
                    validate_document(bad)

    def test_combination_retains_shared_evidence_and_rejects_collision(self):
        original = compact_document(fixture())
        target = {'info': {}}
        merge_provenance(target, original)
        merge_provenance(target, original)
        self.assertEqual(target['info'][KEY], original['info'][KEY])
        key = next(iter(target['info'][KEY]))
        target['info'][KEY][key]['kind'] = 'tampered'
        with self.assertRaises(ValueError):
            merge_provenance(target, original)

    def test_previous_document_and_retained_alias_keep_evidence(self):
        original = compact_document(fixture())
        facts = {'paths': {}, 'servers': [{'url': 'https://api.aisa.one'}]}
        previous = previous_for_facts(facts, {'example': original}, 'example')
        validate_document(previous)
        self.assertIn(KEY, previous['info'])
        candidate = {'paths': {}, 'info': {'x-aisa-document': {'document_hash': 'new'}}}
        retained = retain_unregistered_history(candidate, facts, previous)
        self.assertEqual(len(retained), 1)
        validate_document(candidate)
        self.assertIn(KEY, candidate['info'])

    def test_localization_does_not_translate_shared_provenance(self):
        document = compact_document(fixture())
        self.assertFalse(any(KEY in path for path, _ in iter_spec_strings(document)))

    def test_committed_fred_evidence_rehydrates_and_stays_small(self):
        path = Path(__file__).resolve().parents[2] / 'openapi/fred.json'
        original = json.loads(path.read_text())
        result = compact_document(copy.deepcopy(original))
        self.assertEqual(expand_document(result), expand_document(original))
        self.assertLess(len(json.dumps(result, indent=2).encode()), 2_000_000)
        self.assertEqual(len(result['info'][KEY]), 1)
        self.assertEqual(len(result['paths']), 32)


if __name__ == '__main__':
    unittest.main()
