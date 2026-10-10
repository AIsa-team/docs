"""Exercise publication races, stale evidence and immutable route moves."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pull_openapi import fetch_json, stage
from test_runtime_contracts import facts, operation

REPO = Path(__file__).resolve().parents[2]


class StaleFactsTests(unittest.TestCase):
    def test_stale_200_and_304_cannot_refresh_runtime_evidence(self):
        class Response(io.BytesIO):
            headers = {'Warning': '110 - "Response is stale"', 'Cache-Control': 'no-cache'}
        with patch('pull_openapi.urlopen', return_value=Response(b'{"old":true}')):
            with self.assertRaisesRegex(URLError, 'stale runtime response'):
                fetch_json('https://fixture.invalid/index')
        error = HTTPError('https://fixture.invalid/facts', 304, 'Not modified',
                          {'Warning': '110 - "Response is stale"'}, None)
        with patch('pull_openapi.urlopen', side_effect=error):
            with self.assertRaisesRegex(URLError, 'stale runtime response'):
                fetch_json('https://fixture.invalid/facts', '"prior"')

    def test_fresh_200_and_304_keep_conditional_fetch_behavior(self):
        with patch('pull_openapi.urlopen', return_value=io.BytesIO(b'{"current":true}')):
            self.assertEqual(fetch_json('https://fixture.invalid/index'), {'current': True})
        with patch('pull_openapi.urlopen', side_effect=HTTPError('url', 304, 'Not modified', {}, None)):
            self.assertIsNone(fetch_json('https://fixture.invalid/facts', '"prior"'))


class RouteMoveTests(unittest.TestCase):
    def test_real_stage_preserves_page_urls_and_current_route_without_duplicate_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / 'facts').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: false\nproviders:\n  similarweb: {}\n')
            source = facts()
            (root / 'facts/similarweb.json').write_text(json.dumps(source))
            (root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
                {'language': lang, 'tabs': [{'tab': tab, 'groups': []}]}
                for lang, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
            changes, _ = stage(root, root / 'facts', 'unused')
            for path, value in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            old_path = next(iter(source['paths']))
            new_path = old_path + '/renamed'
            source['paths'][new_path] = source['paths'].pop(old_path)
            source['info']['x-aisa-document']['facts_hash'] = 'changed-route'
            (root / 'facts/similarweb.json').write_text(json.dumps(source))
            changes, _ = stage(root, root / 'facts', 'unused')
            document = json.loads(changes[root / 'openapi/similarweb.json'])
            self.assertEqual(set(document['paths']), {new_path})
            self.assertEqual(operation(document)['operationId'], 'published_identity')
            for prefix in ('', 'zh/'):
                page = root / f'{prefix}api-reference/similarweb/published_identity.mdx'
                self.assertIn(new_path, changes[page])
                self.assertNotIn(f'GET {old_path}"', changes[page])
            for path, value in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            repeated, _ = stage(root, root / 'facts', 'unused')
            self.assertEqual(repeated, {})

    def test_same_route_cannot_be_reassigned_to_another_published_id(self):
        from pull_openapi import assert_identities
        before = facts()
        after = copy.deepcopy(before)
        operation(after)['operationId'] = 'other_identity'
        with self.assertRaisesRegex(ValueError, 'published identity changed'):
            assert_identities(before, after)

    def test_route_and_provider_move_rebinds_legacy_page_and_removes_old_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir(); (root / 'facts').mkdir()
            registry = root / 'openapi/registry.yaml'
            registry.write_text('auto_register: false\nproviders:\n  similarweb: {}\n')
            source = facts(); old_path = next(iter(source['paths']))
            source['paths']['/keep'] = copy.deepcopy(source['paths'][old_path])
            source['paths']['/keep']['post']['operationId'] = 'keep_identity'
            (root / 'facts/similarweb.json').write_text(json.dumps(source))
            (root / 'docs.json').write_text('{"navigation":{"languages":[]}}')
            changes, _ = stage(root, root / 'facts', 'unused')
            for path, value in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
            # Simulate a pre-managed page: its published spec remains ID authority.
            page = root / 'api-reference/similarweb/published_identity.mdx'
            page.write_text('\n'.join(line for line in page.read_text().split('\n') if not line.startswith('x-aisa-operation-id:')))
            second = facts(); second['paths'] = {'/new-provider/renamed': second['paths'].pop(old_path)}
            del source['paths'][old_path]
            source['info']['x-aisa-document']['facts_hash'] = 'remaining-facts'
            second['info']['x-aisa-document']['facts_hash'] = 'moved-facts'
            registry.write_text('auto_register: false\nproviders:\n  similarweb: {}\n  second: {}\n')
            (root / 'facts/similarweb.json').write_text(json.dumps(source))
            (root / 'facts/second.json').write_text(json.dumps(second))
            changes, _ = stage(root, root / 'facts', 'unused')
            prior = json.loads(changes[root / 'openapi/similarweb.json'])
            self.assertEqual(set(prior['paths']), {'/keep'})
            moved = json.loads(changes[root / 'openapi/second.json'])
            self.assertEqual(operation(moved)['operationId'], 'published_identity')
            self.assertIn('openapi/second.json POST /new-provider/renamed', changes[page])
            self.assertIn('openapi/zh/second.json POST /new-provider/renamed',
                          changes[root / 'zh/api-reference/similarweb/published_identity.mdx'])


class PublicationRaceTests(unittest.TestCase):
    def git(self, root, *arguments):
        return subprocess.check_output(['git', *arguments], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()

    def setup_checkout(self, root):
        remote = root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        seed = root / 'seed'; seed.mkdir()
        self.git(seed, 'init', '-q', '-b', 'main')
        self.git(seed, 'config', 'user.name', 'fixture')
        self.git(seed, 'config', 'user.email', 'fixture@example.invalid')
        for relative in ('openapi/example.json', 'api-reference/page.mdx', 'zh/api-reference/page.mdx', 'docs.json', 'openapi.yaml'):
            path = seed / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('original\n')
        self.git(seed, 'add', '.')
        self.git(seed, 'commit', '-qm', 'initial')
        self.git(seed, 'remote', 'add', 'origin', str(remote))
        self.git(seed, 'push', '-q', '-u', 'origin', 'main')
        candidate = root / 'candidate'
        self.git(root, 'clone', '-q', '-b', 'main', str(remote), str(candidate))
        (candidate / 'openapi/example.json').write_text('assessed candidate\n')
        metadata = candidate / 'docs/publication/current.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'contract_release': 'a'*64})+'\n')
        # Run the real origin writer in the actual publish-step race fixture.
        import shutil
        shutil.copytree(REPO/'scripts', candidate/'scripts', ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        return seed, candidate

    def publish(self, candidate, root):
        workflow = yaml.safe_load((REPO / '.github/workflows/pull-openapi.yml').read_text())
        script = next(step['run'] for step in workflow['jobs']['compose']['steps'] if step.get('id') == 'publish')
        script = script.replace('python scripts/', __import__('shlex').quote(sys.executable)+' scripts/')
        return subprocess.run(['bash', '-e', '-c', script], cwd=candidate,
                              env={**os.environ, 'GITHUB_OUTPUT': str(root / 'output'),
                                   'PUBLISH_RUN_ID':'123', 'PUBLISH_RUN_ATTEMPT':'1'}, capture_output=True, text=True)

    def test_concurrent_main_change_cannot_enter_unassessed_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); seed, candidate = self.setup_checkout(root)
            (seed / 'openapi/unassessed.json').write_text('concurrent unrelated new contract\n')
            self.git(seed, 'add', '.'); self.git(seed, 'commit', '-qm', 'concurrent main')
            self.git(seed, 'push', '-q', 'origin', 'main')
            concurrent = self.git(seed, 'rev-parse', 'HEAD')
            result = self.publish(candidate, root)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Main changed after contract assessment', result.stderr)
            self.assertEqual(self.git(root, '--git-dir=remote.git', 'rev-parse', 'main'), concurrent)
            self.assertFalse((root / 'output').exists())

    def test_unchanged_main_publishes_exact_assessed_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); _, candidate = self.setup_checkout(root)
            result = self.publish(candidate, root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            published = self.git(root, '--git-dir=remote.git', 'rev-parse', 'main')
            self.assertEqual(published, self.git(candidate, 'rev-parse', 'HEAD'))
            self.assertEqual(self.git(root, '--git-dir=remote.git', 'show', 'main:openapi/example.json'), 'assessed candidate')
            self.assertIn('docs_commit=' + published, (root / 'output').read_text())
            self.assertEqual(self.git(root, '--git-dir=remote.git', 'show', 'main:docs/publication/current.json'),
                             json.dumps({'contract_release': 'a'*64}))
            receipt = json.loads(self.git(root, '--git-dir=remote.git', 'show', 'main:docs/publication/release-origin.json'))
            self.assertEqual(receipt['run_id'], '123')

    def test_source_maintenance_has_its_own_bounded_schedule(self):
        workflow = yaml.safe_load((REPO / '.github/workflows/refresh-upstream.yml').read_text())
        trigger = workflow.get('on', workflow.get(True))
        self.assertEqual(trigger['schedule'], [{'cron': '17 0,12 * * *'}])
        self.assertIn('workflow_dispatch', trigger)
        self.assertNotIn('RUNTIME_CONTRACT_ACTIVATION_ENABLED', workflow['jobs']['refresh'].get('if', ''))


class SourceReviewWorkflowTests(unittest.TestCase):
    def run_candidate_step(self, fail_at='', change_pointer=False):
        workflow = yaml.safe_load((REPO / '.github/workflows/refresh-upstream.yml').read_text())
        step = next(step for step in workflow['jobs']['refresh']['steps']
                    if step.get('name') == 'Compose and assess the complete source review candidate')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publication = root / 'docs/publication'
            publication.mkdir(parents=True)
            for name in ('current.json', 'formal-contract-readiness.json', 'runtime-acquisition.json'):
                (publication / name).write_text('original')
            def git(*args):
                return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@example.invalid')
            git('add', '.'); git('commit', '-qm', 'existing formal publication')
            executable = root / 'bin/python'
            executable.parent.mkdir()
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$CALLS"\n'
                                  'if [ "$1" = "$FAIL_AT" ]; then exit 17; fi\n'
                                  'if [ "$CHANGE_POINTER" = 1 ]; then echo changed > docs/publication/current.json; fi\n')
            executable.chmod(0o755)
            calls = root / 'calls'
            result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']],
                                    cwd=root, capture_output=True, text=True,
                                    env={**os.environ, 'PATH': str(executable.parent) + os.pathsep + os.environ['PATH'],
                                         'CALLS': str(calls), 'FAIL_AT': fail_at,
                                         'CHANGE_POINTER': '1' if change_pointer else '0',
                                         'REVIEWED_BASELINE': 'a' * 40})
            return result, calls.read_text().splitlines()

    def test_candidate_requires_every_stage_before_accepting_graph(self):
        result, calls = self.run_candidate_step()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['scripts/pull_openapi.py', 'scripts/runtime_consolidate_openapi.py',
                                 'scripts/validate_runtime_api_reference_slugs.py', 'scripts/check_contract_candidate.py'])

    def test_failed_composition_or_formal_assessment_stops_candidate(self):
        for failure in ('scripts/pull_openapi.py', 'scripts/check_contract_candidate.py'):
            with self.subTest(failure=failure):
                result, calls = self.run_candidate_step(fail_at=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[-1], failure)

    def test_candidate_cannot_replace_formal_publication_pointer(self):
        result, _ = self.run_candidate_step(change_pointer=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('docs/publication/current.json', result.stdout)


if __name__ == '__main__':
    unittest.main()
