"""Regression evidence for five production-probed Alexandria operations."""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.compose_openapi import compose, digest, merge_object
from scripts.runtime_registry import public_mirror_index

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / 'docs/current-source-review-20261112/alexandria-live-schema-review.json'


class AlexandriaProductionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW.read_text())
        index = public_mirror_index(ROOT)
        cls.operations = {}
        for row in cls.review['operations']:
            facts = {
                'openapi': '3.1.0', 'servers': [{'url': cls.review['origin']}],
                'info': {'title': 'Production probe fixture', 'version': '1',
                         'x-aisa-document': {'facts_hash': digest(row['runtime_operation'])}},
                'paths': {row['path']: {'post': row['runtime_operation']}}}
            document, pending = compose(facts, public_mirrors=index)
            if pending:
                raise AssertionError(pending)
            cls.operations[row['path']] = document['paths'][row['path']]['post']

    def test_recorded_request_outcomes_match_composed_constraints(self):
        self.assertEqual(self.review['origin'], 'https://api.aisa.one')
        self.assertEqual(len(self.operations), 5)
        self.assertEqual(len(self.review['calls']), 23)
        for call in self.review['calls']:
            with self.subTest(case=call['case']):
                schema = self.operations[call['path']]['requestBody']['content']['application/json']['schema']
                if call['case'] == 'wayback-documented-bare-domain':
                    # A format-blind jsonschema installation cannot test URI syntax.
                    # Preserve the Runtime declaration and the independently observed rejection.
                    self.assertEqual(schema['properties']['url']['format'], 'uri')
                    self.assertFalse(urlsplit(call['request']['url']).scheme)
                    self.assertEqual(call['http_status'], 400)
                    continue
                self.assertEqual(Draft202012Validator(schema).is_valid(call['request']), call['request_valid'])
                self.assertEqual(call['request_valid'], call['http_status'] == 200)

    def test_known_response_shapes_reject_wrong_roots_and_wrong_fields(self):
        invalid_fields = {
            'pubmed-ncbi-nlm-nih-gov/publications/related': {'ids': [123]},
            'web-archive-org/captures/history': {'captures': {'archive_url': 'wrong container'}},
            'datalegion/companies/enrich-base': {'matches': [{'company': []}]},
            'datalegion/people/enrich-base-no-contact': {'matches': [{'person': 'wrong record'}]},
            'wikipedia/articles/lookup': [{'article_body': 'wrong body'}],
        }
        for path, op in self.operations.items():
            with self.subTest(path=path):
                media = op['responses']['200']['content']['application/json']
                validator = Draft202012Validator(media['schema'])
                validator.check_schema(media['schema'])
                for value in (None, 123, 'not a provider payload', True):
                    self.assertFalse(validator.is_valid(value))
                self.assertFalse(validator.is_valid(invalid_fields[path.removeprefix('/apis/v1/')]))
                for example in media.get('examples', {}).values():
                    validator.validate(example['value'])
                self.assertIn('Documented field', op['responses']['200']['description'])
                self.assertNotIn('payload schema has not been reviewed yet', json.dumps(op))

    def test_projection_and_observed_nulls_do_not_become_required_fields(self):
        wiki = self.operations['/apis/v1/wikipedia/articles/lookup']
        validator = Draft202012Validator(wiki['responses']['200']['content']['application/json']['schema'])
        for value in ([], [{'name': 'Marie Curie'}], [{'identifier': 19242}],
                      [{'article_body': {'wikitext': 'content'}}], [{'article_body': {'html': '<p>content</p>'}}]):
            validator.validate(value)
        self.assertFalse(validator.is_valid({'name': 'Marie Curie'}))
        for suffix, record in [('companies/enrich-base', {'company': {'locations': [{
                'street_address': None, 'state': None, 'state_code': None, 'postal_code': None}]}}),
                ('people/enrich-base-no-contact', {'person': {'prefix': None, 'suffix': None,
                'summary': {'cleaned': None}, 'education': [{'start_date': None}]}})]:
            schema = self.operations['/apis/v1/datalegion/' + suffix]['responses']['200']['content']['application/json']['schema']
            Draft202012Validator(schema).validate({'matches': [{**record, 'match_metadata': None}]})

    def test_examples_and_prose_follow_the_supported_request_modes(self):
        pubmed = self.operations['/apis/v1/pubmed-ncbi-nlm-nih-gov/publications/related']
        media = pubmed['responses']['200']['content']['application/json']
        self.assertEqual(media['examples']['production']['value']['results'], [])
        self.assertFalse(Draft202012Validator(media['schema']).is_valid({'results': [{'title': 'summary'}]}))
        for unsupported in ('cited_in', 'references'):
            self.assertNotIn(unsupported, pubmed['description'])
        wayback = self.operations['/apis/v1/web-archive-org/captures/history']
        request = wayback['requestBody']['content']['application/json']
        self.assertEqual(set(request['schema']['properties']), {'url', 'limit'})
        self.assertEqual(request['examples']['production']['value']['url'], 'https://firecrawl.dev')
        self.assertNotIn('midnight', wayback['description'])
        company = self.operations['/apis/v1/datalegion/companies/enrich-base']
        self.assertEqual(set(company['requestBody']['content']['application/json']['schema']['properties']), {'domain'})
        self.assertNotIn('Name matching', company['description'])


class ProviderExclusionCompositionTests(unittest.TestCase):
    def setUp(self):
        self.source = {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'fields': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 50},
            'body': {'type': 'string', 'enum': ['wikitext', 'html', 'both', 'none']}},
            'not': {'required': ['fields', 'body']}}
        self.declared = {'type': 'object', 'properties': {'name': {'type': 'string'}},
                         'required': ['name'], 'additionalProperties': True}

    def test_forwarded_supplier_exclusion_survives_recomposition(self):
        result = merge_object(self.source, self.declared)
        self.assertEqual(merge_object(result, self.declared), result)
        validator = Draft202012Validator(result)
        validator.validate({'name': 'Marie_Curie', 'fields': ['name']})
        validator.validate({'name': 'Marie_Curie', 'body': 'none'})
        self.assertFalse(validator.is_valid({'name': 'Marie_Curie', 'fields': ['name'], 'body': 'none'}))

    def test_source_cannot_override_runtime_fields_or_closed_forwarding(self):
        for patch in ({'additionalProperties': False},
                      {'additionalProperties': {'type': 'string'}},
                      {'properties': {**self.declared['properties'], 'body': {'type': 'string'}}},
                      {'not': {'required': ['name', 'fields']}},
                      {'allOf': [{'required': ['fields']}]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                merge_object(self.source, {**self.declared, **patch})
        with self.assertRaises(ValueError):
            merge_object(self.source, self.declared, constrained={'fields'})
        nested = {**self.source, 'properties': {**self.source['properties'], 'options': {'type': 'object'}}}
        with self.assertRaises(ValueError):
            merge_object(nested, self.declared, constrained={'options.fields'}, prefix='options.')

    def test_other_conditionals_and_undeclared_names_still_fail(self):
        for exclusion in ({'required': ['fields']}, {'required': ['fields', 'unknown']},
                          {'required': ['fields', 'fields']}, {'required': ['fields', 123]},
                          {'required': ['fields', 'body'], 'properties': {}}, {'anyOf': []}):
            with self.subTest(exclusion=exclusion), self.assertRaises(ValueError):
                merge_object({**self.source, 'not': exclusion}, self.declared)


if __name__ == '__main__':
    unittest.main()
