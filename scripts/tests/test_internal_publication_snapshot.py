import copy
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import internal_publication_snapshot as adapter
from schema_input_bundle import canonical, sha
import test_fetch_runtime_release as public_tests


class InternalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'snapshot'
        self.root.mkdir()
        _, compiler, _, current, self.payload, _ = public_tests.PublicReleaseTests().fixture()
        # A synthetic transport-unit fixture, not a claimed Go-validated snapshot.
        self.metadata = {key: current[key] for key in
                         ('generation', 'source_digest', 'compiler_revision', 'files')}
        self.metadata['schema_version'] = '1'
        self.pins = {'generation': current['generation'], 'source_digest': current['source_digest'],
                     'compiler_revision': compiler}
        for name, raw in self.payload.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.save()

    def save(self):
        raw = canonical(self.metadata)
        (self.root / 'snapshot.json').write_bytes(raw)
        self.pins['snapshot_sha256'] = sha(raw)

    def load(self):
        return adapter.load_snapshot(self.root, **self.pins)

    def replace(self, name, raw):
        (self.root / name).write_bytes(raw)
        next(row for row in self.metadata['files'] if row['name'] == name)['sha256'] = sha(raw)
        self.save()

    def test_original_bytes_and_discovery_without_public_receipt_or_io(self):
        with patch('socket.socket.connect', side_effect=AssertionError('network')), \
                patch('subprocess.run', side_effect=AssertionError('process')):
            facts, binding = self.load()
        self.assertEqual(facts['example.json'], self.payload['providers/example.json'])
        self.assertEqual(facts['index.json'], self.payload['index.json'])
        self.assertEqual(json.loads(facts['category.json']), {'apis': [{'id': 'example'}]})
        self.assertEqual(binding['kind'], 'private_publication_snapshot_transport')
        self.assertEqual(binding['validation'], 'pinned_transport_integrity_not_go_validation_attestation')
        self.assertNotIn('acquisition_receipt_sha256', binding)
        self.assertNotIn('artifact_revision', binding)
        self.assertEqual(set(path.name for path in self.root.iterdir()), {'snapshot.json', 'providers', 'index.json'})

    def test_go_raw_number_and_escaped_bytes_are_not_reserialized(self):
        raw = self.payload['providers/example.json'][:-1] + b',"extension":{"escaped":"\\u003c", "number":1.2300}}'
        self.replace('providers/example.json', raw)
        self.assertEqual(self.load()[0]['example.json'], raw)

    def test_pending_generation_needs_no_published_current(self):
        self.metadata['generation'] = 2 ** 64 - 1
        self.pins['generation'] = 2 ** 64 - 1
        self.save()
        self.assertEqual(self.load()[1]['generation'], 2 ** 64 - 1)

    def test_all_caller_pins_are_independent(self):
        for field, bad in [('snapshot_sha256', '0' * 64), ('generation', 7),
                           ('source_digest', '0' * 64), ('compiler_revision', '0' * 40)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter.load_snapshot(self.root, **{**self.pins, field: bad})

    def test_uint64_and_pin_types(self):
        for value in [True, -1, 2 ** 64, '3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.load_snapshot(self.root, **{**self.pins, 'generation': value})
        self.metadata['generation'] = True
        self.pins['generation'] = 1
        self.save()
        with self.assertRaises(ValueError):
            self.load()

    def test_envelope_has_no_claimed_receipt_freshness_or_inline_content(self):
        original = copy.deepcopy(self.metadata)
        for field in ['fresh', 'receipt', 'published_generation', 'go_validation_passed']:
            self.metadata = {**original, field: True}
            self.save()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load()
        self.metadata = original
        self.metadata['files'][0]['content'] = {}
        self.save()
        with self.assertRaises(ValueError):
            self.load()

    def test_duplicate_json_key_is_rejected_even_with_updated_pin(self):
        raw = (self.root / 'snapshot.json').read_bytes().replace(b'"generation":3', b'"generation":2,"generation":3')
        (self.root / 'snapshot.json').write_bytes(raw)
        self.pins['snapshot_sha256'] = sha(raw)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.load()
        self.save()
        raw = self.payload['providers/example.json'][:-1] + b',"paths":{}}'
        self.replace('providers/example.json', raw)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.load()

    def test_members_are_ordered_unique_and_path_safe(self):
        original = copy.deepcopy(self.metadata)
        for names in [['providers/example.json', 'index.json'], ['index.json', 'index.json'],
                      ['index.json', '../outside.json'], ['index.json', 'providers/a%2fb.json'],
                      ['index.json', '/absolute.json']]:
            self.metadata = copy.deepcopy(original)
            for row, name in zip(self.metadata['files'], names):
                row['name'] = name
            self.save()
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.load()

    def test_missing_and_extra_files_fail_closed(self):
        extra = self.root / 'category.json'
        extra.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'Unexpected snapshot member'):
            self.load()
        extra.unlink()
        (self.root / 'providers/example.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing snapshot member'):
            self.load()

    def test_member_hash_tamper_is_rejected(self):
        with (self.root / 'providers/example.json').open('ab') as handle:
            handle.write(b' ')
        with self.assertRaisesRegex(ValueError, 'Content hash'):
            self.load()

    def test_symlink_and_fifo_are_rejected(self):
        path = self.root / 'providers/example.json'
        path.unlink()
        path.symlink_to(self.root / 'index.json')
        with self.assertRaises(ValueError):
            self.load()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.load()

    def test_all_resource_limits(self):
        for constant in ['MAX_METADATA', 'MAX_FILE', 'MAX_TOTAL', 'MAX_FILES']:
            with self.subTest(constant=constant), patch.object(adapter, constant, 1), self.assertRaises(ValueError):
                self.load()

    def test_pending_incomplete_or_orphan_graph_rejected_after_repin(self):
        base = json.loads(self.payload['index.json'])
        for change in [{'pending_endpoints': [{}]}, {'pending_providers': ['example']},
                       {'coverage': {**base['coverage'], 'projected_endpoint_count': 0}},
                       {'coverage': {**base['coverage'], 'pending_endpoint_count': False}},
                       {'providers': []}, {'providers': [{**base['providers'][0], 'facts_hash': '0' * 64}]}]:
            self.replace('index.json', canonical({**base, **change}))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load()

    def test_compile_uses_one_core_and_explicit_internal_kind(self):
        output = Path(self.temp.name) / 'output'
        with patch.object(adapter, 'load_bundle', return_value='verified-bundle'), \
                patch.object(adapter, 'compile_verified_inputs', return_value={'status': 'passed'}) as core:
            adapter.compile_snapshot('bundle', self.root, bundle_sha256='a' * 64, docs_ref='b' * 40,
                                     output=output, **self.pins)
        self.assertEqual(core.call_args.args[0], 'verified-bundle')
        self.assertEqual(core.call_args.kwargs, {'output': output, 'input_kind': 'internal_publication_snapshot'})
        self.assertEqual(core.call_args.args[1]['example.json'], self.payload['providers/example.json'])

    def test_malformed_graph_has_controlled_rejection(self):
        value = json.loads(self.payload['index.json'])
        value['providers'] = ['not an index row']
        self.replace('index.json', canonical(value))
        with self.assertRaisesRegex(ValueError, 'graph structure'):
            self.load()

    def test_failed_snapshot_never_calls_core_or_creates_output(self):
        output = Path(self.temp.name) / 'output'
        (self.root / 'index.json').write_bytes(b'{}')
        with patch.object(adapter, 'load_bundle', return_value='verified-bundle'), \
                patch.object(adapter, 'compile_verified_inputs') as core, self.assertRaises(ValueError):
            adapter.compile_snapshot('bundle', self.root, bundle_sha256='a' * 64, docs_ref='b' * 40,
                                     output=output, **self.pins)
        core.assert_not_called()
        self.assertFalse(output.exists())

    def test_cli_rejection_does_not_echo_private_payload(self):
        stderr = io.StringIO()
        with patch.object(adapter, 'compile_snapshot', side_effect=ValueError('PRIVATE VALUE')), \
                redirect_stderr(stderr), self.assertRaises(SystemExit):
            adapter.main(['--bundle', 'b', '--bundle-sha256', 'a' * 64, '--docs-ref', 'b' * 40,
                          '--snapshot', str(self.root), '--snapshot-sha256', self.pins['snapshot_sha256'],
                          '--generation', '3', '--source-digest', 'a' * 64, '--compiler-revision', 'b' * 40,
                          '--output', 'out'])
        self.assertEqual(stderr.getvalue(), 'Internal snapshot shadow rejected: ValueError\n')


if __name__ == '__main__':
    unittest.main()
