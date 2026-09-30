import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_contract_revisions import assess, compare, main, update_state

class RevisionTests(unittest.TestCase):
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
        result = assess(*self.fixture(), expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['scope'], 'public_contract_convergence')
        self.assertGreater(result['checked_at'], 0)

    def test_matching_hashes_do_not_hide_wrong_consumer_revision(self):
        values = list(self.fixture())
        values[3]['docsRefs'].append('b' * 40)
        values[4]['docs_commit'] = 'b' * 40
        result = assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], ['mcp:docs_revision_mismatch', 'tool-router:docs_revision_mismatch'])

    def test_new_runtime_catalog_cannot_be_absent_from_every_consumer(self):
        values = list(self.fixture())
        values[1]['providers'].append({'id': 'new_provider', 'facts_hash': 'newfacts'})
        result = assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], ['new_provider:docs:catalog_missing'])

    def test_runtime_projection_pending_is_not_deployed_acceptance(self):
        values = list(self.fixture())
        values[1]['pending_providers'] = [{'id': 'new_provider', 'endpoint_count': 1}]
        result = assess(*values, expected_docs_ref='a' * 40)
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
