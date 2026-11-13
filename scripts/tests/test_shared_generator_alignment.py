"""Customer prose and protocol regressions found by comparing dev with PR #334."""
import copy
import unittest

from compose_openapi import merge_object
from pricing_prose import clean_document, clean_text
from runtime_localize_openapi_zh import key_for, localize_tree, strip_translatable


class SharedGeneratorAlignmentTests(unittest.TestCase):
    def test_business_price_field_table_survives_cleanup_and_translation(self):
        text = 'Subscription price: $5 per month. Delivery fee: $2 per delivery.'
        response = {'description': text, 'content': {'application/json': {'schema': {
            'type': 'object', 'x-aisa-schema-completeness': 'documented-fields-only'}}}}
        source = {'paths': {'/records': {'get': {'operationId': 'records',
            'description': 'Find records. Billed $0.02 per call.',
            'responses': {'200': response}}}}}
        original = copy.deepcopy(source)
        cleaned = clean_document(source)
        self.assertEqual(cleaned['paths']['/records']['get']['responses']['200'], response)
        self.assertNotIn('$0.02', cleaned['paths']['/records']['get']['description'])
        translated = 'Business fields: ' + text
        catalog = {'entries': {key_for(text): {'source': text, 'translation': translated}}}
        localized = localize_tree(cleaned, catalog, allow_untranslated=True)
        self.assertEqual(localized['paths']['/records']['get']['responses']['200']['description'], translated)
        self.assertEqual(source, original)
        self.assertEqual(clean_document(cleaned), cleaned)

    def test_supplier_charge_once_claim_does_not_survive_rate_cleanup(self):
        source = ('Billed as a posts read ($0.005). '
                  'Repeat lookups within the same UTC day are charged once. Returns posts.')
        cleaned = clean_text(source)
        self.assertEqual(cleaned, 'Returns posts.')
        self.assertEqual(clean_text(cleaned), cleaned)
        self.assertEqual(clean_text('Failed targets are not charged.'), 'Failed targets are not charged.')

    def test_retired_price_only_description_keeps_localized_protocol_shape(self):
        source = {'paths': {'/records': {'get': {'operationId': 'test',
                  'description': '<!-- aisa-pricing:start -->No charge.<!-- aisa-pricing:end -->',
                  'x-aisa-pricing': {'kind': 'no_customer_charge'}}}}}
        localized = localize_tree(source, {'entries': {}}, allow_untranslated=True)
        self.assertEqual(localized['paths']['/records']['get']['description'], '')
        self.assertEqual(strip_translatable(localized), strip_translatable(source))
        self.assertEqual(localized['paths']['/records']['get']['x-aisa-pricing'],
                         source['paths']['/records']['get']['x-aisa-pricing'])

    def test_rechecking_identical_runtime_rules_preserves_cross_field_constraints(self):
        source = {'type': 'object', 'properties': {'mode': {'type': 'string'}, 'query': {'type': 'string'}},
                  'allOf': [{'if': {'properties': {'mode': {'const': 'search'}}, 'required': ['mode']},
                             'then': {'required': ['query']}}]}
        original = copy.deepcopy(source)
        result = merge_object(source, source)
        self.assertEqual(result['allOf'], source['allOf'])
        self.assertEqual(source, original)
        self.assertEqual(merge_object(result, source), result)


if __name__ == '__main__':
    unittest.main()
