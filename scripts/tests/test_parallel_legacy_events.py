import json
from pathlib import Path
from catalog_fixture import catalog_root
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_parallel_legacy_events import OPERATION_PATH, extract


class ParallelLegacyEventsTests(unittest.TestCase):
    def test_pinned_contract_preserves_beta_route_and_sse(self):
        document = json.loads((catalog_root() / 'openapi/upstream/parallel-legacy-events.json').read_text())
        self.assertEqual(list(document['paths']), [OPERATION_PATH])
        operation = document['paths'][OPERATION_PATH]['get']
        self.assertEqual(operation['parameters'][0]['name'], 'run_id')
        self.assertTrue(operation['parameters'][0]['required'])
        self.assertIn('text/event-stream', operation['responses']['200']['content'])
        self.assertEqual(document['info']['x-aisa-source']['lifecycle'], 'legacy')

    def test_reference_closure_includes_discriminator_mapping(self):
        source = {'openapi': '3.1.0', 'info': {}, 'security': [{'Key': []}], 'paths': {OPERATION_PATH: {'get': {'responses': {'200': {'content': {'text/event-stream': {'schema': {'$ref': '#/components/schemas/A'}}}}}}}}, 'components': {'schemas': {'A': {'discriminator': {'mapping': {'b': '#/components/schemas/B'}}}, 'B': {'type': 'object'}, 'Unused': {}}, 'securitySchemes': {'Key': {'type': 'http', 'scheme': 'bearer'}}}}
        result = extract(json.dumps(source).encode())
        self.assertEqual(set(result['components']['schemas']), {'A', 'B'})
        self.assertEqual(result['paths'], source['paths'])
        self.assertIn('Key', result['components']['securitySchemes'])
        self.assertEqual(extract(json.dumps(source).encode()), result)

    def test_rejects_wrong_media_type(self):
        source = {'paths': {OPERATION_PATH: {'get': {'responses': {'200': {'content': {'application/json': {}}}}}}}}
        with self.assertRaises(ValueError):
            extract(json.dumps(source).encode())
