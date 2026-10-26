from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_canonical_presentation_candidate import assess, checked_scope, presentation_only


class PresentationScopeTests(unittest.TestCase):
    def test_pages_navigation_receipts_and_code_can_be_checked_together(self):
        self.assertTrue(presentation_only(['api-reference/provider/get_operation.mdx',
            'zh/api-reference/provider/get_operation.mdx', 'docs.json', 'openapi/nav-groups.json',
            'docs/current-source-review-20261009/merged-source-reviews.json',
            'scripts/check_canonical_presentation_candidate.py',
            '.github/workflows/test-runtime-contracts.yml']))
        self.assertFalse(presentation_only(['scripts/check_canonical_presentation_candidate.py']))
        self.assertFalse(presentation_only([]))

    def test_schema_policy_and_formal_output_changes_cannot_use_projection(self):
        for name in ('openapi/provider.json', 'openapi/zh/provider.json', 'openapi/openapi.json',
                     'openapi/coverage.json', 'openapi/registry.yaml', 'openapi/upstream/provider.json',
                     'openapi/policies/deferred-enabled-20261010.json', 'openapi.yaml', 'llms.txt',
                     'docs/schema-inputs/context.json', 'docs/publication/current.json',
                     'discovery/openapi.json'):
            with self.subTest(name=name):
                self.assertFalse(presentation_only(['api-reference/provider/get_operation.mdx', name]))


class IsolatedCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repository'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'openapi').mkdir()
        (self.root / 'openapi/provider.json').write_text('{}')
        (self.root / 'api-reference').mkdir()
        (self.root / 'api-reference/provider.mdx').write_text('Original prose\n')
        (self.root / '.gitignore').write_text('.cache/\n')
        self.commit()
        self.base = self.git('rev-parse', 'HEAD')
        (self.root / 'api-reference/provider.mdx').write_text('Reviewed prose\n')
        self.commit()
        (self.root / '.cache').mkdir()
        (self.root / '.cache/source-reviews.json').write_text('{"schema_version":1,"receipts":{}}')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture')

    def test_committed_presentation_diff_is_accepted(self):
        self.assertEqual(checked_scope(self.root, self.base), ['api-reference/provider.mdx'])

    def test_committed_schema_edit_is_rejected_before_projection(self):
        (self.root / 'openapi/provider.json').write_text('{"changed":true}')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'cannot accept schema'):
            checked_scope(self.root, self.base)

    def test_uncommitted_and_untracked_schema_edits_are_rejected(self):
        path = self.root / 'openapi/provider.json'
        path.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'tracked bytes changed'):
            checked_scope(self.root, self.base)
        path.write_text('{}')
        (self.root / 'openapi/rogue.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'untracked publication inputs'):
            checked_scope(self.root, self.base)

    def test_failed_projection_removes_only_its_worktree_and_preserves_original(self):
        before = self.git('worktree', 'list', '--porcelain')
        head = self.git('rev-parse', 'HEAD')
        with patch('check_canonical_presentation_candidate.verified_mode', return_value='canonical'), \
             patch('check_canonical_presentation_candidate.stage_canonical', side_effect=ValueError('stage rejected')):
            with self.assertRaisesRegex(ValueError, 'stage rejected'):
                assess(self.root, Path(self.temp.name) / 'facts', base=self.base, baseline='reviewed')
        self.assertEqual(self.git('worktree', 'list', '--porcelain'), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual((self.root / 'api-reference/provider.mdx').read_text(), 'Reviewed prose\n')
        self.assertEqual(self.git('status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
