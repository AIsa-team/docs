"""Replay official declarations without repairing ambiguous provider item types."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from compose_openapi import digest
from import_similarweb_response_reference import convert_reference, convert_response_only_reference


FIXTURES = Path(__file__).parent / 'fixtures/similarweb-response-20261111'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())['fixtures']
CASES = {row['fixture'].removesuffix('.html'): row for row in MANIFEST}
PARTIAL = {
    'keywords': ('data',),
    'conversion-rates-over-time': ('data',),
    'conversion-rates-aggregated': ('data',),
    'demographics': ('data', 'meta.request.age_buckets', 'meta.request.metrics'),
}


def raw(name):
    return (FIXTURES / CASES[name]['fixture']).read_bytes()


def payload(name):
    return json.loads(re.search(rb'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw(name), re.S).group(1))


def encoded(name, data):
    return ('<link rel="canonical" href="' + CASES[name]['official_url'] + '">'
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + '</script>').encode()


def section(data):
    return data['props']['pageProps']['initialSectionData']


def convert(name, data=None, paths=()):
    row = CASES[name]
    return convert_reference(raw(name) if data is None else encoded(name, data),
                             row['path'], row['official_url'], incomplete_array_paths=paths)


def schema(document):
    return next(iter(document['paths'].values()))['get']['responses']['200']['content']['application/json']['schema']


def field(root, path):
    for part in path.split('.'):
        root = root['properties'][part]
    return root


class SimilarwebResponseReferenceTests(unittest.TestCase):
    def test_projection_keeps_exact_response_declarations_and_authority(self):
        for name, row in CASES.items():
            with self.subTest(name=name):
                self.assertEqual('sha256:' + hashlib.sha256(raw(name)).hexdigest(), row['fixture_sha256'])
                source = section(payload(name))
                self.assertEqual(digest(source['responses']), row['response_declarations_sha256'])
                self.assertEqual(source['_id'], row['section_id'])
                self.assertEqual(source['updatedAt'], row['section_updated_at'])

    def test_segments_preserves_full_json_fields_and_records_other_media(self):
        document, metadata = convert('segments')
        validate(document)
        root = schema(document)
        item = field(root, 'data')['items']
        self.assertEqual(field(root, 'data')['type'], ['array', 'null'])
        self.assertEqual(item['type'], ['object', 'null'])
        self.assertNotIn('required', root)
        self.assertNotIn('required', item)
        self.assertEqual(set(item['properties']), {
            'date', 'source_type', 'visits', 'pages_per_visit', 'page_views',
            'bounce_rate', 'average_visit_duration',
        })
        self.assertEqual(item['properties']['visits']['type'], ['number', 'null'])
        self.assertEqual(item['properties']['source_type']['type'], ['string', 'null'])
        self.assertEqual(field(root, 'meta.request')['required'], ['segment'])
        self.assertEqual(metadata['response_selection']['selected']['media_type'], 'application/json')
        self.assertEqual({row['media_type'] for row in metadata['response_selection']['omitted']},
                         {'application/xml', 'text/json', 'text/plain', 'text/xml'})
        self.assertEqual(metadata['partial_response_scope'], [])
        self.assertNotIn('application/xml', next(iter(document['paths'].values()))['get']['responses']['200']['content'])
        Draft202012Validator(root).validate({'data': [None, {'visits': 1.2}, {'visits': None}]})
        self.assertFalse(Draft202012Validator(root).is_valid({'data': [{'visits': 'unknown'}]}))

    def test_ambiguous_pages_still_fail_in_default_strict_mode(self):
        for name in PARTIAL:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'named child|item schema absent'):
                    convert(name)

    def test_reviewed_partial_paths_keep_only_proven_outer_array(self):
        for name, paths in PARTIAL.items():
            with self.subTest(name=name):
                document, metadata = convert(name, paths=paths)
                validate(document)
                root = schema(document)
                self.assertNotIn('required', root)
                self.assertEqual({row['path'] for row in metadata['partial_response_scope']}, set(paths))
                for path in paths:
                    part = field(root, path)
                    self.assertEqual(part['type'], ['array', 'null'])
                    self.assertEqual(part['items'], {})
                    self.assertEqual(part['x-aisa-schema-status'], 'item_definition_unconfirmed')
                    self.assertIn('numeric item prototype as an array', part['description'])
                    self.assertNotIn('properties', part)
                self.assertEqual(field(root, 'meta.status')['enum'], ['success', 'error'])
                self.assertEqual(field(root, 'meta.error_code')['type'], ['integer', 'null'])
                Draft202012Validator(root).validate({'data': [None, {}, [], 1]})
                self.assertFalse(Draft202012Validator(root).is_valid({'data': {}}))
                self.assertFalse(Draft202012Validator(root).is_valid({'meta': {'status': 'invented'}}))

    def test_demographics_enum_is_only_an_unconfirmed_annotation(self):
        document, metadata = convert('demographics', paths=PARTIAL['demographics'])
        metrics = field(schema(document), 'meta.request.metrics')
        self.assertEqual(metrics['x-aisa-unconfirmed-item-enum'],
                         ['share', 'pages_per_visit', 'bounce_rate', 'average_visit_duration'])
        self.assertNotIn('enum', metrics)
        self.assertEqual(metrics['items'], {})
        self.assertEqual(next(row for row in metadata['partial_response_scope']
                              if row['path'] == 'meta.request.metrics')['reason'], 'absent_array_item_schema')
        Draft202012Validator(metrics).validate(['not-an-enforced-enum-value', 1, []])
        for change in ('missing_outer', 'missing_item', 'different_item', 'duplicate', 'invalid_enum_shape', 'empty', 'named_children'):
            with self.subTest(change=change):
                data = payload('demographics')
                meta = next(n for n in section(data)['responses'][0]['body'] if n['name'] == 'meta')
                request = next(n for n in meta['items'] if n['name'] == 'request')
                node = next(n for n in request['items'] if n['name'] == 'metrics')
                outer, item = node['options'], node['items'][0]['options']
                if change == 'missing_outer': outer.pop('enumValue')
                if change == 'missing_item': item.pop('enumValue')
                if change == 'different_item': item['enumValue'] = [{'value': 'different'}]
                if change == 'duplicate': outer['enumValue'] = item['enumValue'] = [{'value': 'same'}, {'value': 'same'}]
                if change == 'invalid_enum_shape': outer['enumValue'] = item['enumValue'] = ['share']
                if change == 'empty': outer['enumValue'] = item['enumValue'] = []
                if change == 'named_children': node['items'][0]['items'] = [{'name': 'metric', 'isRequired': False, 'valueType': 'string'}]
                with self.assertRaises(ValueError):
                    convert('demographics', data, PARTIAL['demographics'])

    def test_partial_mode_requires_exact_used_array_paths(self):
        for paths in (('missing',), ('meta',), ('data', 'missing'), ('data', 'data'),
                      ('response.data',), ('data[]',), 'data'):
            with self.subTest(paths=paths):
                with self.assertRaises(ValueError):
                    convert('keywords', paths=paths)
        with self.assertRaisesRegex(ValueError, 'not an ambiguous array'):
            convert('segments', paths=('data',))
        with self.assertRaisesRegex(ValueError, 'item schema absent'):
            convert('demographics', paths=('data',))
        with self.assertRaisesRegex(ValueError, 'metrics'):
            convert('demographics', paths=('data', 'meta.request.age_buckets'))

    def test_partial_mode_never_masks_other_schema_errors(self):
        data = payload('keywords')
        nodes = section(data)['responses'][0]['body']
        meta = next(n for n in nodes if n['name'] == 'meta')
        meta['options']['additionalProperties'] = False
        with self.assertRaisesRegex(ValueError, 'unrepresented Similarweb option'):
            convert('keywords', data, PARTIAL['keywords'])
        for change in ('unknown_outer_option', 'unknown_item_option', 'numeric_nested_child', 'two_prototypes', 'wrong_item_type', 'outer_enum'):
            with self.subTest(change=change):
                data = payload('keywords')
                node = next(n for n in section(data)['responses'][0]['body'] if n['name'] == 'data')
                if change == 'unknown_outer_option': node['options']['additionalProperties'] = False
                if change == 'unknown_item_option': node['items'][0]['options']['additionalProperties'] = False
                if change == 'numeric_nested_child': node['items'][0]['items'][0]['name'] = '0'
                if change == 'two_prototypes': node['items'].append(copy.deepcopy(node['items'][0]))
                if change == 'wrong_item_type': node['items'][0]['valueType'] = 'object'
                if change == 'outer_enum': node['options']['enumValue'] = [{'value': 'unexpected'}]
                with self.assertRaises(ValueError):
                    convert('keywords', data, PARTIAL['keywords'])

    def test_partial_paths_cannot_match_literal_dotted_field_names(self):
        data = payload('demographics')
        body = section(data)['responses'][0]['body']
        meta = next(node for node in body if node['name'] == 'meta')
        request = next(node for node in meta['items'] if node['name'] == 'request')
        metrics = next(node for node in request['items'] if node['name'] == 'metrics')
        request['items'].remove(metrics)
        metrics['name'] = 'meta.request.metrics'
        body.append(metrics)
        with self.assertRaisesRegex(ValueError, 'literal field name contains a dot'):
            convert('demographics', data, PARTIAL['demographics'])

        strict = payload('segments')
        section(strict)['responses'][0]['body'].append({
            'name': 'literal.field', 'valueType': 'string', 'isRequired': False,
        })
        document, _ = convert('segments', strict)
        self.assertEqual(schema(document)['properties']['literal.field'], {'type': 'string'})

    def test_exact_route_origin_and_canonical_authority_are_required(self):
        for path in (CASES['segments']['path'], CASES['segments']['path'].lstrip('/')):
            data = payload('segments')
            section(data)['endpoints']['path'] = path
            convert('segments', data)
        for path in ('//' + CASES['segments']['path'].lstrip('/'), CASES['segments']['path'] + '/other'):
            data = payload('segments')
            section(data)['endpoints']['path'] = path
            with self.assertRaisesRegex(ValueError, 'endpoint mismatch'):
                convert('segments', data)
        data = payload('segments')
        section(data)['endpoints']['method'] = 'post'
        with self.assertRaisesRegex(ValueError, 'endpoint mismatch'):
            convert('segments', data)
        data = payload('segments')
        data['props']['pageProps']['documents']['data']['transformedSection'][0]['urls']['Production'] = ['https://example.invalid/']
        with self.assertRaisesRegex(ValueError, 'production authority mismatch'):
            convert('segments', data)
        with self.assertRaisesRegex(ValueError, 'canonical source URL mismatch'):
            convert_reference(raw('segments'), CASES['segments']['path'], CASES['segments']['official_url'] + '-other')

    def test_response_selection_does_not_merge_media_or_error_status(self):
        data = payload('segments')
        responses = section(data)['responses']
        responses.append({'statusCode': 400, 'contentType': 'application/json', 'body': []})
        _, metadata = convert('segments', data)
        self.assertIn({'status': 400, 'media_type': 'application/json',
                       'pointer': '/props/pageProps/initialSectionData/responses/5'},
                      metadata['response_selection']['omitted'])
        responses.append(copy.deepcopy(responses[0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            convert('segments', data)
        data = payload('segments')
        section(data)['responses'] = [r for r in section(data)['responses'] if r['contentType'] != 'application/json']
        with self.assertRaisesRegex(ValueError, 'one explicit'):
            convert('segments', data)

    def test_response_only_mapping_retains_partial_scope_and_raw_hash(self):
        row = CASES['keywords']
        public = '/apis/v1/similarweb/' + row['path'].removeprefix('/v5/')
        document, metadata = convert_response_only_reference(raw('keywords'), row['path'], row['official_url'], public,
                                                              incomplete_array_paths=('data',))
        self.assertEqual(set(document['paths']), {public})
        self.assertEqual(metadata['partial_response_scope'], [{'path': 'data', 'reason': 'named_array_children'}])
        self.assertEqual(metadata['source_pages'][0]['raw_content_hash'], row['fixture_sha256'])
        self.assertEqual(metadata['upstream_path_sha256'], hashlib.sha256(row['path'].encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'exact v5 suffix'):
            convert_response_only_reference(raw('keywords'), row['path'], row['official_url'], public + '-other',
                                            incomplete_array_paths=('data',))


if __name__ == '__main__':
    unittest.main()
