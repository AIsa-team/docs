import copy
from datetime import datetime, timedelta, timezone
import hashlib
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
            urls = dict(zip(('https://api.aisa.one/info/openapi.json', 'https://aisa.one/.well-known/agent-card.json',
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
            urls = dict(zip(('https://api.aisa.one/info/openapi.json', 'https://aisa.one/.well-known/agent-card.json',
                'https://tools.aisa.one/.well-known/catalog.json'), surfaces.values()))
            urls['https://aisa.one/api/contracts/version'] = {'mode': 'formal', 'docsRevision': expected,
                'contentHash': digest}
            report = root / 'report.json'
            def run(began):
                argv = ['monitor', '--root', str(root), '--state', str(root/'state.json'), '--require-budget',
                        '--expected-docs-ref', expected, '--selection-file', str(selection_file),
                        '--budget-start', began.isoformat(), '--report', str(report)]
                with patch.object(sys, 'argv', argv), patch('check_contract_revisions.read_public', side_effect=lambda url: urls[url]), \
                        patch('publication_origin.verify_consumer_refs', side_effect=lambda root, expected, refs, budget: {
                            'status': 'passed', 'expected_docs_ref': expected, 'contract_release': expected + '0' * 24,
                            'clock_docs_ref': expected, 'budget_start': budget, 'publications': {expected: {}}}), \
                        patch('builtins.print'):
                    return main(), json.loads(report.read_text())
            status, failed = run(start)
            self.assertEqual(failed['status'], 'failed')
            self.assertIn('tool-router:docs_revision_mismatch', failed['mismatches'])
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
