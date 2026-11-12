import copy
import unittest
from check_contract_candidate import response_contract


class ResponseReferenceComparisonTests(unittest.TestCase):
    def fixture(self, prefix):
        ref = '#/components/schemas/' + prefix
        schema = {'type': 'object', 'properties': {'kind': {'const': 'a'},
                  'next': {'$ref': ref}}}
        doc = {'components': {'schemas': {prefix: schema, prefix+'Other': {'type': 'string'}}}}
        response = {'content': {'application/json': {'schema': {
            'discriminator': {'propertyName': 'kind', 'mapping': {'a': ref}},
            'oneOf': [{'$ref': ref}], 'default': {'$ref': 'literal'}}}}}
        return response, doc

    def test_namespace_and_serialization_order_are_not_contract_changes(self):
        a, ad = self.fixture('Old')
        b, bd = self.fixture('New')
        bd['components']['schemas']['New']['properties'] = dict(reversed(list(
            bd['components']['schemas']['New']['properties'].items())))
        self.assertEqual(response_contract(a, ad), response_contract(b, bd))

    def test_mapping_target_and_constraints_remain_significant(self):
        a, ad = self.fixture('Old')
        for change in ('target', 'constraint', 'mapping_key'):
            b, bd = copy.deepcopy(a), copy.deepcopy(ad)
            schema = b['content']['application/json']['schema']
            if change == 'target': schema['discriminator']['mapping']['a'] += 'Other'
            elif change == 'mapping_key': schema['discriminator']['mapping']['b'] = schema['discriminator']['mapping'].pop('a')
            else: bd['components']['schemas']['Old']['maxProperties'] = 1
            self.assertNotEqual(response_contract(a, ad), response_contract(b, bd))

    def test_unresolved_or_external_mapping_fails_closed(self):
        for target in ('#/components/schemas/missing', 'https://example.com/schema'):
            a, ad = self.fixture('Old')
            a['content']['application/json']['schema']['discriminator']['mapping']['a'] = target
            with self.assertRaises((ValueError, KeyError)):
                response_contract(a, ad)
