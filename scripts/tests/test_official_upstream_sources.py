import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import digest
from import_upstream import import_source

ROOT = Path(__file__).resolve().parents[2]

class OfficialSourceTests(unittest.TestCase):
    def test_official_yaml_equality_enum_preserves_operator_and_safe_types(self):
        raw = b'''openapi: 3.0.1
info: {title: Provider, version: '1'}
paths: {}
components:
  schemas:
    Filter:
      type: string
      enum:
        - =
        - <>
    Switch:
      type: boolean
      default: false
'''
        with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)):
            document = import_source('provider', 'https://provider.example/openapi.yaml')
        self.assertEqual(document['components']['schemas']['Filter']['enum'], ['=', '<>'])
        self.assertIs(document['components']['schemas']['Switch']['default'], False)
        self.assertEqual(document['info']['x-aisa-source']['converter'], 'scripts/import_upstream.py@2')

    def test_candidate_sources_are_official_unmodified_documents_with_resolvable_refs(self):
        urls = {
            'agentmail-official': 'https://docs.agentmail.to/openapi.json',
            'financial-official': 'https://docs.financialdatasets.ai/api/openapi.json',
            'kalshi-official': 'https://docs.kalshi.com/openapi.yaml',
            'coingecko-official': 'https://raw.githubusercontent.com/coingecko/coingecko-api-oas/main/pro-api.json',
            'dataforseo-official': 'https://raw.githubusercontent.com/dataforseo/OpenApiDocumentation/master/openapi_specification.yaml',
        }
        for name, url in urls.items():
            with self.subTest(source=name):
                document = json.loads((ROOT / 'openapi/upstream' / (name + '.json')).read_text())
                original = copy.deepcopy(document)
                source = original['info'].pop('x-aisa-source')
                self.assertEqual(source['kind'], 'provider_openapi')
                self.assertNotIn('path_space', source)
                self.assertEqual(source['url'], url)
                self.assertEqual(source['content_hash'], digest(original))
                def walk(value):
                    if isinstance(value, dict):
                        if '$ref' in value:
                            ref = value['$ref']
                            self.assertTrue(ref.startswith('#/'), ref)
                            target = document
                            for part in ref[2:].split('/'):
                                target = target[part.replace('~1', '/').replace('~0', '~')]
                        for child in value.values():
                            walk(child)
                    elif isinstance(value, list):
                        for child in value:
                            walk(child)
                walk(document)

    def test_missing_agentmail_and_dataforseo_routes_have_real_source_schemas(self):
        mail = json.loads((ROOT / 'openapi/upstream/agentmail-official.json').read_text())
        for path in ['/v0/api-keys/{api_key_id}', '/v0/domains/{domain_id}',
                     '/v0/domains/{domain_id}/verify', '/v0/domains/{domain_id}/zone-file',
                     '/v0/inboxes/{inbox_id}/api-keys', '/v0/inboxes/{inbox_id}/api-keys/{api_key_id}']:
            self.assertIn(path, mail['paths'])
        seo = json.loads((ROOT / 'openapi/upstream/dataforseo-official.json').read_text())
        for tail in ['competitors_domain', 'domain_intersection', 'domain_metrics_by_categories',
                     'historical_serps', 'page_intersection', 'ranked_keywords']:
            operation = seo['paths'][f'/v3/dataforseo_labs/google/{tail}/live']['post']
            self.assertIn('requestBody', operation)
        for tail in ['instant_pages', 'pages']:
            self.assertIn('requestBody', seo['paths'][f'/v3/on_page/{tail}']['post'])
