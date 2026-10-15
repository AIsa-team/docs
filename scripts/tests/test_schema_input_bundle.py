"""Input packaging boundaries; complete frozen replay is documented separately."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_input_bundle as bundle
from export_schema_input_bundle import GitSource, export_bundle


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = '1' * 40
        self.name = 'input/openapi/upstream/test.json'
        self.raw = b'{"paths":{}}\n'
        self.manifest = {'schema_version': 1, 'kind': 'aisa-schema-input-bundle',
            'docs_ref': self.ref, 'baseline_ref': bundle.REVIEWED_BASELINE,
            'authority': copy.deepcopy(bundle.AUTHORITY), 'files': [
                {'path': self.name, 'role': 'upstream_schema', 'sha256': bundle.sha(self.raw),
                 'bytes': len(self.raw)}]}
        path = self.root / self.name
        path.parent.mkdir(parents=True)
        path.write_bytes(self.raw)

    def validate(self, *, pin=None):
        raw = bundle.canonical(self.manifest)
        (self.root / 'manifest.json').write_bytes(raw)
        return bundle.validate_bundle(self.root, expected_manifest_sha256=pin or bundle.sha(raw),
                                      expected_docs_ref=self.ref)

    def test_external_manifest_pin_is_required(self):
        with self.assertRaisesRegex(ValueError, 'caller trust pin'):
            self.validate(pin='0' * 64)

    def test_authority_bool_cannot_be_number(self):
        self.manifest['authority']['runtime_facts_included'] = 0
        with self.assertRaisesRegex(ValueError, 'authority'):
            self.validate()

    def test_version_bool_rejected(self):
        self.manifest['schema_version'] = True
        with self.assertRaisesRegex(ValueError, 'authority'):
            self.validate()

    def test_duplicate_member_rejected(self):
        self.manifest['files'] *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate member'):
            self.validate()

    def test_role_cannot_claim_runtime_price_authority(self):
        self.manifest['files'][0]['role'] = 'runtime_price'
        with self.assertRaisesRegex(ValueError, 'role mismatch'):
            self.validate()

    def test_tampered_original_bytes_rejected(self):
        (self.root / self.name).write_bytes(self.raw + b' ')
        with self.assertRaisesRegex(ValueError, 'Member bytes differ'):
            self.validate()

    def test_undeclared_file_rejected_before_semantic_loading(self):
        (self.root / 'extra.json').write_bytes(b'{}')
        with patch.object(bundle, 'SINGLETONS', {}), self.assertRaisesRegex(ValueError, 'undeclared files'):
            self.validate()

    def test_missing_input_rejected(self):
        (self.root / self.name).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing bundle member'):
            self.validate()

    def test_symlink_rejected(self):
        target = self.root / self.name
        target.unlink()
        target.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.validate()

    def test_candidate_cannot_approve_new_baseline(self):
        self.manifest['baseline_ref'] = self.ref
        with self.assertRaisesRegex(ValueError, 'baseline differs'):
            self.validate()

    def test_duplicate_json_keys_and_nonfinite_numbers(self):
        for raw in [b'{"role":1,"role":2}', b'{"x":{"sha":1,"sha":2}}', b'[NaN]', b'[Infinity]']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                bundle.strict_json(raw)

    def test_namespace_and_traversal_rejected(self):
        for name in ['../input.json', '/input.json', 'input//x', 'input/./x',
                     'input/../x', 'input/openapi/zh/x.json', 'proofs/main/openapi/x.json']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                bundle.role_for(name)

    def test_unsupported_pin_or_overlay_cannot_be_silently_dropped(self):
        for config in [{'pin': 'a' * 40}, {'overlay': {}}, {'pins': []}, {'overlays': None}]:
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, 'not supported'):
                bundle.reject_unimplemented_inputs({'providers': {'test': config}}, pointer_paths=[])
        with self.assertRaisesRegex(ValueError, 'Overlay inputs'):
            bundle.reject_unimplemented_inputs({'providers': {'test': {}}},
                                               pointer_paths=['openapi/overlays/test.yaml'])

    def test_registry_duplicate_keys_rejected(self):
        import yaml
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            yaml.load('providers:\n  test: {}\n  test: {}\n', Loader=bundle.UniqueLoader)

    def test_bounded_reader_rejects_oversize(self):
        with patch.object(bundle, 'MAX_FILE', 3), self.assertRaisesRegex(ValueError, 'size limit'):
            bundle.regular_read(self.root, self.name)

    def test_reference_context_preserves_instance_values(self):
        document = {'openapi': '3.1.0', 'paths': {}, 'components': {'schemas': {
            'Input': {'type': 'object', 'properties': {'price': {'type': 'number'},
                'status': {'type': 'string'}}, 'example': {'$ref': '../business-value'},
                'x-business': {'$ref': '../literal'}}}}}
        before = copy.deepcopy(document)
        bundle.validate_reference_closure(document)
        self.assertEqual(document, before)
        document['components']['schemas']['Input']['properties']['price'] = {'$ref': '../outside.json'}
        with self.assertRaises(ValueError):
            bundle.validate_reference_closure(document)


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = 'a' * 40
        self.members = {}
        self.proof = {'operation_id': 'old_id', 'locale': 'zh', 'published_ref': self.ref,
            'source_file': 'openapi/zh/test.json', 'canonical_source_file': 'openapi/test.json',
            'public_path': '/test', 'method': 'POST'}
        for field, identity, hash_field in [('source_file', 'old_id', 'source_sha256'),
                ('canonical_source_file', 'new_id', 'canonical_source_sha256')]:
            raw = bundle.canonical({'paths': {'/test': {'post': {'operationId': identity}}}})
            name = 'proofs/' + self.ref + '/' + self.proof[field]
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.members[name] = {'role': 'historical_alias_git_bytes'}
            self.proof[hash_field] = bundle.sha(raw)

    def history(self, proof=None, ids=None):
        return bundle.BundleHistory(self.root, self.members, {'canonical_ids': ids or ['new_id'],
            'aliases': {'new_id': [proof or self.proof]}})

    def test_original_ref_hash_method_and_id_verified(self):
        self.assertEqual(len(self.history().used), 2)
        for key, value in [('method', 'GET'), ('public_path', '/wrong'), ('operation_id', 'wrong'),
                           ('source_sha256', '0' * 64), ('published_ref', 'b' * 40),
                           ('source_file', '../test.json')]:
            proof = {**self.proof, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.history(proof)

    def test_alias_cannot_shadow_canonical(self):
        with self.assertRaisesRegex(ValueError, 'shadows canonical'):
            self.history(ids=['new_id', 'old_id'])

    def test_duplicate_proof_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate alias'):
            bundle.BundleHistory(self.root, self.members, {'canonical_ids': ['new_id'],
                'aliases': {'new_id': [self.proof, self.proof]}})

    def test_proof_parsing_uses_verified_bytes_not_mutable_paths(self):
        verified = {name: (self.root / name).read_bytes() for name in self.members}
        for name in self.members:
            (self.root / name).write_bytes(b'{"paths":{}}')
        history = bundle.BundleHistory(self.root, self.members, {'canonical_ids': ['new_id'],
            'aliases': {'new_id': [self.proof]}}, verified)
        self.assertEqual(len(history.used), 2)

    def test_multiple_owners_or_undisposed_locales_rejected(self):
        # Namespace is separately tested after real proof verification above.
        for aliases in [{'a': [{'operation_id': 'old'}], 'b': [{'operation_id': 'old'}]},
                        {'a': [{'operation_id': 'old'}, {'operation_id': 'older'}]}]:
            with self.subTest(aliases=aliases), self.assertRaises(ValueError):
                bundle.validate_namespace({'a', 'b'}, aliases)


class GitBoundaryTests(unittest.TestCase):
    def test_fixed_git_objects_and_real_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'source.json').write_bytes(b'{"original":true}')
            (root / 'link.json').symlink_to('source.json')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            ref = git('rev-parse', 'HEAD')
            source = GitSource(root, ref)
            (root / 'source.json').write_bytes(b'{"changed":true}')
            self.assertEqual(source.read(ref, 'source.json'), b'{"original":true}')
            source.ancestor(ref)
            with self.assertRaises(ValueError): source.ancestor('0' * 40)
            with self.assertRaises(ValueError): source.read(ref, 'link.json')
            with self.assertRaises(ValueError): source.read(ref, '../source.json')
            with self.assertRaises(ValueError): GitSource(root, 'HEAD')

    def test_export_refuses_candidate_approved_baseline(self):
        with self.assertRaisesRegex(ValueError, 'code-pinned'):
            export_bundle('.', 'a' * 40, 'b' * 40, '/missing', '/unused')


if __name__ == '__main__':
    unittest.main()
