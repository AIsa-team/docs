"""Ensure dev automation cannot publish or notify production consumers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def enabled(condition, ref, event='workflow_dispatch', base=''):
    # These workflow conditions contain only comparisons and boolean operators.
    values = {
        'github.event.pull_request.base.ref': base,
        'github.event_name': event,
        'github.ref': ref,
        'github.repository': 'AIsa-team/docs',
        'needs.activation-plan.outputs.enabled': 'true',
        'vars.RUNTIME_CONTRACT_ACTIVATION_ENABLED': 'true',
        'needs.compose.outputs.docs_commit': 'a' * 40,
    }
    for key, value in values.items():
        condition = condition.replace(key, repr(value))
    condition = condition.replace('always()', 'True').replace('&&', 'and').replace('||', 'or')
    return eval(condition, {'__builtins__': {}})


class BranchIsolationTests(unittest.TestCase):
    def test_production_jobs_cannot_run_from_dev_feature_branches_or_tags(self):
        jobs = {
            'pull-openapi.yml': ['activation-plan', 'compose', 'notify-consumers'],
            'check-contract-revisions.yml': ['activation-plan', 'revisions'],
            'refresh-upstream.yml': ['refresh'],
            'sync-openapi.yml': ['sync-openapi'],
            'dispatch-contract-consumers.yml': ['dispatch'],
        }
        for name, identifiers in jobs.items():
            for identifier in identifiers:
                condition = workflow(name)['jobs'][identifier]['if']
                with self.subTest(workflow=name, job=identifier):
                    self.assertTrue(enabled(condition, 'refs/heads/main'))
                    for ref in ('refs/heads/dev', 'refs/heads/feature', 'refs/tags/main'):
                        self.assertFalse(enabled(condition, ref))

    def test_live_production_assessment_only_applies_to_main_and_prs_into_main(self):
        value = workflow('test-runtime-contracts.yml')
        trigger = value.get('on', value.get(True))
        self.assertEqual(trigger['push']['branches'], ['main'])
        self.assertEqual(trigger['pull_request']['branches'], ['main'])
        for name in ('changes', 'contracts'):
            condition = value['jobs'][name]['if']
            self.assertTrue(enabled(condition, 'refs/heads/main', 'push'))
            self.assertTrue(enabled(condition, 'refs/pull/1/merge', 'pull_request', 'main'))
            self.assertFalse(enabled(condition, 'refs/heads/dev'))
            self.assertFalse(enabled(condition, 'refs/pull/1/merge', 'pull_request', 'dev'))
        self.assertEqual(value['jobs']['artifact-contracts']['needs'], 'changes')

    def test_dev_checks_have_no_production_credentials_acquisition_or_notifications(self):
        value = workflow('dev-docs.yml')
        trigger = value.get('on', value.get(True))
        self.assertEqual(trigger['push']['branches'], ['dev'])
        self.assertEqual(trigger['pull_request']['branches'], ['dev'])
        self.assertEqual(value['permissions'], {'contents': 'read'})
        job = value['jobs']['offline-contracts']
        self.assertTrue(enabled(job['if'], 'refs/heads/dev', 'push'))
        self.assertTrue(enabled(job['if'], 'refs/pull/1/merge', 'pull_request', 'dev'))
        self.assertFalse(enabled(job['if'], 'refs/heads/main'))
        text = yaml.safe_dump(job)
        for production_operation in ('secrets.', 'fetch_runtime_release.py', 'check_contract_candidate.py',
                                     'refresh_payment_publication.py', 'git push', 'gh api',
                                     'create-github-app-token', 'actions/cache'):
            self.assertNotIn(production_operation, text)
        checks = workflow('docs-checks.yml')
        self.assertIn('dev', checks.get('on', checks.get(True))['push']['branches'])
        self.assertIn('github.ref', workflow('pull-openapi.yml')['concurrency']['group'])

    def test_consumer_notification_rejects_a_dev_commit_before_minting_credentials(self):
        steps = workflow('dispatch-contract-consumers.yml')['jobs']['dispatch']['steps']
        validation = next(step for step in steps if step.get('name', '').startswith('Require a published main'))
        token_index = next(i for i, step in enumerate(steps)
                           if step.get('uses', '').startswith('actions/create-github-app-token@'))
        self.assertLess(steps.index(validation), token_index)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote.git'
            subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
            checkout = root / 'checkout'
            checkout.mkdir()

            def git(*args):
                return subprocess.check_output(['git', *args], cwd=checkout, text=True,
                                               stderr=subprocess.DEVNULL).strip()

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            git('commit', '--allow-empty', '-qm', 'published main')
            main = git('rev-parse', 'HEAD')
            git('remote', 'add', 'origin', str(remote))
            git('push', '-q', 'origin', 'main')
            git('switch', '-qc', 'dev')
            git('commit', '--allow-empty', '-qm', 'unpublished dev')
            dev = git('rev-parse', 'HEAD')
            for commit, expected in ((main, True), (dev, False), ('b' * 40, False), ('main', False)):
                with self.subTest(commit=commit):
                    result = subprocess.run(['bash', '-e', '-c', validation['run']], cwd=checkout,
                                            env={**os.environ, 'DOCS_COMMIT': commit},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, expected, result.stderr)

    def test_scheduled_generation_checks_out_dev_and_shares_its_write_lock(self):
        value = workflow('generate-dev-docs.yml')
        trigger = value.get('on', value.get(True))
        self.assertIn('schedule', trigger)
        self.assertEqual(trigger['push']['branches'], ['main'])
        self.assertEqual(trigger['push']['paths'], ['.github/workflows/generate-dev-docs.yml'])
        job = value['jobs']['generate']
        self.assertTrue(enabled(job['if'], 'refs/heads/main', 'schedule'))
        for ref in ('refs/heads/dev', 'refs/pull/1/merge', 'refs/tags/main'):
            self.assertFalse(enabled(job['if'], ref, 'workflow_dispatch'))
        self.assertEqual(value['permissions'], {'contents': 'read'})
        self.assertEqual(job['permissions'], {'contents': 'write'})
        self.assertEqual(job['steps'][0]['with']['ref'], 'dev')
        self.assertEqual(value['concurrency']['group'], 'dev-docs-refs/heads/dev')
        self.assertFalse(value['concurrency']['cancel-in-progress'])
        self.assertFalse(workflow('dev-docs.yml')['concurrency']['cancel-in-progress'])
        text = yaml.safe_dump(job)
        for operation in ('secrets.', 'create-github-app-token', 'dispatch-contract',
                          'fetch_runtime_release.py', 'HEAD:main', '--force'):
            self.assertNotIn(operation, text)
        self.assertIn('--if-changed', text)
        self.assertIn('HEAD:refs/heads/dev', text)

    def test_scheduled_generation_pushes_only_dev_and_refuses_a_main_checkout(self):
        step = workflow('generate-dev-docs.yml')['jobs']['generate']['steps'][-1]['run']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote.git'
            checkout = root / 'site'
            checkout.mkdir()
            subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)

            def git(*args):
                return subprocess.check_output(['git', *args], cwd=checkout, text=True,
                                               stderr=subprocess.DEVNULL).strip()

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            for name in ('docs.json', 'openapi.yaml', 'openapi/example.json',
                         'endpoint.mdx', 'docs/dev-runtime.json'):
                target = checkout / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('baseline\n')
            git('add', '.')
            git('commit', '-qm', 'production baseline')
            main = git('rev-parse', 'HEAD')
            git('remote', 'add', 'origin', str(remote))
            git('push', '-q', 'origin', 'main')
            env = {**os.environ, 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            rejected = subprocess.run(['bash', '-e', '-c', step], cwd=checkout, env=env,
                                      capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(git('rev-parse', 'HEAD'), main)
            git('switch', '-qc', 'dev')
            git('push', '-q', 'origin', 'dev')
            (checkout / 'endpoint.mdx').write_text('generated from dev Runtime\n')
            result = subprocess.run(['bash', '-e', '-c', step], cwd=checkout, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            main_remote = subprocess.check_output(['git', '--git-dir', str(remote),
                                                  'rev-parse', 'main'], text=True).strip()
            dev_remote = subprocess.check_output(['git', '--git-dir', str(remote),
                                                 'rev-parse', 'dev'], text=True).strip()
            self.assertEqual(main_remote, main)
            self.assertEqual(dev_remote, git('rev-parse', 'HEAD'))
            self.assertNotEqual(dev_remote, main)


if __name__ == '__main__':
    unittest.main()
