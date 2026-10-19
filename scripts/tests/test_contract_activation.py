import copy
from datetime import datetime, timedelta, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_activation import deadline, select_revision, validate_config
from check_contract_revisions import main
import test_contract_revisions

SCRIPTS = Path(__file__).resolve().parents[1]


class ActivationTests(unittest.TestCase):
    def test_two_semantic_rounds_and_lost_dispatch_use_actual_all_surface_gates(self):
        """Isolated monitor integration, not attributed publication or deployment.

        Every registry provider participates; expected Git and observed HTTP
        bytes are separate. Only the formal authorization boundary is mocked.
        No checker is replaced with a pre-assessed pass.
        """
        from public_surface_checks import (DISCOVERY_PAGE, JSON_SURFACES, MCP_PAGE, MCP_SERVERS, SALES_CATALOG,
                                           SOFT_404_TITLE, TEXT_SURFACES)
        from router_surface_checks import METADATA, canonical, digest
        providers = sorted(yaml.safe_load((SCRIPTS.parent / 'openapi/registry.yaml').read_text())['providers'])
        began = datetime.now(timezone.utc) - timedelta(minutes=15)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
            git('init', '-q'); git('config', 'user.name', 'Ken'); git('config', 'user.email', 'ken@aisa.one')
            registry = {'providers': {p: {} for p in providers}}
            current = {}
            def make_round(number):
                documents, metadata, pages, rows, hashes = {}, {}, {}, {}, {}
                for provider in providers:
                    oid = 'get_' + provider
                    path = '/apis/v1/' + provider
                    method = 'post' if number == 2 else 'get'
                    parameter = {'name': 'q', 'in': 'query', 'required': number > 0,
                                 'schema': {'type': 'string', 'minLength': number}}
                    operation = {'operationId': oid, 'parameters': [parameter],
                        'requestBody': {'content': {'application/json': {'schema': {
                            'type': 'object', 'properties': {'value': {'type': 'integer', 'minimum': number}}}}}},
                        'responses': {'200': {'description': 'OK'}},
                        'x-aisa-pricing': {'amount': number + .0123, 'billing_mode': 'usage' if number == 2 else 'fixed'},
                        'security': [] if number < 2 else [{'Bearer': []}]}
                    meta = {'document_hash': digest(operation), 'facts_hash': 'facts-' + str(number)}
                    metadata[provider] = meta
                    document = {'openapi': '3.1.0', 'info': {'x-aisa-document': meta},
                        'servers': [{'url': 'https://api.aisa.one'}],
                        'components': {'securitySchemes': {'Bearer': {'type': 'http', 'scheme': 'bearer'}}},
                        'paths': {path: {method: operation}}}
                    documents[provider] = document
                    raw = canonical(document); hashes['openapi/' + provider + '.json'] = hashlib.sha256(raw).hexdigest()
                    request = {**operation, 'method': method.upper(), 'path': path}
                    price = 'Published price round ' + str(number)
                    page = '## Request contract\n\n```json\n' + json.dumps(request) + '\n```\n\n## Cost and request rules\n\n' + price + '\n'
                    for prefix in ('', 'zh/'):
                        pages[prefix + 'api-reference/' + provider + '.mdx'] = page
                    rows[oid] = {'successful': True, 'documentation': {'openapi': copy.deepcopy(document),
                        'provenance': {'source_file': 'openapi/' + provider + '.json',
                                       'source_hash': 'sha256:' + hashes['openapi/' + provider + '.json'],
                                       'document_hash': meta['document_hash']}},
                        'arguments_schema': {'type': 'object', 'additionalProperties': False,
                            'properties': {'q': parameter['schema'], 'value': {'type': 'integer', 'minimum': number}},
                            **({'required': ['q']} if number else {})}}
                aggregate = {'openapi': '3.1.0', 'info': {'x-aisa-document': {'providers': metadata}},
                    'paths': {path: item for document in documents.values() for path, item in document['paths'].items()}}
                sales_view = {'openapi': '3.1.0', 'paths': {path: {method: {'operationId': op['operationId'],
                    'x-aisa-registry-provider': path.rsplit('/', 1)[1]} for method, op in item.items()}
                    for path, item in aggregate['paths'].items()}}
                files = {'openapi.yaml': yaml.safe_dump(aggregate).encode(),
                    'openapi/registry.yaml': yaml.safe_dump(registry).encode(),
                    'discovery/openapi.json': canonical(aggregate),
                    'docs/publication/sales-catalog.json': canonical({'schema_version': 1, 'document': sales_view}),
                    **{'openapi/' + p + '.json': canonical(d) for p, d in documents.items()},
                    **{p: text.encode() for p, text in pages.items()}}
                for path, raw in files.items():
                    target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
                pointer = root / 'docs/publication/current.json'; pointer.parent.mkdir(parents=True, exist_ok=True)
                release = hashlib.sha256(b'release-' + str(number).encode()).hexdigest()
                pointer.write_bytes(canonical({'status': 'passed', 'contract_release': release,
                    'sales_catalog': {'path': 'docs/publication/sales-catalog.json',
                                      'sha256': hashlib.sha256(files['docs/publication/sales-catalog.json']).hexdigest()},
                    'files_sha256': {p: hashlib.sha256(raw).hexdigest() for p, raw in files.items()}}))
                git('add', 'openapi.yaml', 'openapi', 'discovery', 'api-reference', 'zh', 'docs'); git('commit', '-qm', 'isolated semantic round ' + str(number))
                ref = git('rev-parse', 'HEAD'); sha = hashlib.sha256(files['openapi.yaml']).hexdigest()
                for row in rows.values(): row['documentation']['provenance']['docs_sha'] = ref
                mcp = {'state': 'loaded', 'docsRefs': [ref], 'documentHashes': {p: m['document_hash'] for p, m in metadata.items()},
                    'sourceHashes': {p: {p + '.json': 'sha256:' + hashes['openapi/' + p + '.json']} for p in providers}}
                payloads = {url: canonical(aggregate) for url in JSON_SURFACES.values()}
                payloads.update({'https://api.aisa.one/openapi.json': files['discovery/openapi.json'],
                    'https://aisa.one/openapi.yaml': files['openapi.yaml'],
                    'https://mcp.aisa.one/contract-version': canonical(mcp),
                    TEXT_SURFACES['website-llms']: (sha + ' ' + ref + ' https://aisa.one/openapi.json https://raw.githubusercontent.com/AIsa-team/docs/' + ref + '/openapi.yaml').encode(),
                    TEXT_SURFACES['docs-llms']: (sha + ' openapi.json').encode(),
                    TEXT_SURFACES['mcp-llms']: ref.encode(),
                    TEXT_SURFACES['docs-llms-full']: ''.join(pages[p] for p in pages if not p.startswith('zh/')).encode(),
                    SALES_CATALOG: canonical({'docs_revision': ref, 'contract_release': release,
                        'providers': [{'id': p, 'endpoint_count': 1} for p in providers],
                        'operations': [{'operation_id': 'get_' + p, 'provider': p, 'quote': {'amount': str(number + .0123)}} for p in providers]}),
                    MCP_SERVERS: canonical({'serverCount': len(providers), 'toolCount': len(providers),
                        'entrypoints': [{'slug': 'aisa', 'kind': 'root'}, {'slug': 'seo', 'kind': 'category'}]}),
                    MCP_PAGE: ('<title>MCP</title><p>' + str(len(providers)) + ' servers; ' + str(len(providers)) +
                        ' tools reachable; 1 categories; $' + str(number + .0123) + ' ' + providers[0] + '</p>').encode(),
                    DISCOVERY_PAGE: b'# Agent Discovery\n[agent setup guide](https://aisa.one/llms.txt) '
                        b'https://mcp.aisa.one/mcp OAuth; direct HTTP is the fallback.\n'})
                for path, page in pages.items():
                    request = json.loads(page.split('```json\n')[1].split('\n```')[0])
                    payloads['https://aisa.one/docs/' + path.removesuffix('.mdx')] = (
                        '<h2>Request contract</h2><pre><code>' + html.escape(json.dumps(request)) +
                        '</code></pre><h2>Cost and request rules</h2><p>Published price round ' + str(number) + '</p>').encode()
                return {'ref': ref, 'sha': sha, 'payloads': payloads, 'rows': rows,
                    'runtime': {'providers': [{'id': p, 'facts_hash': m['facts_hash']} for p, m in metadata.items()]},
                    'router': {'docs_commit': ref, 'build_id': 'round-' + str(number),
                               'provider_document_hashes': {p: m['document_hash'] for p, m in metadata.items()}}}
            def run(selected):
                selection = root / 'selection.json'
                selection.write_text(json.dumps({'selection': select_revision('schedule', selected['ref'], selected['sha'])}))
                argv = ['monitor', '--root', str(root), '--all-surfaces', '--all-doc-pages', '--require-budget',
                    '--expected-docs-ref', selected['ref'], '--selection-file', str(selection),
                    '--budget-start', began.isoformat(), '--state', str(root/'state.json'), '--report', str(root/'report.json')]
                def read(url):
                    if url.endswith('/info/openapi.json'): return current['runtime']
                    if url == METADATA: return current['router']
                    return {'mode': 'formal', 'docsRevision': current['ref'], 'contentHash': current['sha']}
                def schema_read(_, method, url, payload=None):
                    return current['router'] if url == METADATA else {'tools': {oid: current['rows'][oid] for oid in payload['tools']}}
                def read_page(url):
                    if url in current['payloads']:
                        return 200, current['payloads'][url]
                    slug = url.rsplit('/', 1)[1]
                    if slug in providers:
                        return 200, ('<title>' + slug + ' API - AIsa</title>').encode()
                    return 404, ('<title>' + SOFT_404_TITLE + ' - AIsa</title>').encode()
                with patch.object(sys, 'argv', argv), patch('builtins.print'), \
                    patch('check_contract_revisions.read_public', side_effect=read), \
                    patch('check_contract_revisions.read_public_page', side_effect=read_page), \
                    patch('check_contract_revisions.read_public_bytes', side_effect=lambda url: current['payloads'][url]), \
                    patch('check_contract_revisions.urlopen', side_effect=lambda request, **kw: io.BytesIO(current['payloads'][request.full_url])), \
                    patch('router_surface_checks.PublicSchemaReader.__call__', new=schema_read), \
                    patch('publication_origin.verify_consumer_refs', return_value={'status': 'passed',
                        'expected_docs_ref': selected['ref'], 'contract_release': selected['sha'],
                        'clock_docs_ref': selected['ref'], 'publications': {selected['ref']: {}}}):
                    code = main()
                return code, json.loads((root/'report.json').read_text())
            current.update(make_round(0))
            self.assertEqual(run(current)[1]['status'], 'passed')
            for number in (1, 2):
                selected = make_round(number)
                # Omitted dispatch leaves all actual consumer bytes at last-good.
                _, stale = run(selected)
                self.assertNotEqual(stale['status'], 'passed')
                self.assertTrue(stale['mismatches'])
                self.assertEqual(current['router']['build_id'], 'round-' + str(number - 1))
                current.update(selected)  # Existing scheduled consumer recovery.
                code, recovered = run(selected)
                self.assertEqual((code, recovered['status']), (0, 'passed'))
                self.assertEqual(recovered['router_schemas']['verified_operations'], len(providers))
                self.assertEqual(recovered['timing']['budget_start'], began.isoformat())
                history = json.loads((root/'state.json').read_text())['publication_history']
                self.assertTrue(any((row['identity'].get('contract_release') == selected['sha'] or
                    row['identity'].get('docs_ref') == selected['ref']) and
                    row['assessment']['status'] != 'passed' for row in history))

    def test_ready_plan_and_workflow_double_gate_have_frozen_cadence(self):
        config = json.loads((SCRIPTS / 'contract_activation.json').read_text())
        self.assertTrue(validate_config(config)['activation_enabled'])
        for change in ({'candidate_interval_seconds': 601}, {'candidate_budget_seconds': 3601},
                       {'consumer_budget_seconds': 14401}, {'monitor_interval_seconds': 3601},
                       {'version_cache_max_seconds': 301}, {'activation_enabled': 'true'}):
            with self.assertRaises(ValueError):
                validate_config(dict(config, **change))
        workflows = SCRIPTS.parent / '.github/workflows'
        for name, cron in [('pull-openapi.yml', '*/10 * * * *'), ('check-contract-revisions.yml', '35 * * * *')]:
            text = (workflows / name).read_text()
            self.assertIn("cron: '" + cron + "'", text)
            self.assertIn("needs.activation-plan.outputs.enabled == 'true' && vars.RUNTIME_CONTRACT_ACTIVATION_ENABLED == 'true'", text)
            parsed = yaml.safe_load(text)
            plan = parsed['jobs']['activation-plan']
            self.assertTrue(all('pull_openapi' not in step.get('run', '') and 'read_public' not in step.get('run', '')
                                for step in plan['steps']))
        self.assertIn('default: false', (workflows / 'pull-openapi.yml').read_text())

    def test_deadline_is_frozen_and_not_reset_on_first_or_recovered_observation(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        for phase, cap in [('candidate', 3600), ('convergence', 14400)]:
            self.assertFalse(deadline((now-timedelta(seconds=cap)).isoformat(), phase, now)['deadline_breached'])
            self.assertTrue(deadline((now-timedelta(seconds=cap+1)).isoformat(), phase, now)['deadline_breached'])
        for start in ('2026-01-02', '2027-01-01T00:00:00Z'):
            with self.assertRaises(ValueError):
                deadline(start, 'convergence', now)

    def test_active_unknown_budget_exits_before_any_fetch(self):
        with patch.object(sys, 'argv', ['monitor', '--require-budget']), \
                patch('check_contract_revisions.read_public', side_effect=AssertionError('network')), patch('builtins.print'):
                    self.assertEqual(main(), 3)

    def test_actual_monitor_retains_only_same_release_on_time_observation(self):
        documents, *values = test_contract_revisions.RevisionTests().fixture()
        surfaces = dict(zip(('runtime', 'website', 'router'), values))
        began = datetime(2026, 1, 2, tzinfo=timezone.utc)
        early = began + timedelta(hours=1)
        late = began + timedelta(seconds=14401)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'openapi.yaml'
            original = yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}})
            source.write_text(original)
            state = root / 'state.json'; report = root / 'report.json'
            urls = dict(zip(('https://api.aisa.one/info/openapi.json', 'https://aisa.one/openapi.yaml',
                'https://tools.aisa.one/.well-known/catalog.json'), surfaces.values()))
            urls['https://aisa.one/api/contracts/version'] = {'mode': 'formal', 'docsRevision': 'a' * 40,
                'contentHash': hashlib.sha256(original.encode()).hexdigest()}
            def run(now, start=began, expected='a'*40, acceptance=False):
                argv = ['monitor', '--root', str(root), '--state', str(state), '--report', str(report),
                        '--require-budget', '--expected-docs-ref', expected, '--budget-start', start.isoformat()]
                if acceptance: argv.append('--acceptance')
                with patch.object(sys, 'argv', argv), patch('contract_activation.datetime', wraps=datetime) as clock, \
                        patch('check_contract_revisions.time.time', return_value=now.timestamp()), \
                        patch('check_contract_revisions.read_public', side_effect=lambda url: urls[url]), \
                        patch('check_contract_revisions.read_public_bytes', side_effect=lambda url: source.read_bytes()), \
                        patch('publication_origin.verify_consumer_refs', side_effect=lambda root, expected, refs, budget: {
                            'status': 'passed', 'expected_docs_ref': expected, 'contract_release': expected + '0' * 24,
                            'clock_docs_ref': expected, 'budget_start': budget, 'publications': {expected: {}}}), \
                        patch('builtins.print'):
                    clock.now.return_value = now
                    status = main()
                return status, json.loads(report.read_text())
            first, healthy = run(early)
            self.assertEqual((first, healthy['status']), (0, 'passed'))
            saved = state.read_text()
            again, healthy = run(late)
            self.assertEqual((again, healthy['status']), (0, 'passed'))
            self.assertEqual(healthy['timing']['elapsed_seconds'], 3600)
            self.assertEqual(healthy['timing']['current_elapsed_seconds'], 14401)
            self.assertEqual(json.loads(state.read_text())['convergence_observation'], json.loads(saved)['convergence_observation'])
            # Strict acceptance cannot turn a cached monitor observation into
            # a current dated release acceptance or mutate that cache.
            before = state.read_text()
            strict, failed = run(late, acceptance=True)
            self.assertEqual((strict, failed['status']), (1, 'failed'))
            self.assertEqual(state.read_text(), before)
            for changed in ('no_prior_pass', 'version', 'source_bytes', 'budget_start', 'late_drift'):
                with self.subTest(changed=changed):
                    state.write_text('{}' if changed == 'no_prior_pass' else saved)
                    expected = 'a'*40
                    start = began
                    source.write_text(original)
                    surfaces['router']['docs_commit'] = expected
                    surfaces['router']['provider_document_hashes']['alpha'] = 'doc'
                    if changed == 'version':
                        expected = 'b'*40
                        surfaces['router']['docs_commit'] = expected
                    elif changed == 'source_bytes':
                        source.write_text(original + '# distinct fixed aggregate bytes\n')
                    elif changed == 'budget_start':
                        start -= timedelta(seconds=1)
                    elif changed == 'late_drift':
                        surfaces['router']['provider_document_hashes']['alpha'] = 'different'
                    status, failed = run(late, start, expected)
                    self.assertEqual((status, failed['status']), (1, 'failed'))
                    self.assertIn('timing:deadline_breached', failed['mismatches'])
                    if changed == 'late_drift':
                        self.assertIn('alpha:tool-router:document_hash_mismatch', failed['mismatches'])
        for start in ('unparseable', '2026-01-02', '2099-01-01T00:00:00Z'):
            with patch.object(sys, 'argv', ['monitor', '--require-budget', '--expected-docs-ref', 'a'*40,
                                           '--budget-start', start]), \
                    patch('check_contract_revisions.read_public', side_effect=AssertionError('network')), patch('builtins.print'):
                self.assertEqual(main(), 3)

    def test_real_monitor_entry_selects_missed_dispatch_source_then_recovers_without_deadline_reset(self):
        # Actual selector CLI -> actual monitor CLI -> immutable Git source.
        # Public metadata and the independent provenance gate are mocked here;
        # publication_origin tests exercise the actual producer and full graph.
        # No attributed receipts are minted by this monitor recovery test.
        documents, *values = test_contract_revisions.RevisionTests().fixture()
        surfaces = dict(zip(('runtime', 'website', 'router'), values))
        start = datetime.now(timezone.utc) - timedelta(minutes=10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
            git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'fixture@example.invalid')
            (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
            git('add', '.'); git('commit', '-qm', 'previous publication')
            old = git('rev-parse', 'HEAD')
            documents['alpha']['document_hash'] = 'newdoc'
            raw = yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}).encode()
            (root / 'openapi.yaml').write_bytes(raw)
            git('add', '.'); git('commit', '-qm', 'independently selected fixed source')
            expected = git('rev-parse', 'HEAD'); digest = hashlib.sha256(raw).hexdigest()
            # One dispatch omitted: old consumer still reports old source.
            selection_file = root / 'selection.json'
            selection_file.write_bytes(subprocess.check_output([sys.executable, str(SCRIPTS / 'contract_activation.py'),
                '--event', 'schedule', '--published-ref', expected, '--published-hash', digest]))
            selection = json.loads(selection_file.read_text())['selection']
            self.assertEqual(selection['docs_ref'], expected)
            self.assertFalse(selection['publication_verified'])
            surfaces['router']['docs_commit'] = old
            urls = dict(zip(('https://api.aisa.one/info/openapi.json', 'https://aisa.one/openapi.yaml',
                'https://tools.aisa.one/.well-known/catalog.json'), surfaces.values()))
            urls['https://aisa.one/api/contracts/version'] = {'mode': 'formal', 'docsRevision': expected,
                'contentHash': digest}
            report = root / 'report.json'
            def run(began):
                argv = ['monitor', '--root', str(root), '--state', str(root/'state.json'), '--require-budget',
                        '--expected-docs-ref', expected, '--selection-file', str(selection_file),
                        '--budget-start', began.isoformat(), '--report', str(report)]
                with patch.object(sys, 'argv', argv), patch('check_contract_revisions.read_public', side_effect=lambda url: urls[url]), \
                        patch('check_contract_revisions.read_public_bytes', side_effect=lambda url: yaml.safe_dump(
                            {'info': {'x-aisa-document': {'providers': {name: dict(meta, **surfaces['website']['x-aisa-document']['providers'].get(name, {})) for name, meta in documents.items()}}}}).encode()), \
                        patch('publication_origin.verify_consumer_refs', side_effect=lambda root, expected, refs, budget: {
                            'status': 'passed', 'expected_docs_ref': expected, 'contract_release': expected + '0' * 24,
                            'clock_docs_ref': expected, 'budget_start': budget, 'publications': {expected: {}}}), \
                        patch('builtins.print'):
                    return main(), json.loads(report.read_text())
            status, failed = run(start)
            self.assertEqual(failed['status'], 'not_assessed')
            self.assertIn('website:unavailable:ValueError', failed['missing_inputs'])
            surfaces['website']['x-aisa-document']['providers']['alpha']['document_hash'] = 'newdoc'
            surfaces['router'].update(docs_commit=expected, provider_document_hashes={'alpha': 'newdoc'})
            status, recovered = run(start)
            self.assertEqual((status, recovered['status']), (0, 'passed'))
            self.assertEqual(recovered['timing']['budget_start'], start.isoformat())
            status, overdue = run(datetime.now(timezone.utc)-timedelta(seconds=14401))
            self.assertEqual((status, overdue['status']), (1, 'failed'))
            self.assertEqual(json.loads((root/'state.json').read_text())['consecutive']['timing:deadline_breached'], 1)
            selection['openapi_sha256'] = '0'*64
            selection_file.write_text(json.dumps({'selection': selection}))
            with self.assertRaisesRegex(ValueError, 'source bytes'):
                run(start)


if __name__ == '__main__':
    unittest.main()
