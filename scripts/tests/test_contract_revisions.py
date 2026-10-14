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
        (root / 'website.yaml').write_bytes((root / 'openapi.yaml').read_bytes())
        (root / 'website-version.json').write_text(json.dumps({'mode': 'formal', 'docsRevision': 'a' * 40,
            'contentHash': hashlib.sha256((root / 'openapi.yaml').read_bytes()).hexdigest()}))

    def test_grouped_facts_and_consumers_use_per_provider_hashes(self):
        documents = {'group': {'document_hash': 'document', 'catalogs': {'a': {'x-aisa-document': {'facts_hash': 'facts'}}}}, 'legacy': {}}
        runtime = {'providers': [{'id': 'a', 'facts_hash': 'facts'}]}
        website = {'x-aisa-document': {'providers': {'group': {'document_hash': 'document'}}}}
        router = {'provider_document_hashes': {'group': 'document'}}
        self.assertEqual(compare(documents, runtime, website, router), [])
        runtime['providers'][0]['facts_hash'] = 'changed'
        self.assertEqual(compare(documents, runtime, website, router), ['group:a:facts_hash_mismatch'])
    def test_only_consecutive_failures_escalate(self):
        first = update_state(['a'], {})
        self.assertEqual(first['consecutive'], {'a': 1})
        self.assertEqual(update_state(['a'], first)['consecutive'], {'a': 2})
        self.assertEqual(update_state([], first)['consecutive'], {})

    def fixture(self):
        return ({'alpha': {'document_hash': 'doc', 'facts_hash': 'facts'}, 'legacy': {}},
                {'providers': [{'id': 'alpha', 'facts_hash': 'facts'}]},
                {'x-aisa-document': {'providers': {'alpha': {'document_hash': 'doc'}}}},
                {'provider_document_hashes': {'alpha': 'doc'}, 'docs_commit': 'a' * 40})

    def test_only_verified_same_c_refs_can_differ_and_other_checks_remain(self):
        values = list(self.fixture())
        values[3]['docs_commit'] = 'b' * 40
        version = {'mode': 'formal', 'docsRevision': 'b' * 40, 'contentHash': 'd' * 64}
        proof = {'status': 'passed', 'expected_docs_ref': 'a' * 40, 'contract_release': 'c' * 64,
                 'clock_docs_ref': 'f' * 40, 'publications': {'b' * 40: {}}}
        self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40, website_version=version)['status'], 'failed')
        result = self.assess(*values, expected_docs_ref='a' * 40, website_version=version, formal_provenance=proof)
        self.assertEqual(result['status'], 'passed')
        version['contentHash'] = 'e' * 64
        self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40, website_version=version,
                                    formal_provenance=proof)['status'], 'failed')
        proof['status'] = 'failed'
        with self.assertRaises(ValueError):
            self.assess(*values, expected_docs_ref='a' * 40, website_version=version, formal_provenance=proof)

    def test_metadata_refresh_preserves_observation_identity_without_waiving_deadline(self):
        from check_contract_revisions import publication_identity
        proof = {'status': 'passed', 'contract_release': 'c' * 64, 'clock_docs_ref': 'f' * 40}
        assessment = {'formal_provenance': proof}
        first = publication_identity(assessment, 'a' * 40, 'd' * 64, '2026-10-10T16:56:34Z', 'convergence')
        later = publication_identity(assessment, 'b' * 40, 'd' * 64, '2026-10-10T16:56:34Z', 'convergence')
        self.assertEqual(first, later)
        other = publication_identity({'formal_provenance': dict(proof, contract_release='e' * 64)},
                                     'b' * 40, 'd' * 64, '2026-10-10T16:56:34Z', 'convergence')
        self.assertNotEqual(first, other)

    def test_empty_legacy_catalog_cannot_pass_acceptance(self):
        result = assess({'legacy': {}}, {}, {}, {})
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
                'https://aisa.one/openapi.yaml',
                'https://tools.aisa.one/.well-known/catalog.json'), values))
            version_url = 'https://aisa.one/api/contracts/version'
            urls[version_url] = {'mode': 'formal', 'docsRevision': 'b' * 40,
                'contentHash': hashlib.sha256(raw.encode()).hexdigest()}
            with patch.object(sys, 'argv', ['monitor', '--root', str(root), '--acceptance',
                    '--expected-docs-ref', 'a' * 40, '--report', str(root / 'report.json')]), \
                    patch('check_contract_revisions.read_public', side_effect=lambda url: urls[url]) as reader, \
                    patch('check_contract_revisions.read_public_bytes', return_value=raw.encode()), \
                    patch('builtins.print'):
                self.assertEqual(main(), 1)
            self.assertIn(version_url, [call.args[0] for call in reader.call_args_list])
            report = json.loads((root / 'report.json').read_text())
            self.assertEqual(report['mismatches'], ['website:docs_revision_mismatch'])
            self.assertEqual(report['expected_openapi_sha256'], urls[version_url]['contentHash'])

    def test_invalid_router_provider_hash_map_is_a_structured_failure(self):
        for invalid in (None, [], ['alpha'], 'invalid', 1, False):
            with self.subTest(metadata=invalid):
                values = list(self.fixture())
                values[3]['provider_document_hashes'] = invalid
                result = self.assess(*values, expected_docs_ref='a' * 40)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['mismatches'], [
                    'alpha:tool-router:document_hash_mismatch',
                    'tool-router:provider_document_hashes_invalid'])

    def test_null_router_hashes_strict_cli_writes_failure_without_state_mutation(self):
        import json
        import tempfile
        from unittest.mock import patch
        documents, *surfaces = self.fixture()
        surfaces[2]['provider_document_hashes'] = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
            for name, value in zip(('runtime', 'website', 'router'), surfaces):
                (root / f'{name}.json').write_text(json.dumps(value))
            self.write_website_version(root)
            state = root / 'state.json'
            state.write_text('{"consecutive":{"old":1}}')
            report = root / 'report.json'
            with patch.object(sys, 'argv', ['monitor', '--root', str(root), '--acceptance',
                    '--evidence-dir', str(root), '--state', str(state),
                    '--expected-docs-ref', 'a' * 40, '--report', str(report)]), \
                    patch('builtins.print'), \
                    patch('check_contract_revisions.read_public', side_effect=AssertionError('network')):
                self.assertEqual(main(), 1)
            self.assertEqual(state.read_text(), '{"consecutive":{"old":1}}')
            assessment = json.loads(report.read_text())
            self.assertEqual(assessment['status'], 'failed')
            self.assertIn('tool-router:provider_document_hashes_invalid', assessment['mismatches'])

    def test_null_router_hashes_monitor_escalates_and_recovers(self):
        import copy
        import tempfile
        documents, *values = self.fixture()
        healthy = dict(zip(('runtime', 'website', 'router'), values))
        incomplete = copy.deepcopy(healthy)
        incomplete['router']['provider_document_hashes'] = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, report, state = self.run_monitor(root, documents, incomplete)
            self.assertEqual(first, 0)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(state['consecutive']['tool-router:provider_document_hashes_invalid'], 1)
            second, report, state = self.run_monitor(root, documents, incomplete)
            self.assertEqual(second, 1)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(state['consecutive']['tool-router:provider_document_hashes_invalid'], 2)
            recovered, report, state = self.run_monitor(root, documents, healthy)
            self.assertEqual(recovered, 0)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(state['consecutive'], {})

    def test_matching_hashes_do_not_hide_wrong_consumer_revision(self):
        values = list(self.fixture())
        values[3]['docs_commit'] = 'b' * 40
        result = self.assess(*values, expected_docs_ref='a' * 40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['mismatches'], ['tool-router:docs_revision_mismatch'])

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
        surfaces[2]['docs_commit'] = 'b' * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'openapi.yaml').write_text(yaml.safe_dump({'info': {'x-aisa-document': {'providers': documents}}}))
            for name, value in zip(('runtime', 'website', 'router'), surfaces):
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
            'https://aisa.one/openapi.yaml': 'website',
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
                patch('check_contract_revisions.read_public', side_effect=read_fixture), \
                patch('check_contract_revisions.read_public_bytes', return_value=(root / 'openapi.yaml').read_bytes()), \
                patch('builtins.print'):
            status = main()
        return status, json.loads(report.read_text()), json.loads((root / 'state.json').read_text())

    def test_scheduled_main_escalates_new_runtime_catalog_absent_everywhere_and_recovers(self):
        import copy
        import tempfile
        documents, *values = self.fixture()
        healthy = dict(zip(('runtime', 'website', 'router'), values))
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
        healthy = dict(zip(('runtime', 'website', 'router'), values))
        for failure, error in [
                ('pending', 'runtime:new_provider:projection_pending'),
                ('missing_surface', 'router:publication_metadata_unavailable'),
                ('missing_hash', 'alpha:tool-router:document_hash_mismatch'),
                ('fetch_failure', 'router:unavailable:TimeoutError'),
                ('legacy_only', 'docs:no_runtime_composed_provider_metadata')]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                incomplete = copy.deepcopy(healthy)
                candidate = documents
                if failure == 'pending':
                    incomplete['runtime']['pending_providers'] = [{'id': 'new_provider', 'endpoint_count': 1}]
                elif failure == 'missing_surface':
                    incomplete['router'] = None
                elif failure == 'missing_hash':
                    incomplete['router']['provider_document_hashes'] = {}
                elif failure == 'fetch_failure':
                    incomplete['router'] = TimeoutError('Private details must not enter public reports')
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

    def test_retired_mcp_does_not_block_current_consumers_or_retain_old_alarm(self):
        import json
        import tempfile
        documents, *values = self.fixture()
        # Real CLI calls the three public targets through run_monitor. Its URL
        # map deliberately has no retired MCP endpoint; any fetch would fail.
        healthy = dict(zip(('runtime', 'website', 'router'), values))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'state.json').write_text(json.dumps({'consecutive': {
                'mcp:unavailable:TimeoutError': 4,
                'alpha:mcp:document_hash_mismatch': 4}}))
            status, assessment, state = self.run_monitor(root, documents, healthy)
            self.assertEqual((status, assessment['status']), (0, 'passed'))
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
            for name, value in zip(('runtime', 'website', 'router'), values):
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

    def test_served_aggregate_requires_exact_raw_hash_and_actual_info_metadata(self):
        import hashlib
        from check_contract_revisions import website_metadata
        raw = yaml.safe_dump({'info': {'x-aisa-document': {'providers': {'alpha': {'document_hash': 'doc'}}}}}).encode()
        self.assertEqual(website_metadata(raw, hashlib.sha256(raw).hexdigest()),
                         {'x-aisa-document': {'providers': {'alpha': {'document_hash': 'doc'}}}})
        with self.assertRaises(ValueError):
            website_metadata(raw + b'\n', hashlib.sha256(raw).hexdigest())
        wrong_surface = b'{"x-openapi":"https://aisa.one/openapi.yaml"}'
        with self.assertRaises(ValueError):
            website_metadata(wrong_surface, hashlib.sha256(wrong_surface).hexdigest())

    def test_empty_catalog_requires_hash_bound_accepted_disabled_coverage(self):
        import copy
        import hashlib
        import json
        from unittest.mock import patch
        from check_contract_revisions import verified_empty_catalogs
        row = {'catalog': 'empty', 'operation_id': 'disabled1', 'method': 'GET', 'path': '/disabled',
               'status': 'pending', 'runtime_status': 'disabled', 'binding_hash': 'bound'}
        provider = {'id': 'empty', 'facts_hash': 'facts', 'operation_count': 1}
        document = {'info': {'x-aisa-document': {'document_hash': 'document', 'facts_hash': 'facts'}}, 'paths': {}}
        coverage = {'providers': {'empty': [row]}}
        report = {'status': 'passed', 'providers': {'empty': {'status': 'passed',
                  'existing_pending': [dict(row, runtime_binding={'status': 'disabled'})]}}}
        def prove(doc=document, cov=coverage, assessment=report, corrupt=None, public_corrupt=False):
            files = {'openapi/empty.json': json.dumps(doc).encode(),
                     'openapi/coverage.json': json.dumps(cov).encode(),
                     'docs/publication/formal-contract-readiness.json': json.dumps(assessment).encode()}
            hashes = {path: hashlib.sha256(raw).hexdigest() for path, raw in files.items()}
            current = {'status': 'passed', 'openapi': {'path': 'openapi.yaml', 'sha256': 'd' * 64},
                       'files_sha256': dict(hashes, **{'openapi.yaml': 'd' * 64}), 'formal_readiness': {'path': 'docs/publication/formal-contract-readiness.json',
                       'sha256': hashes['docs/publication/formal-contract-readiness.json']}}
            files['docs/publication/current.json'] = json.dumps(current).encode()
            if corrupt:
                files[corrupt] += b' '
            with patch('check_contract_revisions.subprocess.check_output',
                       side_effect=lambda command, **kwargs: files[command[2].split(':', 1)[1]]):
                return verified_empty_catalogs(Path('.'), 'a' * 40, 'd' * 64,
                                               {'providers': [provider]}, {}, provider_reader=lambda name: files['openapi/' + name + '.json'] + (b' ' if public_corrupt else b''))
        proof = prove()
        self.assertEqual(proof['empty']['coverage_rows'], 1)
        for artifact in ('openapi/empty.json', 'openapi/coverage.json', 'docs/publication/formal-contract-readiness.json'):
            with self.subTest(artifact=artifact), self.assertRaises(ValueError):
                prove(corrupt=artifact)
        with self.assertRaises(ValueError):
            prove(public_corrupt=True)
        nonempty = copy.deepcopy(document)
        nonempty['paths'] = {'/enabled': {'get': {'operationId': 'enabled'}}}
        self.assertEqual(prove(doc=nonempty), {})
        enabled = copy.deepcopy(coverage)
        enabled['providers']['empty'][0]['runtime_status'] = 'enabled'
        self.assertEqual(prove(cov=enabled), {})
        unaccepted = copy.deepcopy(report)
        unaccepted['providers']['empty']['existing_pending'] = []
        self.assertEqual(prove(assessment=unaccepted), {})
        changed_binding = copy.deepcopy(coverage)
        changed_binding['providers']['empty'][0]['binding_hash'] = 'different'
        self.assertEqual(prove(cov=changed_binding), {})
        missing_rows = copy.deepcopy(coverage)
        missing_rows['providers']['empty'] = []
        self.assertEqual(prove(cov=missing_rows), {})
        values = list(self.fixture())
        values[1]['providers'].append(provider)
        values[3]['provider_document_hashes']['empty'] = 'document'
        self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40,
                                    empty_catalogs=proof)['status'], 'passed')
        self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40,
                                    empty_catalogs={})['mismatches'], ['empty:docs:catalog_missing'])

        for value in ('wrong', None):
            values[3]['provider_document_hashes']['empty'] = value
            self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40,
                                        empty_catalogs=proof)['mismatches'],
                             ['empty:tool-router:document_hash_mismatch'])
        del values[3]['provider_document_hashes']['empty']
        self.assertEqual(self.assess(*values, expected_docs_ref='a' * 40,
                                    empty_catalogs=proof)['mismatches'],
                         ['empty:tool-router:document_hash_mismatch'])
