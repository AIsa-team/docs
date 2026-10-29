import copy
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_bundle_supply as supply
from schema_input_bundle import canonical, sha, REVIEWED_BASELINE
import publication_origin as origin


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        name = 'evidence/source-receipts.json'
        path = self.bundle / name
        path.parent.mkdir(parents=True)
        self.source = b'{"schema_version":1,"original_clock":"2026-10-15T00:00:00Z"}\n'
        path.write_bytes(self.source)
        (self.bundle / 'manifest.json').write_bytes(canonical({'files': [{'path': name}]}))

    def test_archive_bytes_ignore_filesystem_timestamps_and_preserve_content(self):
        first, second = self.root / 'a.gz', self.root / 'b.gz'
        supply.pack_bundle(self.bundle, first)
        os.utime(self.bundle / 'manifest.json', (123, 123))
        os.utime(self.bundle / 'evidence/source-receipts.json', (456, 456))
        supply.pack_bundle(self.bundle, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        supply.unpack_bundle(first.read_bytes(), self.root / 'out')
        self.assertEqual((self.root / 'out/evidence/source-receipts.json').read_bytes(), self.source)
        with tarfile.open(first, 'r:gz') as archive:
            self.assertEqual(archive.getnames(), sorted(archive.getnames()))
            self.assertTrue(all(row.uid == row.gid == row.mtime == 0 for row in archive))

    def archive(self, rows):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as archive:
            for name, kind, size in rows:
                info = tarfile.TarInfo(name)
                info.type, info.size = kind, size
                if kind == tarfile.SYMTYPE:
                    info.linkname = '/etc/passwd'
                archive.addfile(info, io.BytesIO(b'x' * size) if kind == tarfile.REGTYPE else None)
        return raw.getvalue()

    def test_paths_links_directories_and_duplicates_are_rejected(self):
        for rows in [[('../escape', tarfile.REGTYPE, 1)], [('/escape', tarfile.REGTYPE, 1)],
                     [('unlisted-role.json', tarfile.REGTYPE, 1)],
                     [('manifest.json', tarfile.SYMTYPE, 0)], [('manifest.json', tarfile.DIRTYPE, 0)],
                     [('manifest.json', tarfile.REGTYPE, 1)] * 2]:
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as parent, self.assertRaises(ValueError):
                supply.unpack_bundle(self.archive(rows), Path(parent) / 'out')

    def test_expansion_and_compressed_limits(self):
        for key in ['MAX_ARCHIVE', 'MAX_FILE', 'MAX_TOTAL', 'MAX_FILES']:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as parent:
                changes = {key: 0}
                rows = [('manifest.json', tarfile.REGTYPE, 10)]
                if key == 'MAX_TOTAL':
                    changes['MAX_FILE'] = 5
                    rows = [('manifest.json', tarfile.REGTYPE, 5),
                            ('evidence/source-receipts.json', tarfile.REGTYPE, 5)]
                if key == 'MAX_FILES':
                    rows.append(('evidence/source-receipts.json', tarfile.REGTYPE, 1))
                with patch.multiple(supply, **changes), self.assertRaises(ValueError):
                    supply.unpack_bundle(self.archive(rows), Path(parent) / 'out')

    def test_archive_requires_manifest(self):
        with self.assertRaisesRegex(ValueError, 'manifest missing'):
            supply.unpack_bundle(self.archive([('evidence/source-receipts.json', tarfile.REGTYPE, 1)]),
                                 self.root / 'out')


class SupplyEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref, self.bundle_sha = '1' * 40, '2' * 64
        self.raw = b'archive bytes inspected only after metadata pins'
        (self.root / supply.ARCHIVE).write_bytes(self.raw)
        self.receipts = b'{"receipts":{},"attempts":{}}'
        self.clock = '2026-10-15T00:00:00+00:00'
        self.packet = {'schema_version': 1, 'kind': supply.KIND, 'scope': supply.SCOPE,
            'bundle': {'schema_version': 2, 'manifest_sha256': self.bundle_sha,
                'docs_ref': self.ref, 'baseline_ref': REVIEWED_BASELINE,
                'source_receipts_sha256': sha(self.receipts), 'source_checked_at': self.clock,
                'archive': {'path': supply.ARCHIVE, 'sha256': sha(self.raw), 'bytes': len(self.raw)}},
            'producer': {'repository': origin.REPOSITORY, 'workflow': origin.WORKFLOW,
                'run_id': '123', 'run_attempt': 1, 'assessed_base': '3' * 40, 'origin_sha256': '4' * 64}}
        self.save()

    def save(self):
        (self.root / 'supply.json').write_bytes(canonical(self.packet))

    def verify(self, **extra):
        pins = dict(bundle_sha256=self.bundle_sha, archive_sha256=sha(self.raw),
                    docs_ref=self.ref, run_id='123', run_attempt=1)
        pins.update(extra)
        return supply.verify_supply(self.root, **pins)

    def test_external_pins_and_exact_metadata(self):
        base = copy.deepcopy(self.packet)
        for path, value in [('kind', 'formal-publication'), ('schema_version', True),
                            ('bundle.docs_ref', '0' * 40), ('bundle.manifest_sha256', '0' * 64),
                            ('bundle.baseline_ref', self.ref), ('producer.run_id', '999'),
                            ('producer.run_attempt', True), ('producer.workflow', 'untrusted.yml'),
                            ('bundle.archive.sha256', '0' * 64), ('bundle.archive.path', '../escape')]:
            self.packet = copy.deepcopy(base)
            container = self.packet
            keys = path.split('.')
            for key in keys[:-1]:
                container = container[key]
            container[keys[-1]] = value
            self.save()
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify()

    def test_run_identifier_matches_build_lock_positive_24_digit_limit(self):
        for value in ['0', '01', '', '1' * 25, '-1', '+1', '1\n', '１２', 1, True]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Invalid producer pins'):
                self.verify(run_id=value)
            with self.subTest(build=value), patch.object(supply, 'GitSource') as git:
                with self.assertRaisesRegex(ValueError, 'Invalid producer pins'):
                    supply.build_supply('.', self.ref, 'receipt.json', self.root / 'new',
                                        run_id=value, run_attempt=1)
                git.assert_not_called()
        verified = SimpleNamespace(contents={'evidence/source-receipts.json': self.receipts},
                                   validation={'source_checked_at': self.clock})
        with patch.object(supply, 'unpack_bundle'), patch.object(supply, 'load_bundle', return_value=verified):
            for value in ['1', '9' * 24]:
                self.packet['producer']['run_id'] = value
                self.save()
                self.assertEqual(self.verify(run_id=value)['status'], 'passed')

    def test_duplicate_envelope_and_undeclared_files(self):
        raw = canonical(self.packet).replace(b'"schema_version":1', b'"schema_version":0,"schema_version":1')
        (self.root / 'supply.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()
        self.save()
        (self.root / 'receipt.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'Unexpected supply'):
            self.verify()

    def test_original_clock_and_receipt_are_not_renewed(self):
        verified = SimpleNamespace(contents={'evidence/source-receipts.json': self.receipts},
                                   validation={'source_checked_at': self.clock})
        with patch.object(supply, 'unpack_bundle'), patch.object(supply, 'load_bundle', return_value=verified):
            result = self.verify()
            self.assertEqual(result['producer_authentication'],
                             'external_successful_formal_origin_and_main_ancestry_required')
            for field, value in [('source_checked_at', '2099-01-01T00:00:00Z'),
                                 ('source_receipts_sha256', '0' * 64)]:
                original = self.packet['bundle'][field]
                self.packet['bundle'][field] = value
                self.save()
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'assessment clock'):
                    self.verify()
                self.packet['bundle'][field] = original


    def test_verified_output_is_atomic_and_failed_validation_leaves_none(self):
        verified = SimpleNamespace(contents={'evidence/source-receipts.json': self.receipts},
                                   validation={'source_checked_at': self.clock})
        def unpack(raw, destination):
            destination.mkdir()
            (destination / 'original').write_bytes(self.receipts)
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'verified'
            with patch.object(supply, 'unpack_bundle', side_effect=unpack), \
                    patch.object(supply, 'load_bundle', side_effect=ValueError('invalid source')):
                with self.assertRaisesRegex(ValueError, 'invalid source'):
                    self.verify(output=output)
            self.assertEqual(list(Path(parent).iterdir()), [])
            with patch.object(supply, 'unpack_bundle', side_effect=unpack), \
                    patch.object(supply, 'load_bundle', return_value=verified):
                self.verify(output=output)
                self.assertEqual((output / 'original').read_bytes(), self.receipts)
                with self.assertRaisesRegex(ValueError, 'new directory'):
                    self.verify(output=output)

    def test_build_export_failure_publishes_no_packet(self):
        source = SimpleNamespace(read=lambda *args: canonical({
            'repository': origin.REPOSITORY, 'workflow': origin.WORKFLOW,
            'run_id': '123', 'run_attempt': 1, 'assessed_base': '3' * 40}),
            git=lambda *args: ('3' * 40).encode())
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'packet'
            with patch.object(supply, 'GitSource', return_value=source), \
                    patch.object(supply, 'export_bundle', side_effect=ValueError('review mismatch')):
                with self.assertRaisesRegex(ValueError, 'review mismatch'):
                    supply.build_supply('.', self.ref, 'original-receipt.json', output,
                                        run_id='123', run_attempt=1)
            self.assertEqual(list(Path(parent).iterdir()), [])


class WorkflowSupplyTests(unittest.TestCase):
    def test_context_cannot_silently_omit_legacy_supply_without_typed_assessment(self):
        from test_canonical_formal import CanonicalShapeTests
        fixture = CanonicalShapeTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        report = copy.deepcopy(fixture.report)
        ref = 'a' * 40
        source = SimpleNamespace(trees={ref: {supply.INPUT_CONTEXT_PATH: []}},
                                 read=lambda *_: canonical(report))
        with patch.object(supply, 'GitSource', return_value=source):
            with self.assertRaisesRegex(ValueError, 'version 2 assessment'):
                supply.legacy_supply_required('.', ref)
            inputs = report['canonical_runtime_import']['inputs']
            inputs.update(schema_version=2, input_context_sha256=inputs.pop('source_pointer_sha256'))
            inputs.pop('source_formal_provenance')
            inputs['source_input_provenance'] = provenance = {
                'kind': 'reviewed_git_input', 'expected_docs_ref': inputs['compiler_inputs']['docs_ref'],
                'bundle_manifest_sha256': inputs['compiler_inputs']['bundle_manifest_sha256'],
                'historical_formal_ref': 'b' * 40, 'input_context_sha256': inputs['input_context_sha256'],
                'input_source_receipts_sha256': 'c' * 64}
            for path, key in (('docs/schema-inputs/context.json', 'input_context_sha256'),
                              ('docs/schema-inputs/source-receipts.json', 'input_source_receipts_sha256')):
                for field in ('frozen_input_files_sha256', 'current_input_files_sha256'):
                    inputs[field][path] = provenance[key]
            self.assertFalse(supply.legacy_supply_required('.', ref))
            provenance['kind'] = 'formal'
            with self.assertRaises(ValueError): supply.legacy_supply_required('.', ref)

    def test_upload_is_required_before_push_and_notifications_bind_only_pushed_commit(self):
        root = Path(__file__).resolve().parents[2]
        flow = yaml.safe_load((root / '.github/workflows/pull-openapi.yml').read_text())
        job = flow['jobs']['compose']
        steps = job['steps']
        prepare = next(i for i, step in enumerate(steps) if step.get('id') == 'prepare')
        upload = next(i for i, step in enumerate(steps) if step.get('id') == 'schema_bundle')
        push = next(i for i, step in enumerate(steps) if step.get('id') == 'publish')
        self.assertLess(prepare, upload)
        self.assertLess(upload, push)
        self.assertEqual(steps[prepare]['name'], origin.STEP)
        self.assertIn('publication_origin.py record', steps[prepare]['run'])
        self.assertNotIn('git push', steps[prepare]['run'])
        self.assertNotIn('docs_commit=', steps[prepare]['run'])
        for step in steps[prepare + 1:push + 1]:
            expected = "steps.prepare.outputs.candidate_commit != ''"
            if step.get('id') == 'schema_bundle':
                expected += " && steps.supply_mode.outputs.legacy == 'true'"
            self.assertEqual(step['if'], expected)
            self.assertNotIn('continue-on-error', step)
        self.assertIn('schema_bundle_supply.py build', steps[prepare + 1]['run'])
        self.assertIn('schema_bundle_supply.py mode', steps[prepare + 1]['run'])
        self.assertIn('--source-receipts .cache/source-reviews.json', steps[prepare + 1]['run'])
        self.assertEqual(steps[upload]['uses'], 'actions/upload-artifact@v4')
        self.assertEqual(steps[upload]['with']['if-no-files-found'], 'error')
        self.assertEqual(steps[upload]['with']['retention-days'], 90)
        self.assertEqual(job['outputs']['docs_commit'], '${{ steps.publish.outputs.docs_commit }}')
        self.assertEqual(flow['jobs']['notify-consumers']['needs'], 'compose')
        self.assertEqual(flow['jobs']['notify-consumers']['if'],
                         "github.ref == 'refs/heads/main' && needs.compose.outputs.docs_commit != ''")


if __name__ == '__main__':
    unittest.main()
