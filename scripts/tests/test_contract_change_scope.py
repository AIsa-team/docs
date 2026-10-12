import subprocess
from pathlib import Path
import tempfile
import sys
import unittest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_change_scope import git_requires_artifact_check, verify_required_jobs, requires_artifact_check
from identity_compatibility import PublishedHistory


class ChangeScopeTests(unittest.TestCase):
    def test_guide_only_edits_run_protocol_checks_without_republishing_contracts(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for event in ('push', 'pull_request'):
            self.assertIn('guides/**', triggers[event]['paths'])
            self.assertIn('zh/guides/**', triggers[event]['paths'])
        self.assertFalse(requires_artifact_check([
            'guides/pricing.mdx', 'zh/guides/pricing.mdx',
            'guides/dashboard/usage-logs.mdx', 'zh/guides/dashboard/usage-logs.mdx']))

    def test_payment_review_inputs_have_candidate_check_and_outputs_require_formal_gate(self):
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                                   '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for event in ('push', 'pull_request'):
            self.assertIn('discovery/**', triggers[event]['paths'])
        self.assertTrue(requires_artifact_check(['discovery/openapi.json']))
        self.assertFalse(requires_artifact_check(['discovery/payment-evidence.json']))
        self.assertIn('python scripts/generate_payment_discovery.py --check',
                      [step.get('run') for step in workflow['jobs']['code-contracts']['steps']])

    def test_manual_assessment_requires_explicit_published_identity_baseline(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        field = triggers['workflow_dispatch']['inputs']['published_ref']
        self.assertIs(field['required'], True)
        self.assertEqual(field['type'], 'string')
        self.assertNotIn('default', field)  # Never silently choose the candidate as history.
        step = next(step for step in workflow['jobs']['artifact-contracts']['steps']
                    if step.get('name') == 'Check actual candidate readiness')
        self.assertEqual(step['env']['PUBLISHED_REF'],
                         "${{ github.event_name == 'workflow_dispatch' && inputs.published_ref || "
                         "github.event.pull_request.base.sha || github.event.before }}")
        self.assertIn('--published-ref "$PUBLISHED_REF"', step['run'])
        # The explicit input still enters the existing strict history validator.
        for invalid in ('', 'main', 'abc1234', 'g' * 40, 'a' * 39, 'a' * 41):
            with self.subTest(ref=invalid), self.assertRaisesRegex(ValueError, 'full published Git SHA'):
                PublishedHistory(root, invalid)

    def test_publication_projection_and_receipts_require_formal_gate(self):
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                                   '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for name in ('sales-catalog.json', 'current.json', 'formal-contract-readiness.json',
                     'runtime-acquisition.json'):
            self.assertTrue(requires_artifact_check(['docs/publication/' + name]))
        for event in ('push', 'pull_request'):
            self.assertIn('docs/publication/**', triggers[event]['paths'])
        self.assertFalse(requires_artifact_check(['docs/publication-notes.md']))

    def test_exact_overview_pages_require_formal_gate_and_both_ci_triggers(self):
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                                   '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for page in ('api-reference.mdx', 'zh/api-reference.mdx'):
            self.assertTrue(requires_artifact_check([page]))
            for event in ('push', 'pull_request'):
                self.assertIn(page, triggers[event]['paths'])
        self.assertFalse(requires_artifact_check(['README.mdx', 'zh/guide.mdx', 'api-reference-extra.mdx']))

    def test_existing_required_check_rejects_failed_missing_or_skipped_applicable_jobs(self):
        def results(scope='false', changes='success', code='success', artifact='skipped'):
            return {'changes': {'result': changes, 'outputs': {'artifacts': scope}},
                    'code-contracts': {'result': code}, 'artifact-contracts': {'result': artifact}}
        verify_required_jobs(results())
        verify_required_jobs(results('true', artifact='success'))
        for state in (results(changes='failure'), results(scope=None), results(scope=''),
                      results(code='cancelled'), results('true'),
                      results('true', artifact='failure'), results(artifact='cancelled')):
            with self.subTest(state=state), self.assertRaises(ValueError):
                verify_required_jobs(state)

    def test_git_diff_keeps_code_only_independent_but_mixed_and_removed_sources_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            (root / 'scripts').mkdir(); (root / 'scripts/generator.py').write_text('before\n')
            (root / 'openapi/upstream').mkdir(parents=True)
            source = root / 'openapi/upstream/source.json'; source.write_text('{}\n')
            git('add', '.'); git('commit', '-qm', 'fixture baseline')
            base = git('rev-parse', 'HEAD')
            (root / 'scripts/generator.py').write_text('after\n')
            git('add', '.'); git('commit', '-qm', 'code only')
            self.assertFalse(git_requires_artifact_check(root, base))
            source.unlink()
            git('add', '-u'); git('commit', '-qm', 'mixed removal')
            self.assertTrue(git_requires_artifact_check(root, base))
            self.assertTrue(git_requires_artifact_check(root, ''))
            self.assertTrue(git_requires_artifact_check(root, '0' * 40))
            with self.assertRaises(subprocess.CalledProcessError):
                git_requires_artifact_check(root, 'unavailable-revision')


if __name__ == '__main__':
    unittest.main()
