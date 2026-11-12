"""Spec #1285 R1: manual entry for the public surface comparison."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_surface_checks as checks  # noqa: E402


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root, text=True).strip()


class PublicSurfaceCliTests(unittest.TestCase):
    def repo(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        git(root, 'init', '-q')
        (root / 'docs/publication').mkdir(parents=True)
        (root / 'openapi').mkdir()
        aggregate = json.dumps({'openapi': '3.1.0', 'paths': {}}).encode()
        (root / 'openapi/openapi.json').write_bytes(aggregate)
        import hashlib
        pointer = {'status': 'passed', 'openapi': {'path': 'openapi.yaml', 'sha256': 'b' * 64},
                   'files_sha256': {'openapi/openapi.json': hashlib.sha256(aggregate).hexdigest()}}
        (root / 'docs/publication/current.json').write_text(json.dumps(pointer))
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'formal')
        formal = git(root, 'rev-parse', 'HEAD')
        (root / 'README').write_text('later\n')
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'later')
        return root, formal

    def test_formal_ref_is_the_last_pointer_change(self):
        root, formal = self.repo()
        self.assertEqual(checks.formal_ref(root), formal)
        spec, expected = checks.expected_publication(root, formal)
        self.assertEqual((spec['openapi'], expected), ('3.1.0', 'b' * 64))

    def test_unbound_aggregate_is_rejected(self):
        root, _ = self.repo()
        (root / 'openapi/openapi.json').write_text('{}')
        git(root, 'commit', '-qam', 'unbound')
        with self.assertRaises(ValueError):
            checks.expected_publication(root, git(root, 'rev-parse', 'HEAD'))

    def test_status_and_exit_codes(self):
        root, formal = self.repo()
        for surfaces, status, code in [({'mismatches': [], 'missing_inputs': []}, 'passed', 0),
                                       ({'mismatches': ['mcp:docs_revision_mismatch'], 'missing_inputs': []}, 'mismatch', 1),
                                       ({'mismatches': [], 'missing_inputs': ['docs-json:unavailable:OSError']}, 'not_assessed', 3)]:
            with self.subTest(status=status), \
                    mock.patch.object(checks, 'check_surfaces', return_value=surfaces), \
                    mock.patch.object(checks, 'fixed_request_blocks', return_value={}), \
                    mock.patch.object(checks, 'fixed_payment_bytes', return_value=b'{}'), \
                    mock.patch.object(checks, 'fixed_mcp_sources', return_value={}), \
                    contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(checks.main(['--root', str(root), '--report', str(root / 'r.json')]), code)
                self.assertEqual(json.loads(out.getvalue())['docs_ref'], formal)
                self.assertEqual(json.loads((root / 'r.json').read_text())['status'], status)

    def test_check_surfaces_receives_the_formal_expectations(self):
        root, formal = self.repo()
        seen = {}
        def fake(spec, expected_hash, accepted, **kwargs):
            seen.update(expected_hash=expected_hash, accepted=accepted, read_bytes=kwargs['read_bytes'])
            return {'mismatches': [], 'missing_inputs': []}
        reader = mock.Mock()
        with mock.patch.object(checks, 'check_surfaces', fake), \
                mock.patch.object(checks, 'fixed_request_blocks', return_value={}), \
                mock.patch.object(checks, 'fixed_payment_bytes', return_value=b'{}'), \
                mock.patch.object(checks, 'fixed_mcp_sources', return_value={}):
            report = checks.run_checks(root, formal, read_bytes=reader)
        self.assertEqual((seen['expected_hash'], seen['accepted'], seen['read_bytes']), ('b' * 64, {formal}, reader))
        self.assertEqual(report['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
