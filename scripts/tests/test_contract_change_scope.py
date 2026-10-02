import subprocess
from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_change_scope import git_requires_artifact_check, verify_required_jobs


class ChangeScopeTests(unittest.TestCase):
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
