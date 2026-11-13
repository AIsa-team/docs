"""Spec #1285 R1: customer-facing catalog projection (openapi-public/)."""
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_projection  # noqa: E402
import release_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_HASH = 'a' * 64


def formal_catalog():
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Widgets', 'x-aisa-document': {'document_hash': 'sha256:' + 'b' * 64, 'facts_hash': 'c' * 64},
                 'x-aisa-source': {'url': 'https://supplier.invalid/catalog'}},
        'paths': {'/apis/v1/widgets/search': {'get': {
            'operationId': 'widgets.search', 'summary': 'Search widgets',
            'x-aisa-source': {'url': 'https://supplier.invalid/op', 'converter': 'x'},
            'x-aisa-source-provenance': {'kind': 'manual'},
            'x-aisa-upstream-path': '/v2/widgets',
            'x-aisa-upstream-selector': {'in': 'query', 'name': 'engine', 'value': 'w'},
            'x-aisa-response-source': {'source': {'upstream_origin_sha256': UPSTREAM_HASH}},
            'x-aisa-pricing': {'mode': 'fixed'},
            'parameters': [{'name': 'domain', 'in': 'query', 'schema': {'type': 'string'},
                            # Data positions are customer values, never stripped.
                            'examples': {'default': {'value': {'x-aisa-source': 'kept'}}}}],
            'responses': {'200': {'description': 'OK', 'content': {'application/json': {'schema': {
                'type': 'object',
                'x-aisa-response-upstream-path-sha256': UPSTREAM_HASH,
                'x-aisa-response-upstream-origin-sha256': UPSTREAM_HASH,
                'properties': {'id': {'type': 'string', 'description': 'Widget id.'}}}}}}},
        }}},
    }


class ProjectionTests(unittest.TestCase):
    def test_project_strips_provenance_and_rebinds_document_hash(self):
        source = formal_catalog()
        projected = public_projection.project(source)
        text = json.dumps(projected)
        for key in public_projection.STRIPPED_KEYS - {'x-aisa-source'}:
            self.assertNotIn('"' + key + '"', text)
        self.assertNotIn('supplier.invalid', text)
        self.assertNotIn(UPSTREAM_HASH, text)
        operation = projected['paths']['/apis/v1/widgets/search']['get']
        self.assertNotIn('x-aisa-source', operation)
        self.assertEqual(operation['parameters'][0]['examples']['default']['value'], {'x-aisa-source': 'kept'})
        self.assertEqual(operation['x-aisa-pricing'], {'mode': 'fixed'})
        self.assertEqual(operation['responses']['200']['content']['application/json']['schema']['properties'],
                         {'id': {'type': 'string', 'description': 'Widget id.'}})
        meta = projected['info']['x-aisa-document']
        self.assertEqual(meta['public_projection'], {'version': '2', 'source_document_hash': 'sha256:' + 'b' * 64})
        unhashed = json.loads(json.dumps(projected))
        unhashed['info']['x-aisa-document'].pop('document_hash')
        self.assertEqual(meta['document_hash'], public_projection.digest(unhashed))
        self.assertEqual(meta['facts_hash'], 'c' * 64)
        # The formal document is not modified.
        self.assertEqual(source, formal_catalog())
        self.assertEqual(public_projection.project(source), projected)

    def test_price_construction_and_revision_are_private_but_payload_names_survive(self):
        import copy
        source = formal_catalog()
        op = source['paths']['/apis/v1/widgets/search']['get']
        op['x-aisa-revision'] = {'profile_ref': 'private'}
        op['x-aisa-pricing'] = {'customer_pricing': 'provider_cost_multiplier',
                              'customer_multiplier': 2, 'cost_contract': 'response_units',
                              'unit_rate_usd': .000001, 'unit': 'provider_credit',
                              'default_request_estimate_usd': .9}
        schema = op['responses']['200']['content']['application/json']['schema']
        schema['properties']['x-aisa-revision'] = {'type': 'string'}
        original = copy.deepcopy(source)
        public = public_projection.project(source)['paths']['/apis/v1/widgets/search']['get']
        self.assertNotIn('x-aisa-revision', public)
        self.assertEqual(public['x-aisa-pricing'], {'customer_pricing': 'usage_based', 'default_request_estimate_usd': .9})
        self.assertEqual(public['responses']['200']['content']['application/json']['schema']['properties']['x-aisa-revision'], {'type': 'string'})
        self.assertEqual(source, original)

    def test_write_check_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi/zh').mkdir(parents=True)
            (root / 'scripts').mkdir()
            for name in ('openapi/widgets.json', 'openapi/zh/widgets.json', 'openapi/other.json'):
                (root / name).write_text(json.dumps(formal_catalog()))
            (root / 'scripts/public_projection.json').write_text(json.dumps(
                {'schema_version': 1, 'catalogs': ['not-yet-published', 'widgets']}))
            self.assertEqual(public_projection.check(root), [('openapi-public/widgets.json', 'missing'),
                                                             ('openapi-public/zh/widgets.json', 'missing')])
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(public_projection.main(['--root', str(root), '--check']), 1)
                self.assertEqual(public_projection.main(['--root', str(root), '--write']), 0)
                self.assertEqual(public_projection.main(['--root', str(root), '--check']), 0)
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in (root / 'openapi-public').rglob('*.json')),
                             ['openapi-public/widgets.json', 'openapi-public/zh/widgets.json'])
            (root / 'openapi-public/stray.json').write_text('{}')
            self.assertEqual(public_projection.check(root), [('openapi-public/stray.json', 'unexpected')])
            public_projection.write(root)
            self.assertEqual(public_projection.check(root), [])

    def test_page_renderer_uses_public_schema_and_hides_formal_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'api-reference').mkdir()
            page = root / 'api-reference/widgets.mdx'
            page.write_text('---\nopenapi: "openapi/widgets.json GET /widgets"\n---\nEditorial prose.\n')
            (root / '.mintignore').write_text('/openapi.yaml\n')
            changes = public_projection.public_surface_changes(root, ['widgets'])
            self.assertIn(b'openapi-public/widgets.json', changes['api-reference/widgets.mdx'])
            self.assertIn(b'Editorial prose.', changes['api-reference/widgets.mdx'])
            self.assertIn(b'/openapi/widgets.json', changes['.mintignore'])
            for name, raw in changes.items():
                (root / name).write_bytes(raw)
            self.assertEqual(public_projection.public_surface_changes(root, ['widgets']), {})

    def test_catalog_list_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'list.json'
            for catalogs in (['b', 'a'], ['a', 'a'], ['../x'], ['openapi'], 'a'):
                with self.subTest(catalogs=catalogs):
                    path.write_text(json.dumps({'schema_version': 1, 'catalogs': catalogs}))
                    with self.assertRaises(ValueError):
                        public_projection.load_catalogs(path)

    def test_public_path_maps_only_projected_catalogs(self):
        catalogs = frozenset({'tiktok'})
        self.assertEqual(public_projection.public_path('openapi/tiktok.json', catalogs), 'openapi-public/tiktok.json')
        self.assertEqual(public_projection.public_path('openapi/zh/tiktok.json', catalogs), 'openapi-public/zh/tiktok.json')
        self.assertEqual(public_projection.public_path('openapi/apollo.json', catalogs), 'openapi/apollo.json')
        self.assertEqual(public_projection.public_path('reference-contracts/account.json', catalogs),
                         'reference-contracts/account.json')
        self.assertEqual(public_projection.public_path('openapi/upstream/tiktok.json', catalogs), 'openapi/upstream/tiktok.json')


class CommittedProjectionTests(unittest.TestCase):
    """The committed checkout: projection current, complete and clean."""

    def test_committed_projection_is_current(self):
        self.assertEqual(public_projection.check(ROOT), [])

    def test_every_in_scope_catalog_is_projected(self):
        listed = set(public_projection.load_catalogs())
        scope = release_gate.load_scope(release_gate.SCOPE)
        catalogs = {path.stem for path, *_ in release_gate.in_scope_operations(ROOT, scope)}
        self.assertTrue(catalogs)
        self.assertEqual(catalogs - listed, set())

    def test_projection_has_no_provenance_or_upstream_hash(self):
        files = sorted((ROOT / public_projection.PUBLIC_DIR).rglob('*.json'))
        self.assertTrue(files)
        hash_rules = [re.compile(r'"(?:upstream_(?:origin|path)_sha256|x-aisa-response-upstream-[a-z]+-sha256)"')]
        for path in files:
            text = path.read_text()
            for key in public_projection.STRIPPED_KEYS:
                self.assertNotIn('"' + key + '"', text, path.name)
            for rule in hash_rules:
                self.assertIsNone(rule.search(text), path.name)

    def test_projected_pages_link_the_projection(self):
        listed = set(public_projection.load_catalogs())
        link = re.compile(r'\]\(https://aisa\.one/docs/(openapi(?:-public)?)/(?:zh/)?([A-Za-z0-9_.-]+)\.json\)')
        seen = 0
        for directory in ('api-reference', 'zh/api-reference'):
            for page in (ROOT / directory).rglob('*.mdx'):
                for folder, name in link.findall(page.read_text()):
                    if name in listed:
                        seen += 1
                        self.assertEqual(folder, 'openapi-public', str(page))
        self.assertGreater(seen, 0)


if __name__ == '__main__':
    unittest.main()
