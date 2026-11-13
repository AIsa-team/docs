import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_contract_plan as plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def index(*rows, generation=1, revision='a' * 64):
    return {'artifact_revision': revision, 'generation': generation, 'fresh': True,
            'files': [{'name': name, 'media_type': 'application/json', 'sha256': sha} for name, sha in rows]}


class ContentHashTests(unittest.TestCase):
    def test_hash_covers_names_and_bytes_but_not_metadata_or_order(self):
        rows = [('index.json', '1' * 64), ('contracts/native/x.json', '2' * 64)]
        first = plan.content_hash(index(*rows))
        self.assertEqual(first, plan.content_hash(index(*reversed(rows), generation=9, revision='b' * 64)))
        expected = hashlib.sha256(f'contracts/native/x.json {"2" * 64}\nindex.json {"1" * 64}\n'.encode()).hexdigest()
        self.assertEqual(first, expected)
        self.assertNotEqual(first, plan.content_hash(index(('index.json', '1' * 64), ('contracts/native/x.json', '3' * 64))))
        self.assertNotEqual(first, plan.content_hash(index(('index.json', '1' * 64))))

    def test_invalid_or_duplicate_rows_are_refused(self):
        for bad in ({}, index(), index(('x.json', 'nothex')),
                    index(('x.json', '1' * 64), ('x.json', '2' * 64)),
                    index(('x.json', '1' * 64), ('x.json', '1' * 64))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                plan.content_hash(bad)

    def test_category_ignores_only_the_cache_timestamp(self):
        category = {'apis': [{'id': 'a'}], 'cached_at': 1}
        self.assertEqual(plan.category_hash(category), plan.category_hash({**category, 'cached_at': 2}))
        self.assertNotEqual(plan.category_hash(category), plan.category_hash({'apis': [{'id': 'b'}], 'cached_at': 1}))
        with self.assertRaises(ValueError):
            plan.category_hash({'cached_at': 1})


class DocsInputTests(unittest.TestCase):
    def test_generated_outputs_are_not_inputs_but_registry_is(self):
        for path in ('openapi/aisa-social.json', 'api-reference/x/y.mdx', 'zh/api-reference/a.mdx',
                     'docs.json', 'llms.txt', 'openapi.yaml', 'docs/publication/current.json',
                     'discovery/openapi.json', 'discovery/payment-evidence.json'):
            self.assertFalse(plan.is_input(path), path)
        for path in ('openapi/registry.yaml', 'scripts/canonical_import.py', 'translations/openapi-zh.json',
                     'docs/human-api-retirements.json', 'README.md'):
            self.assertTrue(plan.is_input(path), path)

    def test_bot_mirror_commit_keeps_the_key_and_a_source_edit_changes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                               cwd=root, check=True, capture_output=True)
            (root / 'openapi').mkdir()
            (root / 'scripts').mkdir()
            (root / 'openapi/x.json').write_text('{}')
            (root / 'scripts/gen.py').write_text('a = 1\n')
            git('init', '-q'); git('add', '.'); git('commit', '-qm', 'base')
            base = plan.docs_inputs(root)
            (root / 'openapi/x.json').write_text('{"regenerated": true}')
            git('commit', '-qam', 'mirror')
            self.assertEqual(plan.docs_inputs(root), base)
            (root / 'openapi/registry.yaml').write_text('providers: {}\n')
            git('add', '.'); git('commit', '-qm', 'registry')
            registry = plan.docs_inputs(root)
            self.assertNotEqual(registry, base)
            (root / 'scripts/gen.py').write_text('a = 2\n')
            git('commit', '-qam', 'generator')
            self.assertNotEqual(plan.docs_inputs(root), registry)

    def test_input_key_depends_on_every_part(self):
        key = plan.input_key('c', 'k', 'd')
        self.assertEqual(len({key, plan.input_key('x', 'k', 'd'), plan.input_key('c', 'x', 'd'),
                              plan.input_key('c', 'k', 'x')}), 4)


class FetchTests(unittest.TestCase):
    def test_transient_errors_are_retried_then_reported_unavailable(self):
        calls = []
        def opener_open(request, timeout):
            calls.append(request.full_url)
            raise URLError('timed out')
        with patch.object(plan, 'build_opener') as build:
            build.return_value.open.side_effect = opener_open
            with self.assertRaises(plan.Unavailable):
                plan.fetch('https://api.example.invalid', plan.CURRENT, sleep=lambda _: None)
        self.assertEqual(calls, ['https://api.example.invalid/public/api-contract/current'] * 3)

    def test_main_reports_unavailable_with_exit_two_and_no_outputs(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(plan, 'fetch', side_effect=plan.Unavailable('down')):
            output = Path(directory) / 'out'
            self.assertEqual(plan.main(['--root', str(ROOT), '--github-output', str(output)]), 2)
            self.assertFalse(output.exists())

    def test_main_writes_key_outputs(self):
        responses = {plan.CURRENT: index(('index.json', '1' * 64), generation=13699),
                     plan.CATEGORY: {'apis': [], 'cached_at': 5}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(plan, 'fetch', side_effect=lambda base, path: responses[path]), \
                patch.object(plan, 'docs_inputs', return_value='d' * 64):
            output = Path(directory) / 'out'
            self.assertEqual(plan.main(['--github-output', str(output)]), 0)
            values = dict(line.split('=', 1) for line in output.read_text().splitlines())
        self.assertEqual(values['generation'], '13699')
        self.assertEqual(values['input_key'], plan.input_key(plan.content_hash(responses[plan.CURRENT]),
                                                             plan.category_hash(responses[plan.CATEGORY]), 'd' * 64))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / '.github/workflows/pull-openapi.yml').read_text())
        self.jobs = self.workflow['jobs']
        self.trigger = self.workflow.get('on', self.workflow.get(True))

    def test_ticks_every_ten_minutes_and_queues_instead_of_cancelling(self):
        self.assertEqual(self.trigger['schedule'], [{'cron': '*/10 * * * *'}])
        self.assertEqual(self.workflow['concurrency'], {
            'group': "${{ github.ref == 'refs/heads/main' && 'pull-openapi' || format('pull-openapi-{0}', github.ref) }}",
            'cancel-in-progress': False})

    def test_no_activation_plan_gate_remains(self):
        text = (ROOT / '.github/workflows/pull-openapi.yml').read_text()
        self.assertNotIn('activation-plan', self.jobs)
        self.assertNotIn('RUNTIME_CONTRACT_ACTIVATION_ENABLED', text)
        self.assertNotIn('contract_activation', text)
        for retired in ('check-contract-revisions.yml', 'read-merged-input-qualification.yml'):
            self.assertFalse((ROOT / '.github/workflows' / retired).exists(), retired)

    def test_compose_runs_only_when_the_plan_saw_a_change(self):
        compose = self.jobs['compose']
        self.assertEqual(compose['needs'], 'plan')
        self.assertIn("needs.plan.outputs.changed == 'true'", compose['if'])
        self.assertEqual(compose['continue-on-error'], "${{ github.event_name == 'schedule' }}")
        steps = {step.get('id'): step for step in self.jobs['plan']['steps']}
        self.assertIn('live_contract_plan.py', steps['live']['run'])
        self.assertTrue(steps['done']['with']['lookup-only'])
        self.assertEqual(steps['done']['with']['key'], 'pull-openapi-done-${{ steps.live.outputs.input_key }}')

    def test_only_a_completed_publishing_run_is_remembered(self):
        compose_steps = self.jobs['compose']['steps']
        completed = next(step for step in compose_steps if step.get('id') == 'completed')
        publish = next(i for i, step in enumerate(compose_steps) if step.get('id') == 'publish')
        self.assertGreater(compose_steps.index(completed), publish)
        prepare = next(step for step in compose_steps if step.get('id') == 'prepare')
        self.assertIn("steps.pull.outputs.available == 'true'", completed['if'])
        publishing = "(inputs.publish == true || (github.event_name != 'workflow_dispatch' && vars.RUNTIME_CONTRACT_PUBLISH != 'false'))"
        for condition in (prepare['if'], completed['if']):
            self.assertIn(publishing, condition)
            self.assertIn("github.ref == 'refs/heads/main'", condition)
        record = self.jobs['record']
        self.assertEqual(record['needs'], ['plan', 'compose'])
        save = next(step for step in record['steps'] if step.get('uses', '').startswith('actions/cache/save'))
        self.assertEqual(save['if'], "needs.compose.outputs.completed == 'true'")
        self.assertEqual(save['with']['key'], 'pull-openapi-done-${{ needs.plan.outputs.input_key }}')
        warn = record['steps'][0]
        self.assertEqual(warn['if'], "needs.compose.outputs.completed != 'true'")
        self.assertIn('::warning::', warn['run'])

    def test_acquisition_retries_with_a_fresh_output(self):
        step = next(s for s in self.jobs['compose']['steps']
                    if s.get('name') == 'Acquire one complete fresh immutable Runtime release')
        self.assertIn('for attempt in 1 2 3', step['run'])
        self.assertLess(step['run'].index('rm -rf /tmp/formal-runtime-facts'), step['run'].index('fetch_runtime_release.py'))

    def test_plan_failure_is_a_warning_not_a_failed_run(self):
        script = next(s for s in self.jobs['plan']['steps'] if s.get('id') == 'live')['run']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'scripts/live_contract_plan.py').write_text('import sys; sys.exit(2)\n')
            output = root / 'output'
            result = subprocess.run(['bash', '-e', '-c', script.replace('python ', sys.executable + ' ')],
                                    cwd=root, env={'GITHUB_OUTPUT': str(output), 'PATH': '/usr/bin:/bin'},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('::warning::', result.stdout)
            self.assertIn('available=false', output.read_text())


if __name__ == '__main__':
    unittest.main()
