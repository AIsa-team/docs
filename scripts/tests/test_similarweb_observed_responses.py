"""Replay pinned shape proofs without committing private production payloads."""
import copy
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from amend_similarweb_observed_responses import CASES, amend_observed_response, shape_attestation
from compose_openapi import digest
from import_similarweb_response_reference import convert_reference, convert_response_only_reference
from source_governance import policy_revision

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'scripts/tests/fixtures'
FILES = {'keywords': 'response-similarweb-keyword-overview.json',
         'demographics': 'response-similarweb-traffic-demographics-aggregated.json'}
PAGES = {'keywords': 'get_similarweb_apis_v1_similarweb_keyword_analysi_490801.mdx',
         'demographics': 'get_similarweb_apis_v1_similarweb_website_analysi_aa2e1f.mdx'}
EVIDENCE = 'docs/current-source-review-20261110/similarweb-observed-keywords-demographics-20261111.json'


def inputs(name):
    source = json.loads((ROOT / 'openapi/upstream' / FILES[name]).read_text())
    metadata = source['info']['x-aisa-source']
    path = next(iter(source['paths']))
    upstream = '/v5/' + path.removeprefix('/apis/v1/similarweb/')
    raw = (FIXTURES / 'similarweb-response-20261111' / (name + '.html')).read_bytes()
    prior, _ = convert_response_only_reference(raw, upstream, metadata['url'], path,
                                               incomplete_array_paths=CASES[path]['partial'])
    prior['info']['x-aisa-source'] = copy.deepcopy(metadata['prior_source'])
    observation = json.loads((FIXTURES / 'similarweb-observed-20261111' / (name + '.json')).read_text())
    example = json.loads((FIXTURES / 'similarweb-observed-20261111' / (name + '-example.json')).read_text())
    return source, prior, raw, observation, example


def schema(source):
    return next(iter(source['paths'].values()))['get']['responses']['200']['content']['application/json']['schema']


class SimilarwebObservedResponseTests(unittest.TestCase):
    def test_each_amendment_replays_exactly_and_preserves_source_clocks_policy(self):
        evidence = json.loads((ROOT / EVIDENCE).read_text())['observations']
        for name in FILES:
            with self.subTest(name=name):
                source, prior, raw, observation, example = inputs(name)
                replay, receipt = amend_observed_response(prior, raw, observation, EVIDENCE, example)
                self.assertEqual(replay, source)
                self.assertEqual(receipt, {k: v for k, v in next(row for row in evidence
                    if row['source_file'].endswith(FILES[name])).items()
                    if k not in ('source_file', 'observation_fixture', 'synthetic_example_fixture')})
                metadata = source['info']['x-aisa-source']
                for key in ('fetched_at', 'acquisition', 'url', 'refresh_policy', 'owner', 'review_period_days', 'policy_revision'):
                    self.assertEqual(metadata[key], prior['info']['x-aisa-source'][key])
                self.assertEqual(metadata['policy_revision'], policy_revision(metadata))
                self.assertEqual(metadata['observed_at'], observation['observed_at'])
                self.assertNotEqual(metadata['observed_at'], metadata['fetched_at'])
                without_metadata = copy.deepcopy(source)
                without_metadata['info'].pop('x-aisa-source')
                self.assertEqual(metadata['content_hash'], digest(without_metadata))

    def test_synthetic_examples_pass_format_aware_validation_and_are_not_capture_hashes(self):
        for name in FILES:
            source, _, _, observation, example = inputs(name)
            root = schema(source)
            validator = Draft202012Validator(root, format_checker=FormatChecker())
            self.assertEqual(example['kind'], 'synthetic_example')
            self.assertNotEqual(digest(example['body']), observation['capture_hashes']['body_canonical_hash'])
            validator.validate(example['body'])
            media = next(iter(source['paths'].values()))['get']['responses']['200']['content']['application/json']
            self.assertEqual(set(media['examples']), {'synthetic_success'})
            published = media['examples']['synthetic_success']
            self.assertIn('not a production response', published['description'])
            self.assertEqual(published['value'], example['body'])
            self.assertNotIn('required', root)
            self.assertNotIn('required', root['properties']['data']['items'])
            self.assertEqual(root['properties']['data']['items']['type'], ['object', 'null'])
            self.assertNotIn('item_definition_unconfirmed', json.dumps(root))
            validator.validate({'data': [None, {}]})
            bad = copy.deepcopy(example['body'])
            bad['data'][0] = []
            self.assertFalse(validator.is_valid(bad))

    def test_only_observed_date_field_formats_are_removed(self):
        for name in FILES:
            source, _, _, _, _ = inputs(name)
            root = schema(source)
            meta = root['properties']['meta']['properties']
            for field in ('start_date', 'end_date'):
                self.assertNotIn('format', meta['request']['properties'][field])
            self.assertNotIn('format', meta['last_updated'])
            if name == 'demographics':
                self.assertEqual(meta['last_update']['format'], 'date-time')
                validator = Draft202012Validator(root, format_checker=FormatChecker())
                self.assertFalse(validator.is_valid({'meta': {'last_update': '2025-01-31'}}))
                validator.validate({'meta': {'last_update': '2025-01-31T00:00:00Z'}})
            else:
                self.assertNotIn('format', root['properties']['data']['items']['properties']['date'])

    def test_observed_string_items_do_not_add_sample_enums_or_requiredness(self):
        keyword, _, _, _, _ = inputs('keywords')
        root = schema(keyword)
        ai = root['properties']['data']['items']['properties']['ai_overview']['items']
        self.assertEqual(ai['type'], ['string', 'null'])
        self.assertNotIn('enum', ai)
        Draft202012Validator(root, format_checker=FormatChecker()).validate({'data': [{'date': '2025-01', 'ai_overview': ['another phrase', None]}]})
        demographic, _, _, _, example = inputs('demographics')
        root = schema(demographic)
        echoed = root['properties']['meta']['properties']['request']
        self.assertEqual(echoed['required'], ['domain'])
        self.assertEqual(echoed['properties']['age_buckets']['items']['type'], ['string', 'null'])
        self.assertEqual(echoed['properties']['metrics']['items']['enum'],
                         ['share', 'pages_per_visit', 'bounce_rate', 'average_visit_duration', None])
        validator = Draft202012Validator(root, format_checker=FormatChecker())
        bad = copy.deepcopy(example['body'])
        bad['meta']['request']['metrics'] = ['not-an-official-metric']
        self.assertFalse(validator.is_valid(bad))
        bad['meta']['request']['metrics'] = ['share']
        bad['meta']['request']['age_buckets'] = ['65']
        validator.validate(bad)

    def test_both_languages_publish_only_the_labeled_synthetic_example(self):
        for name, filename in PAGES.items():
            source, _, _, _, example = inputs(name)
            for locale in ('api-reference', 'zh/api-reference'):
                with self.subTest(name=name, locale=locale):
                    page = (ROOT / locale / 'similarweb' / filename).read_text()
                    human = page.split('{/* aisa-contract-details:start */}', 1)[0]
                    samples = [json.loads(block) for block in re.findall(r'```json\n(.*?)\n```', human, re.S)]
                    self.assertEqual(samples, [example['request_query'], example['body']])
                    self.assertIn('synthetic' if locale == 'api-reference' else '模拟', human)
                    Draft202012Validator(schema(source), format_checker=FormatChecker()).validate(samples[1])
                    self.assertNotIn('Captured successful response', human)
                    self.assertNotIn('以下参数及响应来自这次请求', human)

    def test_attestations_contain_shapes_not_production_values(self):
        self.assertEqual(shape_attestation({'metric': 12.5, 'terms': ['illustrative'], 'day': '2025-01-01'}), {
            'type': 'object', 'properties': {
                'metric': {'type': 'number'},
                'terms': {'type': 'array', 'observed_item_count': 1, 'observed_items': [{'type': 'string'}]},
                'day': {'type': 'string', 'format_checks': {'date': True, 'date-time': False}},
            }})

        def assert_value_free(node):
            self.assertLessEqual(set(node), {'type', 'properties', 'observed_item_count', 'observed_items', 'format_checks'})
            for child in node.get('properties', {}).values():
                assert_value_free(child)
            for child in node.get('observed_items', []):
                assert_value_free(child)

        for name in FILES:
            _, _, _, observation, _ = inputs(name)
            self.assertNotIn('body', observation)
            self.assertEqual(observation['kind'], 'private_response_shape_attestation')
            assert_value_free(observation['body_shape'])

    def test_only_exact_successful_attestation_can_authorize_the_correction(self):
        for name in FILES:
            _, prior, raw, original, example = inputs(name)
            for change in ('method', 'origin', 'path', 'http', 'status', 'empty', 'nonobject', 'shape', 'query', 'timestamp', 'hash'):
                with self.subTest(name=name, change=change):
                    record = copy.deepcopy(original)
                    data = record['body_shape']['properties']['data']
                    if change == 'method': record['request']['method'] = 'POST'
                    if change == 'origin': record['request']['origin'] = 'https://example.invalid'
                    if change == 'path': record['request']['path'] += '/other'
                    if change == 'http': record['http_status'] = 400
                    if change == 'status': record['response_status'] = 'error'
                    if change == 'empty': data['observed_items'] = []
                    if change == 'nonobject': data['observed_items'][0]['type'] = 'array'
                    if change == 'shape': data['observed_items'][0]['properties']['invented'] = {'type': 'boolean'}
                    if change == 'query': record['request']['query']['country'] = 'us'
                    if change == 'timestamp': record['observed_at'] = '2099-01-01T00:00:00Z'
                    if change == 'hash': record['capture_hashes']['body_canonical_hash'] = digest({})
                    with self.assertRaises(ValueError):
                        amend_observed_response(prior, raw, record, EVIDENCE, example)

    def test_source_only_converter_still_rejects_and_predecessor_is_exact(self):
        for name in FILES:
            _, prior, raw, observation, example = inputs(name)
            path = observation['request']['path']
            with self.assertRaisesRegex(ValueError, 'named child|item schema absent'):
                convert_reference(raw, '/v5/' + path.removeprefix('/apis/v1/similarweb/'), prior['info']['x-aisa-source']['url'])
            invalid = copy.deepcopy(prior)
            invalid['info']['title'] = 'unreviewed source'
            with self.assertRaisesRegex(ValueError, 'prior source'):
                amend_observed_response(invalid, raw, observation, EVIDENCE, example)
            invalid_example = copy.deepcopy(example)
            invalid_example['kind'] = 'actual_response'
            with self.assertRaisesRegex(ValueError, 'synthetic'):
                amend_observed_response(prior, raw, observation, EVIDENCE, invalid_example)


if __name__ == '__main__':
    unittest.main()
