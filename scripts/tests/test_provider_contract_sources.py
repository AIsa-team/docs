"""Coverage and schema checks for the production-bound provider source review."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from compose_openapi import referenced_components, schema_30_to_31
from runtime_registry import public_mirror_index


class ProviderContractSourceTests(unittest.TestCase):
    def test_every_enabled_alexandria_operation_has_bound_source_and_valid_examples(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261112/alexandria-contract-review.json').read_text())
        self.assertEqual(review['operation_count'], 2063)
        self.assertEqual(review['catalog_count'], 351)
        index = public_mirror_index(ROOT)
        seen = set()
        request_examples = response_examples = 0
        documents = {}
        for row in review['operations']:
            with self.subTest(path=row['path']):
                self.assertNotIn(row['endpoint_id'], seen)
                seen.add(row['endpoint_id'])
                if row['source_file'] not in documents:
                    documents[row['source_file']] = json.loads((ROOT / row['source_file']).read_text())
                source = documents[row['source_file']]
                metadata = source['info']['x-aisa-source']
                binding = next(e for e in metadata['operation_evidence'] if e['path'] == row['path'])
                self.assertEqual(binding['descriptor_sha256'], row['source_descriptor_sha256'])
                selected = index[(row['path'], row['method'].lower())]
                self.assertNotIn('x-aisa-mirror-error', selected['operation'])
                operation = source['paths'][row['path']]['post']
                request = operation['requestBody']['content']['application/json']
                response = operation['responses']['200']['content']['application/json']
                self.assertEqual(response['schema']['x-aisa-schema-completeness'], 'documented-fields-only')
                self.assertNotIn('required', response['schema'])
                self.assertNotIn('payload schema has not been reviewed yet', operation['responses']['200']['description'])
                for media in (request, response):
                    Draft202012Validator.check_schema(media['schema'])
                    for example in media.get('examples', {}).values():
                        Draft202012Validator(media['schema']).validate(example['value'])
                request_examples += len(request.get('examples', {}))
                response_examples += len(response.get('examples', {}))
        self.assertEqual((request_examples, response_examples), (1872, 1872))

    def test_firecrawl_response_sources_pin_the_exact_passthrough_and_refs(self):
        sources = list((ROOT / 'openapi/upstream').glob('response-firecrawl-post-*.json'))
        self.assertEqual(len(sources), 4)
        for path in sources:
            document = json.loads(path.read_text())
            route, item = next(iter(document['paths'].items()))
            upstream = '/v2/' + route.rsplit('/', 1)[1]
            metadata = document['info']['x-aisa-source']
            self.assertEqual(metadata['source_revision'], '999f3b10e5322c5d32a46f44b1bc7c243adcb7a3')
            self.assertTrue(metadata['response_only'])
            self.assertEqual(metadata['upstream_path_sha256'], hashlib.sha256(upstream.encode()).hexdigest())
            self.assertEqual(metadata['upstream_origin_sha256'], hashlib.sha256(b'https://api.firecrawl.dev').hexdigest())
            operation = item['post']
            self.assertNotIn('requestBody', operation)
            self.assertEqual(referenced_components(operation, document), document['components'])
            schema = schema_30_to_31(operation['responses']['200']['content']['application/json']['schema'])
            schema['components'] = {'schemas': {n: schema_30_to_31(v) for n, v in document['components'].get('schemas', {}).items()}}
            Draft202012Validator.check_schema(schema)
            if upstream == '/v2/scrape':
                self.assertEqual(schema['$ref'], '#/components/schemas/ScrapeResponse')


if __name__ == '__main__':
    unittest.main()
