from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canonical_replay import stage_composer, verify_outputs
from schema_input_bundle import sha


class PinnedComposerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        source = self.repo / 'scripts/shadow_compile_bundle.py'
        source.parent.mkdir()
        source.write_text('print("pinned")\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'Pinned compiler')
        self.pins = {'composer_revision': self.git('rev-parse', 'HEAD').strip(),
                     'source_manifest_sha256': sha(json.dumps({
                         'scripts/shadow_compile_bundle.py': sha(source.read_bytes())},
                         sort_keys=True, separators=(',', ':')).encode())}

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True)

    def test_uses_committed_pinned_code_and_rejects_wrong_source_manifest(self):
        (self.repo / 'scripts/shadow_compile_bundle.py').write_text('raise RuntimeError("draft")\n')
        target = self.root / 'staged'
        stage_composer(self.repo, self.pins, target)
        self.assertEqual((target / 'scripts/shadow_compile_bundle.py').read_text(), 'print("pinned")\n')
        with self.assertRaisesRegex(ValueError, 'source manifest differs'):
            stage_composer(self.repo, {**self.pins, 'source_manifest_sha256': '0' * 64},
                           self.root / 'bad-pin')

    def test_symlink_source_is_rejected(self):
        (self.repo / 'scripts/unsafe.py').symlink_to('/tmp/untrusted.py')
        self.git('add', 'scripts/unsafe.py')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'Invalid source')
        with self.assertRaisesRegex(ValueError, 'non-regular Git input'):
            stage_composer(self.repo, {**self.pins, 'composer_revision': self.git('rev-parse', 'HEAD').strip()},
                           self.root / 'unsafe')


class CompleteReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.members = {'contracts/native/one.json': b'{"schema":{"type":"string"}}',
                        'contracts/native/two.json': b'{"schema":{"type":"integer"}}',
                        'contracts/openapi.json': b'{"aggregate":true}',
                        'contracts/readiness.json': b'{"status":"passed"}'}
        self.outputs = {}
        for name, raw in self.members.items():
            rel = ('aggregate/openapi.json' if name == 'contracts/openapi.json'
                   else name.removeprefix('contracts/'))
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.outputs[name] = path
        (self.root / 'manifest.json').write_text('{}')

    def test_every_native_aggregate_and_readiness_byte_must_match(self):
        self.assertEqual(verify_outputs(self.root, self.members), 4)
        for name, path in self.outputs.items():
            raw = path.read_bytes()
            path.write_bytes(raw + b'\n')
            with self.subTest(member=name), self.assertRaisesRegex(ValueError, 'replay output differs'):
                verify_outputs(self.root, self.members)
            path.write_bytes(raw)
        # Typed changes cannot be hidden by Python's True == 1 equality.
        self.outputs['contracts/openapi.json'].write_bytes(b'{"aggregate":1}')
        with self.assertRaisesRegex(ValueError, 'replay output differs'):
            verify_outputs(self.root, self.members)

    def test_extra_missing_and_symlinked_outputs_fail(self):
        extra = self.root / 'native/extra.json'
        extra.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'membership differs'):
            verify_outputs(self.root, self.members)
        extra.unlink()
        path = self.outputs['contracts/native/one.json']
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'membership differs'):
            verify_outputs(self.root, self.members)
        target = self.root / 'manifest.json'
        target.write_bytes(raw)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            verify_outputs(self.root, self.members)


if __name__ == '__main__':
    unittest.main()
import json
