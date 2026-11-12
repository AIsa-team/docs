import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_projection  # noqa: E402
import release_gate  # noqa: E402
from playground_examples import example_sha256  # noqa: E402

TERMS = json.dumps(['acmefeeds', 'zeta-gateway.dev'])
HEADER = '# Fixed reference example. Playground inputs do not update this sample.\n'


def operation(path='/apis/v1/widgets/search', *, verified=True, value='stripe.com', sample=True, extra=None):
    op = {'operationId': 'widgets.search', 'summary': 'Search widgets',
          'description': 'Find widgets by company domain.',
          'x-aisa-docs-url': 'https://aisa.one/docs/api-reference/widgets/widgets-search',
          'parameters': [{'name': 'domain', 'in': 'query', 'required': True, 'schema': {'type': 'string'},
                          'examples': {'default': {'value': value}}}]}
    if sample:
        op['x-codeSamples'] = [{'lang': 'text', 'label': 'Reference example',
                                'source': HEADER + "curl --request GET \\\n  --url 'https://api.aisa.one" + path + '?domain=' + value + "'"}]
    scenario = {'body': None, 'parameters': {'query:domain': value}}
    if verified is not None:
        op['x-aisa-example'] = ({'state': 'verified', 'id': 'widgets.search#1', 'sha256': example_sha256(scenario)}
                                if verified else {'state': 'pending', 'reason': 'no_evidence'})
    op.update(extra or {})
    return op


class Tree:
    """A minimal Docs checkout: aggregate, llms, one catalog, one page."""

    def __init__(self, root, ops=None, *, release_ops=None, llms_hash=None, page_extra=''):
        self.root = Path(root)
        ops = ops if ops is not None else {'/apis/v1/widgets/search': {'get': operation()}}
        catalog = {'openapi': '3.1.0', 'info': {'title': 'Widgets'}, 'paths': ops}
        (self.root / 'openapi/zh').mkdir(parents=True)
        (self.root / 'openapi/widgets.json').write_text(json.dumps(catalog))
        aggregate = {'openapi': '3.1.0', 'paths': {p: {m: {'operationId': o['operationId']} for m, o in item.items()}
                                                   for p, item in ops.items()}}
        aggregate['paths']['/v1/models'] = {'get': {'operationId': 'models'}}
        (self.root / 'openapi/openapi.json').write_text(json.dumps(aggregate))
        (self.root / 'openapi.yaml').write_text(json.dumps(aggregate))  # JSON is valid YAML
        digest = hashlib.sha256((self.root / 'openapi.yaml').read_bytes()).hexdigest()
        (self.root / 'llms.txt').write_text(f'Declared API contract (OpenAPI YAML SHA-256): {llms_hash or digest}.\n')
        (self.root / 'docs.json').write_text(json.dumps({'navigation': [{'group': 'Widgets'}]}))
        page = self.root / 'api-reference/widgets/widgets-search.mdx'
        page.parent.mkdir(parents=True)
        page.write_text('---\ntitle: "Search widgets"\nopenapi: "openapi/widgets.json GET /apis/v1/widgets/search"\n---\n\nSearch widgets.\n' + page_extra)
        self.facts = self.root / 'facts'
        (self.facts / 'contracts').mkdir(parents=True)
        release = copy.deepcopy(aggregate) if release_ops is None else release_ops
        (self.facts / 'contracts/openapi.json').write_text(json.dumps(release))
        self.scope = self.root / 'scope.json'
        self.scope.write_text(json.dumps({'schema_version': 1, 'operations': ['GET /apis/v1/widgets/search']}))
        self.exclusions = self.root / 'exclusions.json'
        self.exclusions.write_text(json.dumps({'schema_version': 1, 'docs_only': [], 'release_only': []}))
        self.drift = self.root / 'drift.json'
        self.drift.write_text(json.dumps({'schema_version': 1, 'operations': []}))
        self.projection = self.root / 'projection.json'
        self.projection.write_text(json.dumps({'schema_version': 1, 'catalogs': ['widgets']}))
        public_projection.write(self.root, ['widgets'])

    def run(self, environ=None, **kwargs):
        options = dict(facts_dir=self.facts, scope_path=self.scope, exclusions_path=self.exclusions,
                       drift_path=self.drift, projection_path=self.projection, environ={'SUPPLIER_VOCAB_JSON': TERMS, **(environ or {})},
                       yaml_loader=lambda path: json.loads(Path(path).read_text()))
        options.update(kwargs)
        return release_gate.run(self.root, **options)


class ReleaseGateTests(unittest.TestCase):
    def tree(self, *args, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Tree(directory.name, *args, **kwargs)

    def test_clean_verified_publication_passes(self):
        report = self.tree().run()
        self.assertEqual(report['status'], 'passed', json.dumps(report['gates'], indent=1))
        self.assertEqual(report['gates']['G4']['pending_total'], 0)
        self.assertTrue(report['enforced'])

    def test_g6_invalid_declaration_blocks_the_combined_release_gate(self):
        tree = self.tree()
        # A separate catalog outside the three-line evidence scope must still
        # obey the pagination/latency structure it declares.
        path = tree.root / 'openapi/other.json'
        document = {'paths': {'/apis/v1/other': {'get': {
            'operationId': 'other', 'x-aisa-latency': {'timeout_seconds': -1}}}}}
        path.write_text(json.dumps(document))
        report = tree.run()
        self.assertEqual(report['gates']['G6']['status'], 'failed')
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['enforced'])
        self.assertEqual(report['gates']['G6']['findings'][0]['code'], 'latency_timeout_invalid')
        self.assertEqual(report['gates']['G6']['findings'][0]['location'], 'openapi/other.json')
        self.assertEqual(report['gates']['G6']['declarations'], {'pagination': 0, 'latency': 1})
        rollback = tree.run(environ={'RELEASE_GATE_ENFORCE': 'false'})
        self.assertEqual(rollback['status'], 'failed')
        self.assertFalse(rollback['enforced'])
        # Removing an unsupported declaration is different from inventing one.
        del document['paths']['/apis/v1/other']['get']['x-aisa-latency']
        path.write_text(json.dumps(document))
        empty = tree.run()
        self.assertEqual(empty['status'], 'passed')
        self.assertEqual(empty['gates']['G6']['declarations'], {'pagination': 0, 'latency': 0})

    def test_g1_yaml_json_llms_and_operation_set(self):
        tree = self.tree(llms_hash='0' * 64)
        report = tree.run()
        self.assertEqual(report['gates']['G1']['status'], 'failed')
        self.assertIn('llms.txt does not declare exactly sha256(openapi.yaml)', report['gates']['G1']['errors'])
        tree = self.tree(release_ops={'openapi': '3.1.0', 'paths': {}})
        g1 = tree.run()['gates']['G1']
        self.assertEqual(g1['checks']['operation_set']['docs_only'], [['GET', '/apis/v1/widgets/search', 'widgets.search']])
        # A reviewed exclusion closes the difference; code-owned model routes never count.
        tree.exclusions.write_text(json.dumps({'schema_version': 1, 'release_only': [],
            'docs_only': [{'operation': ['GET', '/apis/v1/widgets/search', 'widgets.search'], 'reason': 'test'}]}))
        self.assertEqual(tree.run()['gates']['G1']['status'], 'passed')
        tree = self.tree()
        g1 = tree.run(yaml_loader=lambda path: {'different': True})['gates']['G1']
        self.assertIn('openapi.yaml and openapi/openapi.json differ', g1['errors'])
        self.assertEqual(self.tree().run(facts_dir=None)['gates']['G1']['status'], 'failed')

    def test_g2_injected_vocabulary_blocks_without_echoing_words(self):
        # Spec acceptance case 8: price dial note, supplier-hosted wording, supplier host name.
        for description in ('THIS IS THE PRICE DIAL', 'An AcmeFeeds-hosted asset', 'Served by api.zeta-gateway.dev'):
            with self.subTest(description=description):
                op = operation(extra={'description': description})
                report = self.tree({'/apis/v1/widgets/search': {'get': op}}).run()
                self.assertEqual(report['gates']['G2']['status'], 'failed')
                self.assertNotIn('acmefeeds', json.dumps(report).lower())
                self.assertNotIn('zeta-gateway', json.dumps(report).lower())
        report = self.tree(page_extra='Data from AcmeFeeds.\n').run()
        self.assertEqual(report['gates']['G2']['findings'][0]['location'], 'api-reference/widgets/widgets-search.mdx:7')

    def test_g2_without_secret_runs_public_rules(self):
        op = operation(extra={'description': 'An AcmeFeeds-hosted asset'})
        report = self.tree({'/apis/v1/widgets/search': {'get': op}}).run(environ={'SUPPLIER_VOCAB_JSON': ''})
        self.assertEqual(report['gates']['G2']['status'], 'passed')
        self.assertEqual(report['gates']['G2']['supplier_terms'], 0)

    def test_g3_placeholders_and_provenance(self):
        for value in ('example', 'hello@example.com', 'https://linkedin.com/in/example', 'YOUR_API_KEY'):
            with self.subTest(value=value):
                report = self.tree({'/apis/v1/widgets/search': {'get': operation(value=value)}}).run()
                self.assertEqual(report['gates']['G3']['status'], 'failed')
        report = self.tree(page_extra='"x-aisa-source": {"url": "https://x"}\n').run()
        self.assertEqual(report['gates']['G3']['provenance'][0]['rule'], 'PV01')
        # The fixed header comment ("reference example") is not a placeholder.
        self.assertEqual(self.tree().run()['gates']['G3']['placeholders'], [])

    def test_g3_checks_a_published_projection(self):
        tree = self.tree()
        (tree.root / 'openapi-public/widgets.json').write_text(json.dumps({'x-aisa-source': {}}))
        g3 = tree.run()['gates']['G3']
        self.assertEqual((g3['status'], g3['public_projection']), ('failed', 'checked'))
        self.assertIn('PV02', {row['rule'] for row in g3['provenance']})

    def test_g3_projection_must_cover_scope_and_be_current(self):
        tree = self.tree()
        g3 = tree.run()['gates']['G3']
        self.assertEqual((g3['status'], g3['provenance']), ('passed', []))
        # An in-scope catalog outside the reviewed list blocks the release.
        tree.projection.write_text(json.dumps({'schema_version': 1, 'catalogs': []}))
        rules = {(row['rule'], row.get('problem')) for row in tree.run()['gates']['G3']['provenance']}
        self.assertIn(('PV04', 'in_scope_catalog_not_projected'), rules)
        self.assertIn(('PV03', 'unexpected'), rules)
        tree.projection.write_text(json.dumps({'schema_version': 1, 'catalogs': ['widgets']}))
        # A formal catalog change without a fresh projection is stale.
        catalog = json.loads((tree.root / 'openapi/widgets.json').read_text())
        catalog['paths']['/apis/v1/widgets/search']['get']['summary'] = 'Changed'
        (tree.root / 'openapi/widgets.json').write_text(json.dumps(catalog))
        g3 = tree.run()['gates']['G3']
        self.assertEqual(g3['provenance'], [{'location': 'openapi-public/widgets.json', 'rule': 'PV03', 'problem': 'stale'}])
        public_projection.write(tree.root, ['widgets'])
        self.assertEqual(tree.run()['gates']['G3']['status'], 'passed')
        (tree.root / 'openapi-public/widgets.json').unlink()
        self.assertEqual(tree.run()['gates']['G3']['provenance'][0]['problem'], 'missing')

    def test_g4_example_without_verified_evidence_blocks(self):
        for op, reason in [(operation(verified=False), 'reference_example_without_verified_evidence'),
                           (operation(verified=None), 'reference_example_without_verified_evidence')]:
            with self.subTest(reason=reason):
                g4 = self.tree({'/apis/v1/widgets/search': {'get': op}}).run()['gates']['G4']
                self.assertEqual((g4['status'], g4['violations'][0]['reason']), ('failed', reason))
        op = operation()
        op['parameters'][0]['examples']['default']['value'] = 'other.com'  # sample no longer the verified one
        g4 = self.tree({'/apis/v1/widgets/search': {'get': op}}).run()['gates']['G4']
        self.assertEqual(g4['violations'][0]['reason'], 'example_sha256_mismatch')

    def test_g4_missing_examples_are_pending_not_blocking(self):
        ops = {'/apis/v1/widgets/search': {'get': operation(verified=False, sample=False,
                                                           extra={'x-aisa-verification': {'state': 'pending', 'reason': 'no_fixture'}})},
               '/apis/v1/widgets/list': {'get': {'operationId': 'widgets.list',
                                                 'x-aisa-example': {'state': 'pending', 'reason': 'no_fixture'}}}}
        tree = self.tree(ops)
        report = tree.run()
        self.assertEqual(report['gates']['G4']['status'], 'passed')
        self.assertEqual(report['gates']['G4']['pending_reasons'], {'inputs_undeclared': 1, 'no_fixture': 1})
        tree.drift.write_text(json.dumps({'schema_version': 1, 'operations': [
            {'operation_id': 'widgets.list', 'kind': 'required_added', 'field': 'company'}]}))
        reasons = {row['operation_id']: row['reason'] for row in tree.run()['gates']['G4']['pending']}
        self.assertEqual(reasons['widgets.list'], 'upstream_drift')

    def test_scope_is_marked_operations_plus_inventory(self):
        unscoped = operation('/apis/v1/other/thing', verified=None)
        unscoped.pop('x-aisa-example', None)
        ops = {'/apis/v1/widgets/search': {'get': operation()}, '/apis/v1/other/thing': {'get': unscoped}}
        g4 = self.tree(ops).run()['gates']['G4']
        self.assertEqual((g4['status'], g4['scope_operations']), ('passed', 1))

    def test_cli_exit_codes_and_rollback_switch(self):
        tree = self.tree({'/apis/v1/widgets/search': {'get': operation(verified=False)}})
        args = ['--root', str(tree.root), '--facts-dir', str(tree.facts), '--scope', str(tree.scope),
                '--exclusions', str(tree.exclusions), '--drift', str(tree.drift), '--projection', str(tree.projection),
                '--report', str(tree.root / 'gate.json')]
        with mock.patch.object(release_gate, 'load_yaml', lambda path: json.loads(Path(path).read_text())), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.dict('os.environ', {'RELEASE_GATE_ENFORCE': ''}):
                self.assertEqual(release_gate.main(args), 1)
            with mock.patch.dict('os.environ', {'RELEASE_GATE_ENFORCE': 'false'}):
                self.assertEqual(release_gate.main(args), 0)
        report = json.loads((tree.root / 'gate.json').read_text())
        self.assertEqual((report['status'], report['enforced']), ('failed', False))


if __name__ == '__main__':
    unittest.main()
