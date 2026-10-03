import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wrapper_cloudsway_reference as cloudsway
import wrapper_twitter_reference as twitter
from compose_openapi import compose
from test_runtime_contracts import facts, operation

FIXTURES = Path(__file__).parent / 'fixtures'


class WrapperReferenceTests(unittest.TestCase):
    def test_twitter_source_http_contract_and_body_requirements(self):
        document, metadata = twitter.convert_reference(
            (FIXTURES / 'wrapper_twitter_routes.py.txt').read_bytes(),
            (FIXTURES / 'wrapper_twitter_schemas.py.txt').read_bytes())
        op = document['paths']['/delete_twitter']['post']
        body = op['requestBody']['content']['application/json']['schema']
        self.assertEqual(set(body['required']), {'aisa_api_key', 'tweet_id'})
        self.assertNotIn('maxLength', body['properties']['tweet_id'])
        self.assertEqual(body['properties']['tweet_id']['x-aisa-normalized-schema'], {'type': 'string', 'minLength': 1, 'maxLength': 64})
        self.assertEqual(body['properties']['tweet_id']['x-aisa-normalization'], 'strip')
        self.assertNotIn('additionalProperties', body)  # Pydantic ignores extras.
        self.assertEqual(metadata['source_revision'], twitter.REVISION)
        self.assertEqual(len(metadata['source_pages']), 2)

    def test_twitter_changed_method_validator_or_fields_fail_closed(self):
        routes = (FIXTURES / 'wrapper_twitter_routes.py.txt').read_bytes()
        schema = (FIXTURES / 'wrapper_twitter_schemas.py.txt').read_bytes()
        variants = [(routes.replace(b'router.post(', b'router.delete('), schema),
                    (routes, schema.replace(b'value.strip()', b'value.lower()')),
                    (routes, schema.replace(b'aisa_api_key:', b'api_key:'))]
        for r, s in variants:
            with self.assertRaises(ValueError): twitter.convert_reference(r, s)

    def test_smart_official_query_fields_defaults_and_private_mapping(self):
        document, metadata = cloudsway.convert_reference((FIXTURES / 'wrapper_cloudsway_smart.html').read_bytes())
        params = {p['name']: p for p in document['paths']['/apis/v1/search/smart']['get']['parameters']}
        self.assertTrue(params['q']['required'])
        self.assertEqual(params['count']['schema']['enum'], [10,20,30,40,50])
        self.assertEqual(params['count']['schema']['default'], 10)
        self.assertFalse(params['enableContent']['schema']['default'])
        self.assertEqual(params['contentTimeout']['schema']['maximum'], 10)
        self.assertEqual(params['contentType']['schema']['default'], 'TEXT')
        self.assertNotIn('Authorization', params)
        self.assertEqual(metadata['path_space'], 'public')
        self.assertEqual(len(metadata['upstream_path_sha256']), 64)
        self.assertEqual(metadata['original_upstream_path_template'], '/search/{Endpoint}/smart')
        self.assertNotIn('/apis/v1/search/full', document['paths'])

    def test_smart_unknown_type_or_changed_method_fails_closed(self):
        raw = (FIXTURES / 'wrapper_cloudsway_smart.html').read_bytes()
        for source in [raw.replace(b'>Short<', b'>Maybe<'), raw.replace(b'GET',b'POST')]:
            with self.assertRaises(ValueError): cloudsway.convert_reference(source)

    def test_twitter_compose_keeps_runtime_price_and_identity(self):
        from catalog_fixture import catalog_root
        root = catalog_root()
        source = json.loads((root/'openapi/upstream/wrapper-twitter-delete.json').read_text())
        runtime = facts('provider')
        op = operation(runtime)
        op['x-aisa-upstream-path'] = '/delete_twitter'
        path = next(iter(runtime['paths']))
        runtime['paths'][path] = {'post': op}
        output,pending=compose(runtime,source)
        self.assertFalse(pending)
        actual=next(iter(output['paths'].values()))['post']
        self.assertEqual(actual['x-aisa-pricing'],op['x-aisa-pricing'])
        self.assertEqual(actual['operationId'],op['operationId'])
        self.assertIn('requestBody',actual)

    def test_twitter_normalized_bounds_do_not_reject_valid_raw_whitespace(self):
        from jsonschema import Draft202012Validator
        document, _ = twitter.convert_reference((FIXTURES/'wrapper_twitter_routes.py.txt').read_bytes(), (FIXTURES/'wrapper_twitter_schemas.py.txt').read_bytes())
        field = document['paths']['/delete_twitter']['post']['requestBody']['content']['application/json']['schema']['properties']['tweet_id']
        raw = Draft202012Validator(field)
        normalized = Draft202012Validator(field['x-aisa-normalized-schema'])
        for value, valid in [(' ' + 'x'*64 + ' ', True), (' ', False), ('x'*65, False), (' x ', True)]:
            self.assertTrue(raw.is_valid(value))
            self.assertEqual(normalized.is_valid(value.strip()), valid)


if __name__ == '__main__': unittest.main()
