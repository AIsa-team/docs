import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import runtime_publication as publication
import fetch_runtime_release as fetch
from schema_input_bundle import REVIEWED_BASELINE
import test_fetch_runtime_release as facts_fixture
import test_runtime_contract_artifact as canonical_fixture


class RuntimePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def acquired(self, canonical):
        if canonical:
            fixture = canonical_fixture.CanonicalArtifactTests(); fixture.setUp()
            acquisition = fixture.acquire()
        else:
            revision, compiler, reader, *_ = facts_fixture.PublicReleaseTests().fixture()
            acquisition = fetch.acquire(revision, compiler, reader)
        target = self.root / ('canonical' if canonical else 'facts')
        fetch.save(target, acquisition)
        return target

    def test_mode_uses_complete_saved_acquisition_and_retains_fact_only_behavior(self):
        old, new = self.acquired(False), self.acquired(True)
        self.assertEqual(publication.verified_mode(old), 'facts')
        self.assertEqual(publication.verified_mode(new), 'canonical')
        (new / 'contracts/openapi.json').write_text('{}')
        with self.assertRaises(ValueError):
            publication.verified_mode(new)
        with patch('builtins.print'):
            self.assertNotEqual(publication.main(['mode', '--facts-dir', str(new)]), 0)

    def test_invalid_schema_proof_never_falls_back_or_writes(self):
        acquired = self.acquired(True)
        marker = self.root / 'openapi.yaml'; marker.write_bytes(b'last good')
        with patch.object(publication, 'publication_refs', return_value=('a' * 40, 'b' * 40)), \
             patch.object(publication, 'schema_input_view_files', side_effect=ValueError('schema mismatch')), \
             patch('pull_openapi.stage', side_effect=AssertionError('canonical must not compose')):
            with self.assertRaisesRegex(ValueError, 'schema mismatch'):
                publication.stage_canonical(self.root, acquired, baseline=REVIEWED_BASELINE, write=True)
        self.assertEqual(marker.read_bytes(), b'last good')

    def test_canonical_requires_exact_reviewed_baseline_and_attributed_history(self):
        with self.assertRaisesRegex(ValueError, 'reviewed baseline'):
            publication.publication_refs(self.root, 'f' * 40)
        with patch.object(publication.subprocess, 'check_output', side_effect=['a' * 40, '']):
            with self.assertRaisesRegex(ValueError, 'attributed previous'):
                publication.publication_refs(self.root, REVIEWED_BASELINE)

    def test_failed_formal_gate_retains_failure_report_and_does_not_emit_pass(self):
        acquired = self.acquired(True)
        report = self.root / 'assessment.json'
        with patch.object(publication, 'publication_refs', return_value=('a' * 40, 'b' * 40)), \
             patch.object(publication, 'assess_formal_canonical', side_effect=ValueError('input drift')), \
             patch('builtins.print'):
            status = publication.main(['assess', '--root', str(self.root), '--facts-dir', str(acquired),
                '--baseline-ref', REVIEWED_BASELINE, '--report', str(report)])
        self.assertNotEqual(status, 0)
        self.assertEqual(json.loads(report.read_bytes())['status'], 'not_assessed')
        with patch('builtins.print'):
            self.assertNotEqual(publication.main(['assess', '--root', str(self.root),
                '--facts-dir', str(self.acquired(False)), '--report', str(report)]), 0)


class PublicationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
            '.github/workflows/pull-openapi.yml').read_text())
        self.steps = {step.get('name'): step for step in self.workflow['jobs']['compose']['steps']}

    def test_real_shell_dispatches_only_selected_mode_and_propagates_failure(self):
        stage = self.steps['Stage contracts']['run']
        assess = self.steps['Check formal artifact readiness before publication']['run']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / 'python'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nexit "$FAKE_STATUS"\n')
            fake.chmod(0o755)
            for script, action in ((stage, 'stage'), (assess, 'assess')):
                for mode, code in (('canonical', 0), ('canonical', 3), ('facts', 0), ('unknown', 0)):
                    log = root / 'calls'; log.write_text('')
                    result = subprocess.run(['bash', '-e', '-c', script], capture_output=True,
                        env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                             'CALL_LOG': str(log), 'FAKE_STATUS': str(code), 'RUNTIME_MODE': mode,
                             'REVIEWED_BASELINE': REVIEWED_BASELINE, 'GITHUB_OUTPUT': str(root / 'output')})
                    calls = log.read_text()
                    with self.subTest(action=action, mode=mode, code=code):
                        if mode == 'canonical':
                            self.assertIn('runtime_publication.py ' + action, calls)
                            self.assertNotIn('pull_openapi.py', calls)
                            self.assertNotIn('check_contract_candidate.py', calls)
                            self.assertEqual(result.returncode, code)
                        elif mode == 'facts':
                            self.assertIn('pull_openapi.py' if action == 'stage' else 'check_contract_candidate.py', calls)
                            self.assertNotIn('runtime_publication.py', calls)
                            self.assertEqual(result.returncode, 0)
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual(calls, '')

    def test_canonical_skips_only_recomposition_and_keeps_publication_gates(self):
        self.assertIn("steps.runtime_mode.outputs.mode == 'facts'", self.steps['Consolidate generated contracts']['if'])
        self.assertIn('runtime_publication.py mode', self.steps['Select the verified Runtime publication mode']['run'])
        self.assertEqual(self.workflow['permissions']['actions'], 'read')
        for name in ('Stage contracts', 'Check formal artifact readiness before publication',
                     'Export the passed same-commit publication pointer'):
            self.assertIn('GH_TOKEN', self.steps[name]['env'])
        for name in ('Generate payment discovery from the same staged contracts', 'Validate page references',
                     'Export the passed same-commit publication pointer'):
            self.assertEqual(self.steps[name]['if'], "steps.pull.outputs.available == 'true'")
        publish = self.steps['Push the assessed commit after schema supply succeeds']['run']
        self.assertIn('origin/main', publish)
        self.assertIn('ASSESSED_BASE', publish)
        self.assertFalse(self.workflow['concurrency']['cancel-in-progress'])
        self.assertIn('Commit contract mirrors and coverage', self.steps)


if __name__ == '__main__':
    unittest.main()
