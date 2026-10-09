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
        metadata.write_text('assessed same-commit pointer\n')
        return seed, candidate

    def publish(self, candidate, root):
        workflow = yaml.safe_load((REPO / '.github/workflows/pull-openapi.yml').read_text())
        script = next(step['run'] for step in workflow['jobs']['compose']['steps'] if step.get('id') == 'publish')
        return subprocess.run(['bash', '-e', '-c', script], cwd=candidate,
                              env={**os.environ, 'GITHUB_OUTPUT': str(root / 'output')}, capture_output=True, text=True)

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
                             'assessed same-commit pointer')

    def test_source_maintenance_has_its_own_bounded_schedule(self):
        workflow = yaml.safe_load((REPO / '.github/workflows/refresh-upstream.yml').read_text())
        trigger = workflow.get('on', workflow.get(True))
        self.assertEqual(trigger['schedule'], [{'cron': '17 0,12 * * *'}])
        self.assertIn('workflow_dispatch', trigger)
        self.assertNotIn('RUNTIME_CONTRACT_ACTIVATION_ENABLED', workflow['jobs']['refresh'].get('if', ''))


if __name__ == '__main__':
    unittest.main()
