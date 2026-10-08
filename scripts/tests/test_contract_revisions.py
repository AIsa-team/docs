import sys
import unittest
import yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_contract_revisions import assess, compare, main, update_state

class RevisionTests(unittest.TestCase):
    def assess(self, *values, **kwargs):
        kwargs.setdefault('website_version', {'mode': 'formal', 'docsRevision': 'a' * 40, 'contentHash': 'd' * 64})
        kwargs.setdefault('expected_openapi_sha256', 'd' * 64)
        return assess(*values, **kwargs)

    def write_website_version(self, root):
        import hashlib
        import json
        (root / 'website-version.json').write_text(json.dumps({'mode': 'formal', 'docsRevision': 'a' * 40,
            'contentHash': hashlib.sha256((root / 'openapi.yaml').read_bytes()).hexdigest()}))

    def test_grouped_facts_and_consumers_use_per_provider_hashes(self):
        documents = {'group': {'document_hash': 'document', 'catalogs': {'a': {'x-aisa-document': {'facts_hash': 'facts'}}}}, 'legacy': {}}
        runtime = {'providers': [{'id': 'a', 'facts_hash': 'facts'}]}
        website = {'x-aisa-document': {'providers': {'group': {'document_hash': 'document'}}}}
        mcp = {'documentHashes': {'group': 'document'}}
        router = {'provider_document_hashes': {'group': 'document'}}
        self.assertEqual(compare(documents, runtime, website, mcp, router), [])
        runtime['providers'][0]['facts_hash'] = 'changed'
        self.assertEqual(compare(documents, runtime, website, mcp, router), ['group:a:facts_hash_mismatch'])
    def test_only_consecutive_failures_escalate(self):
        first = update_state(['a'], {})
        self.assertEqual(first['consecutive'], {'a': 1})
        self.assertEqual(update_state(['a'], first)['consecutive'], {'a': 2})
        self.assertEqual(update_state([], first)['consecutive'], {})

    def fixture(self):
        return ({'alpha': {'document_hash': 'doc', 'facts_hash': 'facts'}, 'legacy': {}},
                {'providers': [{'id': 'alpha', 'facts_hash': 'facts'}]},
                {'x-aisa-document': {'providers': {'alpha': {'document_hash': 'doc'}}}},
                {'documentHashes': {'alpha': 'doc'}, 'docsRefs': ['a' * 40]},
                {'provider_document_hashes': {'alpha': 'doc'}, 'docs_commit': 'a' * 40})

    def test_empty_legacy_catalog_cannot_pass_acceptance(self):
        result = assess({'legacy': {}}, {}, {}, {}, {})
        self.assertEqual(result['status'], 'not_assessed')
        self.assertEqual(result['verified_providers'], 0)
        self.assertIn('docs:no_runtime_composed_provider_metadata', result['missing_inputs'])

    def test_matching_hashes_and_locked_revisions_pass(self):
        result = self.assess(*self.fixture(), expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['scope'], 'public_contract_convergence')
        self.assertGreater(result['checked_at'], 0)

    def test_matching_provider_hashes_cannot_hide_wrong_website_source(self):
        for field, replacement, expected in [
                ('docsRevision', 'b' * 40, 'website:docs_revision_mismatch'),
                ('contentHash', 'e' * 64, 'website:aggregate_content_hash_mismatch'),
                ('mode', 'legacy', 'website:source_mode_not_formal')]:
            with self.subTest(field=field):
                version = {'mode': 'formal', 'docsRevision': 'a' * 40, 'contentHash': 'd' * 64}
                version[field] = replacement
                result = self.assess(*self.fixture(), expected_docs_ref='a' * 40, website_version=version)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['mismatches'], [expected])

    def test_strict_source_version_and_aggregate_hash_are_required(self):
        result = self.assess(*self.fixture(), expected_docs_ref='a' * 40, website_version=None)
        self.assertEqual(result['status'], 'not_assessed')
        self.assertIn('website:source_version_unavailable', result['missing_inputs'])
        result = self.assess(*self.fixture(), expected_docs_ref='a' * 40, expected_openapi_sha256=None)
        self.assertEqual(result['status'], 'not_assessed')
        self.assertIn('docs:aggregate_content_hash_unavailable', result['missing_inputs'])

    def test_actual_strict_cli_reads_public_website_version_before_acceptance(self):
        import hashlib
        import json
        import tempfile
        from unittest.mock import patch
        documents, *values = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}})
            (root / 'openapi.yaml').write_text(raw)
            urls = dict(zip(('https://api.aisa.one/info/openapi.json',
                'https://aisa.one/.well-known/agent-card.json',
                'https://mcp.aisa.one/.well-known/mcp.json',
                'https://tools.aisa.one/.well-known/catalog.json'), values))
            version_url = 'https://aisa.one/api/contracts/version'
            urls[version_url] = {'mode': 'formal', 'docsRevision': 'b' * 40,
                'contentHash': hashlib.sha256(raw.encode()).hexdigest()}
            with patch.object(sys, 'argv', ['monitor', '--root', str(root), '--acceptance',
                    '--expected-docs-ref', 'a' * 40, '--report', str(root / 'report.json')]), \
                    patch('check_contract_revisions.read_public', side_effect=lambda url: urls[url]) as reader, \
                    patch('builtins.print'):
                self.assertEqual(main(), 1)
            self.assertIn(version_url, [call.args[0] for call in reader.call_args_list])
            report = json.loads((root / 'report.json').read_text())
            self.assertEqual(report['mismatches'], ['website:docs_revision_mismatch'])
            self.assertEqual(report['expected_openapi_sha256'], urls[version_url]['contentHash'])

    def test_matching_hashes_do_not_hide_wrong_consumer_revision(self):
        values = list(self.fixture())
        values[3]['docsRefs'].append('b' * 40)
        values[4]['docs_commit'] = 'b' * 40
        result = self.assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], ['mcp:docs_revision_mismatch', 'tool-router:docs_revision_mismatch'])

    def test_new_runtime_catalog_cannot_be_absent_from_every_consumer(self):
        values = list(self.fixture())
        values[1]['providers'].append({'id': 'new_provider', 'facts_hash': 'newfacts'})
        result = self.assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], ['new_provider:docs:catalog_missing'])

    def test_runtime_projection_pending_is_not_deployed_acceptance(self):
        values = list(self.fixture())
        values[1]['pending_providers'] = [{'id': 'new_provider', 'endpoint_count': 1}]
        result = self.assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'not_assessed')
        self.assertIn('runtime:new_provider:projection_pending', result['missing_inputs'])

    def test_missing_surface_or_fetch_failure_is_dated_unassessed(self):
        values = list(self.fixture())
        values[2] = None
        result = assess(*values, failures=['website:unavailable:HTTPError'])
        self.assertEqual(result['status'], 'not_assessed')
        self.assertIn('website:publication_metadata_unavailable', result['missing_inputs'])
        self.assertIn('website:unavailable:HTTPError', result['missing_inputs'])

    def test_acceptance_cli_fails_first_mismatch_without_monitor_mutation(self):
        import json
        import tempfile
        from unittest.mock import patch
        import yaml
        documents, *surfaces = self.fixture()
        surfaces[3]['docs_commit'] = 'b' * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
            for name, value in zip(('runtime', 'website', 'mcp', 'router'), surfaces):
                (root / f'{name}.json').write_text(json.dumps(value))
            self.write_website_version(root)
            state = root / 'state.json'
            state.write_text('{"consecutive":{"old":1}}')
            report = root / 'report.json'
            with patch.object(sys, 'argv', ['check_contract_revisions.py', '--root', str(root),
                    '--acceptance', '--evidence-dir', str(root), '--state', str(state),
                    '--expected-docs-ref', 'a' * 40, '--report', str(report)]), patch('builtins.print'), \
                    patch('check_contract_revisions.read_public', side_effect=AssertionError('network')):
                self.assertEqual(main(), 1)
            self.assertEqual(state.read_text(), '{"consecutive":{"old":1}}')
            self.assertEqual(json.loads(report.read_text())['status'], 'failed')

    def test_acceptance_cli_cannot_silently_skip_revision_checks(self):
        from unittest.mock import patch
        with patch.object(sys, 'argv', ['check_contract_revisions.py', '--acceptance', '--expected-docs-ref', '']), \
                patch('sys.stderr'), patch('check_contract_revisions.read_public', side_effect=AssertionError('network')):
            with self.assertRaises(SystemExit) as exc:
                main()
        self.assertEqual(exc.exception.code, 2)

    def run_monitor(self, root, documents, surfaces):
        """Exercise the real scheduled CLI with only public metadata mocked."""
        import json
        from unittest.mock import patch
        import yaml
        (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
        urls = {
            'https://api.aisa.one/info/openapi.json': 'runtime',
            'https://aisa.one/.well-known/agent-card.json': 'website',
            'https://mcp.aisa.one/.well-known/mcp.json': 'mcp',
            'https://tools.aisa.one/.well-known/catalog.json': 'router',
        }
        def read_fixture(url):
            value = surfaces[urls[url]]
            if isinstance(value, Exception):
                raise value
            return value
        report = root / 'report.json'
        with patch.object(sys, 'argv', ['check_contract_revisions.py', '--root', str(root),
                '--state', str(root / 'state.json'), '--report', str(report)]), \
                patch('check_contract_revisions.read_public', side_effect=read_fixture), patch('builtins.print'):
            status = main()
        return status, json.loads(report.read_text()), json.loads((root / 'state.json').read_text())

    def test_scheduled_main_escalates_new_runtime_catalog_absent_everywhere_and_recovers(self):
        import copy
        import tempfile
        documents, *values = self.fixture()
        healthy = dict(zip(('runtime', 'website', 'mcp', 'router'), values))
        incomplete = copy.deepcopy(healthy)
        incomplete['runtime']['providers'].append({'id': 'new_provider', 'facts_hash': 'newfacts'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, assessment, state = self.run_monitor(root, documents, incomplete)
            self.assertEqual(first, 0)
            self.assertEqual(assessment['status'], 'failed')
            self.assertEqual(state['consecutive'], {'new_provider:docs:catalog_missing': 1})
            second, _, state = self.run_monitor(root, documents, incomplete)
            self.assertEqual(second, 1)
            self.assertEqual(state['consecutive'], {'new_provider:docs:catalog_missing': 2})
            recovered, assessment, state = self.run_monitor(root, documents, healthy)
            self.assertEqual(recovered, 0)
            self.assertEqual(assessment['status'], 'passed')
            self.assertEqual(state['consecutive'], {})
            again, _, state = self.run_monitor(root, documents, incomplete)
            self.assertEqual(again, 0)
            self.assertEqual(state['consecutive'], {'new_provider:docs:catalog_missing': 1})

    def test_scheduled_main_escalates_pending_or_missing_evidence_and_clears_after_recovery(self):
        import copy
        import tempfile
        documents, *values = self.fixture()
        healthy = dict(zip(('runtime', 'website', 'mcp', 'router'), values))
        for failure, error in [
                ('pending', 'runtime:new_provider:projection_pending'),
                ('missing_surface', 'mcp:publication_metadata_unavailable'),
                ('missing_hash', 'alpha:mcp:document_hash_mismatch'),
                ('fetch_failure', 'mcp:unavailable:TimeoutError'),
                ('legacy_only', 'docs:no_runtime_composed_provider_metadata')]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                incomplete = copy.deepcopy(healthy)
                candidate = documents
                if failure == 'pending':
                    incomplete['runtime']['pending_providers'] = [{'id': 'new_provider', 'endpoint_count': 1}]
                elif failure == 'missing_surface':
                    incomplete['mcp'] = None
                elif failure == 'missing_hash':
                    incomplete['mcp']['documentHashes'] = {}
                elif failure == 'fetch_failure':
                    incomplete['mcp'] = TimeoutError('Private details must not enter public reports')
                else:
                    candidate = {'legacy': {}}
                first, _, state = self.run_monitor(root, candidate, incomplete)
                self.assertEqual(first, 0)
                self.assertEqual(state['consecutive'][error], 1)
                second, assessment, state = self.run_monitor(root, candidate, incomplete)
                self.assertEqual(second, 1)
                self.assertEqual(state['consecutive'][error], 2)
                self.assertNotIn('Private details', str(assessment) + str(state))
                recovered, assessment, state = self.run_monitor(root, documents, healthy)
                self.assertEqual(recovered, 0)
                self.assertEqual(assessment['status'], 'passed')
                self.assertEqual(state['consecutive'], {})

    def test_strict_success_does_not_clear_scheduled_monitor_state(self):
        import json
        import tempfile
        from unittest.mock import patch
        import yaml
        documents, *values = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
            for name, value in zip(('runtime', 'website', 'mcp', 'router'), values):
                (root / f'{name}.json').write_text(json.dumps(value))
            self.write_website_version(root)
            state = root / 'state.json'
            previous = '{"consecutive":{"alpha:mcp:document_hash_mismatch":2}}'
            state.write_text(previous)
            with patch.object(sys, 'argv', ['check_contract_revisions.py', '--root', str(root),
                    '--acceptance', '--evidence-dir', str(root), '--state', str(state),
                    '--expected-docs-ref', 'a' * 40]), patch('builtins.print'), \
                    patch('check_contract_revisions.read_public', side_effect=AssertionError('network')):
                self.assertEqual(main(), 0)
            self.assertEqual(state.read_text(), previous)
