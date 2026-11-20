import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import resolve, schema_30_to_31
from import_dataforseo_filters import (normalize_nullable_response_refs,
                                       normalize_polymorphic_responses, normalize_response_echo)

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / 'openapi/upstream/dataforseo-official.json'
FIXTURES = ROOT / 'scripts/tests/fixtures/dataforseo-live-20261113'
ORGANIC = '/v3/serp/google/organic/live/advanced'
REF = '#/components/schemas/'


def wrapper(name, **extra):
    """Upstream's nullable single-reference wrapper."""
    return {'type': 'object', 'oneOf': [{'$ref': REF + name}], 'nullable': True, **extra}


def upstream_shape():
    """Minimal copy of the official SERP declarations (pinned upstream 702356d7)."""
    schemas = {
        'Rectangle': {'type': 'object', 'properties': {'x': {'type': 'number', 'nullable': True}}},
        'Untyped': {'properties': {'v': {'type': 'string', 'nullable': True}}},
        'BaseItem': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'type': {'type': 'string', 'nullable': True},
                           'rank': {'type': 'integer', 'nullable': True},
                           'rectangle': wrapper('Rectangle')},
            'discriminator': {'propertyName': 'type', 'mapping': {
                'organic': REF + 'OrganicItem', 'video': REF + 'VideoItem'}},
        },
        'OrganicItem': {'type': 'object', 'allOf': [wrapper('BaseItem'), {'type': 'object', 'properties': {
            'domain': {'type': 'string', 'nullable': True}, 'about': wrapper('Rectangle')}}]},
        'VideoItem': {'type': 'object', 'allOf': [wrapper('BaseItem'), {'type': 'object', 'properties': {
            'source': {'type': 'string', 'nullable': True}}}]},
        'Result': {'type': 'object', 'properties': {
            'chips': wrapper('Rectangle'), 'spell': wrapper('Untyped'),
            'items': {'type': 'array', 'nullable': True, 'items': wrapper('BaseItem')}}},
        'Request': {'type': 'object', 'properties': {'mode': wrapper('Rectangle')}},
    }
    return {'openapi': '3.0.1', 'components': {'schemas': schemas}, 'paths': {'/v3/x': {'post': {
        'requestBody': {'content': {'application/json': {'schema': {'$ref': REF + 'Request'}}}},
        'responses': {'200': {'content': {'application/json': {'schema': wrapper('Result')}}}},
    }}}}


def normalize(document):
    return normalize_polymorphic_responses(document) + [('null', n) for n in normalize_nullable_response_refs(document)]


def validator(document, schema):
    return Draft202012Validator(schema_30_to_31(resolve(schema, document)))


def response_schema(document, path):
    return document['paths'][path]['post']['responses']['200']['content']['application/json']['schema']


class PolymorphicResponseShapeTests(unittest.TestCase):
    valid = {'chips': None, 'spell': None, 'items': [
        {'type': 'organic', 'rank': 1, 'rectangle': None, 'domain': 'example.com', 'about': None},
        {'type': 'video', 'rank': 2, 'rectangle': {'x': 1.5}, 'source': 'YouTube'}, None]}

    def test_upstream_shape_rejects_documented_response_and_fix_accepts_it(self):
        document = upstream_shape()
        schema = response_schema(document, '/v3/x')
        self.assertFalse(validator(document, schema).is_valid(self.valid))
        changes = normalize(document)
        self.assertEqual(sorted(kind for kind, _ in changes),
                         # null: response root, chips, base rectangle, organic about
                         ['null', 'null', 'null', 'null', 'open_base', 'tag_subtype', 'tag_subtype', 'union_site'])
        validator(document, response_schema(document, '/v3/x')).validate(self.valid)

    def test_subtype_fields_types_and_tags_remain_enforced(self):
        document = upstream_shape()
        normalize(document)
        check = validator(document, response_schema(document, '/v3/x'))
        for label, mutate in [
            ('subtype field type', lambda r: r['items'][0].__setitem__('domain', 5)),
            ('base field type', lambda r: r['items'][0].__setitem__('rank', '1')),
            ('unknown discriminator', lambda r: r['items'][0].__setitem__('type', 'unknown')),
            ('missing discriminator', lambda r: r['items'][0].pop('type')),
            ('nullable ref non-object', lambda r: r.__setitem__('chips', 'x')),
            ('nested nullable ref non-object', lambda r: r['items'][1].__setitem__('rectangle', [])),
            ('scalar item', lambda r: r['items'].append('x')),
        ]:
            with self.subTest(label):
                instance = copy.deepcopy(self.valid)
                mutate(instance)
                self.assertFalse(check.is_valid(instance))
        instance = copy.deepcopy(self.valid)
        instance['items'][0]['future_field'] = {'open': True}
        check.validate(instance)  # subtypes stay as open as the rest of the source

    def test_requests_and_untyped_targets_are_unchanged_and_rules_are_idempotent(self):
        document = upstream_shape()
        before = copy.deepcopy(document['components']['schemas'])
        normalize(document)
        after = document['components']['schemas']
        self.assertEqual(after['Request'], before['Request'])
        self.assertEqual(after['Result']['properties']['spell'], before['Result']['properties']['spell'])
        self.assertEqual(after['OrganicItem']['allOf'][0], before['OrganicItem']['allOf'][0])
        snapshot = copy.deepcopy(document)
        self.assertEqual(normalize(document), [])
        self.assertEqual(document, snapshot)

    def test_base_with_a_subtype_outside_its_allof_contract_is_not_rewritten(self):
        document = upstream_shape()
        document['components']['schemas']['VideoItem'] = {'type': 'object', 'properties': {'source': {'type': 'string'}}}
        before = copy.deepcopy(document['components']['schemas']['BaseItem'])
        self.assertEqual([c for c in normalize_polymorphic_responses(document)], [])
        self.assertEqual(document['components']['schemas']['BaseItem'], before)


class ReviewedSourceTests(unittest.TestCase):
    """The reviewed mirror as the importer emits it (a no-op once the mirror carries it)."""

    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(MIRROR.read_text())
        normalize_response_echo(cls.document)
        normalize(cls.document)

    def test_live_google_organic_response_passes_with_constraints(self):
        response = json.loads((FIXTURES / 'organic-advanced.json').read_text())
        check = validator(self.document, response_schema(self.document, ORGANIC))
        check.validate(response)
        result = response['tasks'][0]['result'][0]
        self.assertIsNone(result['refinement_chips'])
        self.assertEqual({i['type'] for i in result['items']},
                         {'organic', 'video', 'knowledge_graph', 'people_also_ask', 'related_searches'})
        organic = next(i for i, item in enumerate(result['items']) if item['type'] == 'organic')
        graph = next(i for i, item in enumerate(result['items']) if item['type'] == 'knowledge_graph')
        def item(r, index):
            return r['tasks'][0]['result'][0]['items'][index]

        for label, mutate in [
            ('organic rank_group type', lambda r: item(r, organic).__setitem__('rank_group', '1')),
            ('organic domain type', lambda r: item(r, organic).__setitem__('domain', 5)),
            ('unknown item type', lambda r: item(r, organic).__setitem__('type', 'not_a_serp_item')),
            ('refinement_chips type', lambda r: r['tasks'][0]['result'][0].__setitem__('refinement_chips', 'x')),
            ('rectangle type', lambda r: item(r, organic).__setitem__('rectangle', 5)),
            ('nested knowledge graph item tag', lambda r: item(r, graph)['items'][0].__setitem__('type', 'organic')),
            ('task cost type', lambda r: r['tasks'][0].__setitem__('cost', 'invalid')),
        ]:
            with self.subTest(label):
                instance = copy.deepcopy(response)
                mutate(instance)
                self.assertFalse(check.is_valid(instance))

    def test_previous_successful_replays_still_pass(self):
        for name, path in [('anchors', '/v3/backlinks/anchors/live'),
                           ('keyword-overview', '/v3/dataforseo_labs/google/keyword_overview/live')]:
            with self.subTest(path):
                response = json.loads((FIXTURES / (name + '.json')).read_text())
                validator(self.document, response_schema(self.document, path)).validate(response)

    def test_importer_reaches_every_published_base_and_is_idempotent(self):
        document = copy.deepcopy(self.document)
        self.assertEqual(normalize(document), [])
        schemas = document['components']['schemas']
        # The only remaining closed base is not reachable from any operation.
        self.assertEqual([n for n, s in schemas.items() if s.get('additionalProperties') is False],
                         ['BaseSerpApiBingPeopleAlsoAskExpandedElementItem'])
        organic = schemas['SerpGoogleOrganicLiveAdvancedResultInfo']['properties']['items']['items']
        self.assertEqual(len(organic['oneOf']), len(organic['discriminator']['mapping']) + 1)

if __name__ == '__main__':
    unittest.main()
