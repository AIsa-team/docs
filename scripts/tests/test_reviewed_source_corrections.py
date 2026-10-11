import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import digest
from import_similarweb_response_reference import field_schema

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads((ROOT / path).read_text())


class ReviewedSourceCorrectionsTests(unittest.TestCase):
    def test_official_scalar_amendments_match_saved_declarations(self):
        evidence = read('docs/source-corrections-20261012.json')
        count = 0
        for row in evidence['official_response_leaf_changes']:
            doc = read(row['file'])
            source = doc['info']['x-aisa-source']
            self.assertEqual(source['response_contract_review'], row)
            props = doc['paths'][row['public_path']]['get']['responses']['200']['content']['application/json']['schema']['properties']['data']['items']['properties']
            for change in row['changes']:
                name = change['field'].removeprefix('data[].')
                self.assertEqual(props[name], field_schema(change['official_declaration'], change['field']))
                self.assertEqual(props[name], change['after'])
                count += 1
        self.assertEqual(count, 40)

    def test_unconfirmed_array_items_do_not_assert_a_false_scalar_type(self):
        from jsonschema import Draft202012Validator
        count = 0
        for row in read('docs/source-corrections-20261012.json')['official_response_leaf_changes']:
            partial = row.get('partial_array_declaration')
            if not partial:
                continue
            document = read(row['file'])
            schema = document['paths'][row['public_path']]['get']['responses']['200']['content']['application/json']['schema']['properties']['data']['items']['properties']['serp_features']
            self.assertEqual(schema, partial['after'])
            self.assertNotIn('items', schema)
            self.assertEqual(schema['x-aisa-schema-status'], 'item_definition_unconfirmed')
            validator = Draft202012Validator(schema)
            for value in (None, [], ['known observation']):
                self.assertEqual(list(validator.iter_errors(value)), [])
            for value in ('incorrect scalar', 1, {}):
                self.assertTrue(list(validator.iter_errors(value)))
            count += 1
        self.assertEqual(count, 3)

    def test_obsolete_region_samples_removed_without_relabeling(self):
        evidence = read('docs/source-corrections-20261012.json')
        self.assertEqual(sum(x['examples_removed'] for x in evidence['region_samples_removed']), 36)
        for row in evidence['region_samples_removed']:
            for path in read(row['file'])['paths'].values():
                for op in path.values():
                    for response in op.get('responses', {}).values():
                        for media in response.get('content', {}).values():
                            self.assertNotEqual(media.get('example', {}).get('meta', {}).get('request', {}).get('country'), 'us')

    def test_amended_sources_have_new_content_identity(self):
        files = {x['file'] for x in read('docs/source-corrections-20261012.json')['region_samples_removed']}
        files.update(['openapi/upstream/youte-search.json', 'openapi/upstream/exa.json'])
        for file in files:
            document = read(file)
            source = document['info'].pop('x-aisa-source')
            self.assertEqual(source['content_hash'], digest(document), file)
            old = source.get('prior_source', source.get('request_source'))
            self.assertNotEqual(source['content_hash'], old['content_hash'], file)

    def test_youtube_official_shape_and_exa_pricing_scope(self):
        doc = read('openapi/upstream/youte-search.json')
        schemas = doc['components']['schemas']
        self.assertEqual(schemas['Video']['properties']['thumbnail']['$ref'], '#/components/schemas/Thumbnail')
        self.assertEqual(schemas['Channel']['properties']['thumbnail']['$ref'], '#/components/schemas/Thumbnail')
        self.assertEqual(schemas['Channel']['properties']['subscribers']['type'], 'integer')
        self.assertEqual(schemas['Thumbnail']['type'], 'object')
        exa = (ROOT / 'openapi/upstream/exa.json').read_text()
        self.assertNotIn('flat $0.08', exa)
        self.assertNotIn('flat $0.10', exa)

    def test_balance_sample_components_and_language_parity(self):
        import re
        samples = []
        for prefix in ('', 'zh/'):
            text = (ROOT / (prefix + 'api-reference/credits-balance.mdx')).read_text()
            sample = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S)[1])
            gtm = sample['gtm']
            self.assertEqual(gtm['balance_micros_usd'], gtm['trial_balance_micros_usd'] + gtm['subscription_balance_micros_usd'] + gtm['subscription_addon_available_micros_usd'])
            self.assertEqual(gtm['subscription_addon_balance_micros_usd'], gtm['subscription_addon_available_micros_usd'] + gtm['subscription_addon_frozen_micros_usd'])
            self.assertIn('media_promo', sample)
            samples.append(sample)
        self.assertEqual(*samples)


if __name__ == '__main__':
    unittest.main()
