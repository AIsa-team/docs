import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import resolve, schema_30_to_31
from import_dataforseo_filters import normalize_response_echo

ROOT = Path(__file__).resolve().parents[2]


class DataforseoResponseEchoTests(unittest.TestCase):
    def test_complete_live_responses_and_result_constraints(self):
        document = json.loads((ROOT / 'openapi/upstream/dataforseo-official.json').read_text())
        fixtures = ROOT / 'scripts/tests/fixtures/dataforseo-live-20261113'
        for name, path in [('anchors', '/v3/backlinks/anchors/live'),
                           ('keyword-overview', '/v3/dataforseo_labs/google/keyword_overview/live')]:
            with self.subTest(endpoint=path):
                response = json.loads((fixtures / (name + '.json')).read_text())
                declaration = document['paths'][path]['post']['responses']['200']['content']['application/json']['schema']
                validator = Draft202012Validator(schema_30_to_31(resolve(declaration, document)))
                validator.validate(response)
                bad = copy.deepcopy(response)
                bad['tasks'][0]['data'] = ['invalid-envelope']
                self.assertFalse(validator.is_valid(bad))
                bad = copy.deepcopy(response)
                bad['tasks'][0]['cost'] = 'invalid-cost-type'
                self.assertFalse(validator.is_valid(bad))
                before = copy.deepcopy(document)
                before['components']['schemas']['BaseResponseTaskInfo']['properties']['data']['additionalProperties'] = {
                    'type': 'object', 'nullable': True}
                self.assertFalse(Draft202012Validator(schema_30_to_31(resolve(declaration, before))).is_valid(response))

    def test_official_example_is_accepted_without_relaxing_the_envelope(self):
        # Public data projection from https://docs.dataforseo.com/v3/backlinks/anchors/live/
        official_echo = {'api': 'backlinks', 'function': 'anchors', 'target': 'forbes.com',
                         'limit': 4, 'order_by': ['backlinks,desc'],
                         'filters': ['anchor', 'like', '%news%']}
        envelope = {'type': 'object', 'required': ['status_code', 'data'], 'properties': {
            'status_code': {'type': 'integer'},
            'data': {'type': 'object', 'nullable': True,
                     'additionalProperties': {'type': 'object', 'nullable': True}},
        }}
        original = {'components': {'schemas': {'BaseResponseTaskInfo': envelope,
            'OtherResponseInfo': copy.deepcopy(envelope)}}}
        document = copy.deepcopy(original)
        payload = {'status_code': 20000, 'data': official_echo}
        self.assertFalse(Draft202012Validator(schema_30_to_31(envelope)).is_valid(payload))
        self.assertEqual(normalize_response_echo(document), [('BaseResponseTaskInfo', 'data')])
        validator = Draft202012Validator(schema_30_to_31(document['components']['schemas']['BaseResponseTaskInfo']))
        validator.validate(payload)
        validator.validate({'status_code': 20000, 'data': {'flag': False, 'nested': {'v': [1, None]}}})
        validator.validate({'status_code': 20000, 'data': None})
        self.assertFalse(validator.is_valid({'status_code': 20000, 'data': ['not-an-object']}))
        self.assertFalse(validator.is_valid({'status_code': 'invalid', 'data': official_echo}))
        self.assertEqual(document['components']['schemas']['OtherResponseInfo'], envelope)
        self.assertEqual(normalize_response_echo(document), [])

    def test_structured_or_future_upstream_constraints_are_not_overwritten(self):
        for additional in [{'type': 'string'}, {'type': 'object', 'properties': {'id': {'type': 'integer'}}},
                           {'$ref': '#/components/schemas/EchoValue'}]:
            document = {'components': {'schemas': {'BaseResponseTaskInfo': {'properties': {
                'data': {'type': 'object', 'additionalProperties': additional}}}}}}
            before = copy.deepcopy(document)
            self.assertEqual(normalize_response_echo(document), [])
            self.assertEqual(document, before)

    def test_reviewed_source_retains_nullable_object_with_arbitrary_json_members(self):
        document = json.loads((ROOT / 'openapi/upstream/dataforseo-official.json').read_text())
        data = document['components']['schemas']['BaseResponseTaskInfo']['properties']['data']
        validator = Draft202012Validator(schema_30_to_31(data))
        validator.validate({'target': 'example.com', 'limit': 1, 'filters': [['rank', '>', 1]],
                            'enabled': True, 'optional': None})
        self.assertFalse(validator.is_valid('invalid-envelope'))
        self.assertEqual(normalize_response_echo(document), [])


if __name__ == '__main__':
    unittest.main()
