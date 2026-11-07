import copy
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from compose_openapi import compose, digest
from import_upstream import import_source, OfficialSourceLoader
from import_twitter_endpoint import ENDPOINTS, PREFIX, extract
from test_runtime_contracts import facts, operation

RAW = (Path(__file__).parent / 'fixtures/twitter-endpoints/create_tweet_v2.md').read_bytes()
URL = PREFIX + 'create_tweet_v2.md'


class TwitterEndpointReferenceTests(unittest.TestCase):
    def test_actual_official_page_roundtrip_and_acquisition_hash(self):
        with patch('import_upstream.urlopen', return_value=io.BytesIO(RAW)):
            doc = import_source('twitter-create-tweet-v2', URL)
        source = doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(doc))
        self.assertEqual(source['url'], URL)
        self.assertEqual(source['refresh_policy'], 'automatic')
        self.assertTrue(source['official_reference_sha256'])
        self.assertEqual(doc['paths']['/twitter/create_tweet_v2']['post']['requestBody']['content']['application/json']['schema']['required'], ['login_cookies', 'tweet_text', 'proxy'])

    def test_route_method_host_duplicate_and_unknown_sources_fail_closed(self):
        variants = [
            RAW.replace(b'/twitter/create_tweet_v2', b'/twitter/other'),
            RAW.replace(b'yaml POST ', b'yaml GET '),
            RAW.replace(b'https://api.twitterapi.io', b'https://unreviewed.example'),
            RAW + b'\n' + RAW,
            RAW.replace(b'openapi: 3.0.1', b'openapi: 3.0.1\nopenapi: 3.0.1'),
        ]
        for raw in variants:
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                extract(raw, URL, OfficialSourceLoader)
        with self.assertRaises(ValueError):
            extract(RAW, PREFIX + 'send_tweet_v3.md', OfficialSourceLoader)

    def test_all_nine_any_routes_keep_runtime_disabled_identity_and_price(self):
        for name in sorted(ENDPOINTS):
            with self.subTest(name=name):
                raw = (Path(__file__).parent / 'fixtures/twitter-endpoints' / (name + '.md')).read_bytes()
                with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)):
                    doc = import_source('twitter-' + name.replace('_', '-'), PREFIX + name + '.md')
                runtime = facts('provider', 'x-aisa-any')
                op = operation(runtime)
                op['x-aisa-upstream-path'] = '/twitter/' + name
                op['x-aisa-status'] = 'disabled'
                op['x-aisa-passthrough'] = True
                op['parameters'] = []
                path = '/apis/v1/twitter/' + name
                runtime['paths'] = {path: {'x-aisa-any': op}}
                frozen = copy.deepcopy(runtime)
                out, pending = compose(runtime, doc, source_bindings={path: PREFIX + name + '.md'})
                self.assertEqual(pending, [])
                result = out['paths'][path]['post']
                self.assertEqual(result['x-aisa-status'], 'disabled')
                self.assertEqual(result['x-aisa-pricing'], op['x-aisa-pricing'])
                self.assertEqual(result['x-aisa-runtime-operation']['operation_id'], op['operationId'])
                self.assertEqual(result['x-aisa-runtime-operation']['method'], 'ANY')
                self.assertEqual(runtime, frozen)
                self.assertEqual(set(out['paths'][path]), {'post'})
