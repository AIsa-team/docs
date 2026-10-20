import subprocess
from pathlib import Path
import tempfile
import sys
import unittest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_change_scope import (git_requires_artifact_check, verify_required_jobs,
                                   requires_artifact_check, is_reviewed_input_change)
from identity_compatibility import PublishedHistory


class ChangeScopeTests(unittest.TestCase):
    def test_input_only_intent_is_closed_and_requires_changed_context(self):
        context, receipt = 'docs/schema-inputs/context.json', 'docs/schema-inputs/source-receipts.json'
        self.assertTrue(is_reviewed_input_change([context, receipt, 'openapi/upstream/one.json']))
        self.assertTrue(is_reviewed_input_change([context, 'openapi/registry.yaml']))
        for paths in ([context, receipt], [receipt, 'openapi/upstream/one.json'],
                      [context, 'openapi/upstream/../one.json']):
            self.assertFalse(is_reviewed_input_change(paths))
        for extra in ('scripts/changed.py', 'openapi/one.json', 'api-reference/one.mdx',
                      'docs/publication/current.json', 'docs/publication/release-origin.json',
                      'openapi/overlays/one.json', 'docs/schema-inputs/extra.json'):
            self.assertFalse(is_reviewed_input_change([context, receipt, 'openapi/upstream/one.json', extra]))
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
                                   '.github/workflows/test-runtime-contracts.yml').read_text())
        steps = workflow['jobs']['artifact-contracts']['steps']
        original = next(row for row in steps if row.get('name') == 'Check actual candidate readiness')
        candidate = next(row for row in steps if 'check_reviewed_schema_inputs.py' in row.get('run', ''))
        self.assertEqual(original['if'], "needs.changes.outputs.input_candidate != 'true'")
        self.assertEqual(candidate['if'], "needs.changes.outputs.input_candidate == 'true' && steps.input_recovery.outputs.selected != 'true' && steps.open_input_diagnostic.outputs.selected != 'true'")
        recovery = next(row for row in steps if 'read_recovery_input_qualification.py --output' in row.get('run', ''))
        self.assertEqual(recovery['if'], "steps.input_recovery.outputs.selected == 'true' && steps.open_input_diagnostic.outputs.selected != 'true'")
        acquire = next(row for row in steps if 'fetch_runtime_release.py --current' in row.get('run', ''))
        self.assertEqual(acquire['if'], "steps.input_recovery.outputs.selected != 'true' && steps.open_input_diagnostic.outputs.selected != 'true'")
        self.assertIn('--base "$INPUT_BASE"', candidate['run'])

    def test_input_review_and_regression_attachments_do_not_admit_execution_or_outputs(self):
        source = ['docs/schema-inputs/context.json', 'docs/schema-inputs/source-receipts.json',
                  'openapi/upstream/apollo.json']
        attachments = ['scripts/tests/test_apollo_people_request_location.py',
                       'docs/current-source-review-20261009/merged-source-reviews.json',
                       'docs/current-source-review-20261016/apollo-people-request-location-review.json']
        self.assertTrue(is_reviewed_input_change(source + attachments))
        self.assertFalse(is_reviewed_input_change(attachments))
        self.assertFalse(is_reviewed_input_change(source[1:] + attachments))
        for extra in ('scripts/compose_openapi.py', 'scripts/check_reviewed_schema_inputs.py',
                      'scripts/contract_change_scope.py', 'scripts/tests/__init__.py',
                      'scripts/tests/helper.py', 'scripts/tests/fixtures/test_hidden.py',
                      'scripts/tests/test_../escape.py', '.github/workflows/test-runtime-contracts.yml',
                      'openapi/apollo.json', 'openapi.yaml', 'openapi/overlays/apollo.json',
                      'docs/publication/current.json', 'api-reference/apollo.mdx',
                      'docs/current-source-review-20261016/review.py',
                      'docs/current-source-review-20261016/unknown.json',
                      'docs/current-source-review-20261016/../apollo-review.json'):
            with self.subTest(extra=extra):
                self.assertFalse(is_reviewed_input_change(source + attachments + [extra]))

    def test_guide_only_edits_run_protocol_checks_without_republishing_contracts(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for event in ('push', 'pull_request'):
            self.assertIn('guides/**', triggers[event]['paths'])
            self.assertIn('zh/guides/**', triggers[event]['paths'])
        self.assertFalse(requires_artifact_check([
            'guides/pricing.mdx', 'zh/guides/pricing.mdx',
            'guides/dashboard/overview.mdx', 'zh/guides/dashboard/usage-logs.mdx']))

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

    def test_artifact_check_acquires_current_without_overwriting_candidate_or_baselines(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        steps = workflow['jobs']['artifact-contracts']['steps']
        commands = [step.get('run', '') for step in steps]
        acquire = next(command for command in commands if 'fetch_runtime_release.py' in command)
        self.assertIn('--current', acquire)
        self.assertNotIn('--artifact-revision', acquire)
        self.assertNotIn('--compiler-revision', acquire)
        self.assertNotIn('origin/main:docs/publication/runtime-acquisition.json', '\n'.join(commands))
        check = next(step for step in steps if step.get('name') == 'Check actual candidate readiness')
        self.assertEqual(check['env']['REVIEWED_BASELINE'], '${{ vars.RUNTIME_CONTRACT_BASELINE_REF }}')
        self.assertIn('--facts-dir /tmp/runtime-contract-evidence', check['run'])
        self.assertIn('--baseline-ref "$REVIEWED_BASELINE"', check['run'])
        self.assertIn('--published-ref "$PUBLISHED_REF"', check['run'])
        # CI must inspect committed PR bytes. Regenerating first could hide a
        # stale or tampered request/schema/price in the actual proposed graph.
        for command in commands:
            for writer in ('pull_openapi.py', 'runtime_consolidate_openapi.py', 'export_contract_publication.py'):
                self.assertNotIn(writer, command)
        self.assertNotIn('continue-on-error', check)

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
