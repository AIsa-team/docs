import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev_release_pages import DEV_API, DEV_SITE, project, project_openapi
from fetch_runtime_release import sha
from sync_dev_runtime import acquire_dev_release
import test_fetch_runtime_release
from test_runtime_contracts import facts
import test_runtime_contract_artifact


class DevReleaseTests(unittest.TestCase):
    def test_only_published_canonical_members_become_inputs(self):
        fixture = test_runtime_contract_artifact.CanonicalArtifactTests()
        fixture.setUp()
        files, receipt = acquire_dev_release(fixture.reader)
        self.assertEqual(files, {k: fixture.contents[k] for k in
                                 ('contracts/native/example.json', 'contracts/openapi.json')})
        self.assertTrue(receipt['fresh_before_and_after'])
        fixture.current['fresh'] = False
        with self.assertRaisesRegex(ValueError, 'fresh'):
            acquire_dev_release(fixture.reader)
        _, _, reader, _, _, _ = test_fetch_runtime_release.PublicReleaseTests().fixture()
        with self.assertRaisesRegex(ValueError, 'canonical'):
            acquire_dev_release(reader)

    def test_project_only_declared_origins_and_keep_input_hash_scope(self):
        prod = 'https://api.aisa.one'
        schema = {'const': prod, 'description': prod, 'example': {'servers': [{'url': prod}]}}
        op = {'responses': schema, 'externalDocs': {'url': prod},
              'servers': [{'url': prod + '.example'}, {'url': prod + '/v1'}],
              'x-aisa-docs-url': 'https://aisa.one/docs/api-reference/example/one'}
        raw = json.dumps({'info': {'x-aisa-document': {'document_hash': 'original'}},
                          'servers': [{'url': prod}], 'paths': {'/one': {
                              'get': op, 'servers': [{'url': prod + '/prefix'}]}}}).encode()
        doc, output = project_openapi(raw)
        item = doc['paths']['/one']
        self.assertEqual(doc['servers'], [{'url': DEV_API}])
        self.assertEqual(item['servers'], [{'url': DEV_API + '/prefix'}])
        self.assertEqual(item['get'], {**op, 'x-aisa-docs-url': DEV_SITE + '/api-reference/example/one',
                                       'servers': [{'url': prod + '.example'}, {'url': DEV_API + '/v1'}]})
        self.assertEqual(doc['info']['x-aisa-dev-projection']['source_sha256'], sha(raw))
        self.assertEqual(doc['info']['x-aisa-document'], {'source_document_hash': 'original'})
        # The next input already uses the dev environment. Preserve its exact bytes.
        self.assertEqual(project_openapi(output)[1], output)

    def test_published_slug_restores_archived_binding_and_repeats_exactly(self):
        page = 'api-reference/example/stable'
        path = '/apis/v1/similarweb/test'
        document = facts()
        document['info']['x-aisa-document']['document_hash'] = 'published'
        document['paths'][path]['post']['x-aisa-docs-url'] = 'https://aisa.one/docs/' + page
        raw = json.dumps(document).encode()
        files = {'contracts/native/example.json': raw, 'contracts/openapi.json': raw}
        release = {'artifact_revision': 'a' * 64}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'translations').mkdir()
            for name in ('openapi-zh', 'openapi-nav-zh'):
                (root / f'translations/{name}.json').write_text('{}')
            languages = []
            for language, tab, prefix in [('en', 'API Reference', ''), ('zh', 'API 参考', 'zh/')]:
                languages.append({'language': language, 'tabs': [{'tab': tab, 'groups': []}]})
                target = root / f'{prefix}{page}.mdx'
                target.parent.mkdir(parents=True)
                target.write_text('---\ntitle: Former\nx-aisa-archived-openapi: "openapi/old.json GET /old"\n---\n')
                (target.parent / 'absent.mdx').write_text('---\nopenapi: "openapi/old.json GET /absent"\n---\n')
            config = {'navigation': {'languages': languages}, 'api': {'mdx': {}}, 'markdown': {}}
            (root / 'docs.json').write_text(json.dumps(config))
            first = project(root, files, release)
            for name, content in first.items():
                target = root / name
                target.parent.mkdir(exist_ok=True, parents=True)
                target.write_bytes(content)
            for prefix in ['', 'zh/']:
                self.assertIn(f'openapi: "openapi/{prefix}example.json POST {path}"'.encode(),
                              first[f'{prefix}{page}.mdx'])
                self.assertEqual(first[f'{prefix}api-reference/example/absent.mdx'].count(b'<Warning>'), 1)
            second = project(root, files, release)
            for name, content in second.items():
                self.assertEqual(content, (root / name).read_bytes(), name)
