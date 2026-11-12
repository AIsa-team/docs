"""Observed success data must remain bound, conservative and reproducible."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
from compose_openapi import digest
from observed_response_source import build_source, project_shape, schema_from_shapes
from source_governance import policy_errors

ROOT = Path(__file__).resolve().parents[2]
REPORT = 'docs/current-source-review-20261110/pending-live-probes-20261112.json'


class ObservedResponseSourceTests(unittest.TestCase):
    def test_every_source_replays_from_value_free_attestation(self):
        report = json.loads((ROOT / REPORT).read_text())
        self.assertEqual(len(report['sources']), 11)
        for row in report['sources']:
            with self.subTest(path=row['public_path']):
                source = json.loads((ROOT / row['source_file']).read_text())
                attestation = json.loads((ROOT / row['attestation_file']).read_text())
                self.assertEqual(digest(attestation), row['attestation_hash'])
                offers = None
                if row['provider'] == 'duffel-flights':
                    prior = json.loads((ROOT / 'openapi/upstream/response-duffel-flights-get-offer-request-20261110.json').read_text())
                    offers = prior['paths']['/apis/v1/duffel/flights/offer-requests/{id}']['get']['responses']['2XX']['content']['application/json']['schema']
                self.assertEqual(build_source(attestation, REPORT, offers), source)
                metadata = source['info'].pop('x-aisa-source')
                self.assertEqual(metadata['content_hash'], digest(source))
                self.assertEqual(policy_errors(metadata), [])
                response = source['paths'][row['public_path']][row['method'].lower()]['responses'][str(row['http_status'])]
                media = response['content']['application/json']
                Draft202012Validator.check_schema(media['schema'])
                Draft202012Validator(media['schema']).validate(media['examples']['synthetic_success']['value'])

    def test_null_empty_arrays_and_dynamic_keys_do_not_invent_constraints(self):
        body = {'result': {'private_id_123': {'field': None, 'list': []}}}
        shape = project_shape(body, maps=(('result',),))
        self.assertNotIn('private_id_123', json.dumps(shape))
        schema = schema_from_shapes([shape], root=True)
        entry = schema['properties']['result']['additionalProperties']
        self.assertNotIn('type', entry['properties']['field'])
        self.assertEqual(entry['properties']['list']['items'], {})
        for future in ({'result': {'future': {'field': 123, 'list': ['unknown'], 'extra': True}}},
                       {'result': None}, {}):
            Draft202012Validator(schema).validate(future)
        def check(node):
            if isinstance(node, dict):
                for forbidden in ('required', 'enum', 'const', 'format', 'minItems', 'maxItems'):
                    self.assertNotIn(forbidden, node)
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)
        check(schema)

    def test_errors_and_quotes_cannot_become_success_sources(self):
        row = json.loads((ROOT / REPORT).read_text())['sources'][0]
        attestation = json.loads((ROOT / row['attestation_file']).read_text())
        for key, value in [('http_status', 404), ('mode', 'quote'),
                           ('body_shape', project_shape({'error': {'code': 'not_found'}}))]:
            invalid = copy.deepcopy(attestation)
            invalid[key] = value
            with self.assertRaises(ValueError):
                build_source(invalid, REPORT)


if __name__ == '__main__':
    unittest.main()
