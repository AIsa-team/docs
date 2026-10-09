import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_contract_publication import prepare, export, acquired_input, canonical, RUNTIME_KEYS
from fetch_runtime_release import acquire, save, sha, main
from publication_surface import publication_hashes
from sales_catalog_projection import SALES_CATALOG_PATH, sales_catalog_bytes
import test_fetch_runtime_release as fetch_tests
from source_governance import initial_policy, acquisition_receipt, receipt_key, source_report


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.facts = self.root / 'facts'
        revision, compiler, self.reader, _, _, _ = fetch_tests.PublicReleaseTests().fixture()
        save(self.facts, acquire(revision, compiler, self.reader))
        (self.root / 'openapi.yaml').write_text('openapi: 3.1.0\npaths: {}\n')
        sales = self.root / SALES_CATALOG_PATH
        sales.parent.mkdir(parents=True)
        sales.write_bytes(sales_catalog_bytes({'openapi': '3.1.0', 'paths': {}}, (self.root / 'openapi.yaml').read_bytes()))
        self.now = datetime.now(timezone.utc)
        self.metadata = initial_policy({'kind': 'provider_openapi', 'content_hash': 'sha256:' + 'a' * 64,
                         'url': 'https://official.example.invalid/openapi.json', 'refresh_policy': 'automatic'})
        upstream = self.root / 'openapi/upstream/source.json'; upstream.parent.mkdir(parents=True)
        upstream.write_text(json.dumps({'info': {'x-aisa-source': self.metadata}}))
        receipt_raw = (self.facts / 'acquisition-receipt.json').read_bytes()
        receipt = json.loads(receipt_raw)
        self.report = {'status': 'passed', 'evaluation': 'actual_publication_graph_and_offline_composed_candidate', 'composed_candidate': {'status': 'passed'},
                       'publication_surfaces': {'status': 'passed'},
                       'runtime': {key: receipt[key] for key in RUNTIME_KEYS},
                       'runtime_acquisition_sha256': sha(receipt_raw),
                       'publication_artifact': {'source_metadata': {'source.json': {key: self.metadata[key] for key in ('content_hash', 'policy_revision', 'refresh_policy')}},
                                                'source_hashes': {'source.json': self.metadata['content_hash']},
                                                'files_sha256': publication_hashes(self.root),
                                                'openapi_sha256': sha((self.root / 'openapi.yaml').read_bytes())},
                       'source_governance': {'status': 'passed', 'checked_at': self.now.isoformat(), 'sources': {'source.json': {
                           'checked_at': self.now.isoformat(), 'last_successful_review_at': self.now.isoformat(),
                           'source_hash': self.metadata['content_hash'], 'policy_revision': self.metadata['policy_revision'],
                           'freshness': 'fresh', 'policy': 'automatic',
                           'review_due_at': (self.now + timedelta(days=30)).isoformat(),
                           'next_acquisition_due_at': (self.now + timedelta(hours=1)).isoformat()}}}}

        receipts = {receipt_key(self.metadata): acquisition_receipt(self.metadata, self.now)}
        cached = self.root / '.cache/source-reviews.json'; cached.parent.mkdir()
        cached.write_text(json.dumps({'receipts': receipts}))
        self.report['source_governance'] = source_report(self.root, receipts, checked_at=self.now)

    def prepared(self, report=None):
        return prepare(self.root, self.facts, canonical(report or self.report), self.now)

    def test_single_commit_hash_has_no_self_reference_and_full_receipts_match(self):
        files = self.prepared()
        current = json.loads(files['current.json'])
        core = {key: current[key] for key in ('schema_version', 'runtime', 'files_sha256')}
        self.assertEqual(current['contract_release'], sha(canonical(core)))
        self.assertNotIn('docs_revision', current)
        self.assertEqual(current['formal_readiness']['sha256'], sha(files['formal-contract-readiness.json']))
        self.assertEqual(current['runtime_acquisition']['sha256'], sha(files['runtime-acquisition.json']))
        self.assertEqual(current['source_authorization_expires_at'], self.report['source_governance']['sources']['source.json']['next_acquisition_due_at'])
        destination = self.root / 'docs/publication'; destination.mkdir(parents=True, exist_ok=True)
        for name, raw in files.items():
            (destination / name).write_bytes(raw)
        self.assertEqual(publication_hashes(self.root), current['files_sha256'])

    def test_runtime_or_graph_change_changes_c(self):
        old = json.loads(self.prepared()['current.json'])['contract_release']
        (self.root / 'openapi.yaml').write_text('openapi: 3.1.0\ninfo: {version: changed}\npaths: {}\n')
        (self.root / SALES_CATALOG_PATH).write_bytes(sales_catalog_bytes(
            {'openapi': '3.1.0', 'info': {'version': 'changed'}, 'paths': {}}, (self.root / 'openapi.yaml').read_bytes()))
        self.report['publication_artifact'].update({'files_sha256': publication_hashes(self.root),
            'openapi_sha256': sha((self.root / 'openapi.yaml').read_bytes())})
        self.assertNotEqual(old, json.loads(self.prepared()['current.json'])['contract_release'])

    def test_failed_pending_or_unassessed_subgate_never_exports(self):
        for section in (None, 'composed_candidate', 'publication_surfaces', 'source_governance'):
            for status in ('failed', 'not_assessed'):
                report = copy.deepcopy(self.report)
                (report if section is None else report[section])['status'] = status
                with self.subTest(section=section, status=status), self.assertRaises(ValueError):
                    self.prepared(report)
        for key in ('global_errors', 'missing_inputs', 'blocked_providers'):
            report = copy.deepcopy(self.report); report[key] = ['61 enabled operations']
            with self.assertRaises(ValueError): self.prepared(report)

    def test_graph_drift_and_wrong_runtime_receipt_rejected(self):
        for key in ('runtime_acquisition_sha256', 'runtime'):
            report = copy.deepcopy(self.report); report[key] = 'wrong'
            with self.assertRaises(ValueError): self.prepared(report)
        (self.root / 'openapi.yaml').write_text('drift')
        with self.assertRaises(ValueError): self.prepared()

    def test_flat_fact_drift_and_incomplete_manifest_rejected(self):
        path = self.facts / 'example.json'; original = path.read_bytes()
        path.write_text('{}')
        with self.assertRaises(ValueError): acquired_input(self.facts)
        path.write_bytes(original)
        (self.facts / 'providers/example.json').write_text('{}')
        with self.assertRaises(ValueError): acquired_input(self.facts)

    def test_expired_or_unknown_source_rejected(self):
        for change in ({'freshness': 'unknown'}, {'review_due_at': None},
                       {'next_acquisition_due_at': None},
                       {'next_acquisition_due_at': self.now.isoformat()}):
            report = copy.deepcopy(self.report)
            report['source_governance']['sources']['source.json'].update(change)
            with self.assertRaises(ValueError): self.prepared(report)

    def test_source_identity_and_future_review_cannot_be_relabelled_passed(self):
        for change in ({'policy_revision': 'wrong'}, {'source_hash': 'wrong'}, {'policy': 'unknown'},
                       {'checked_at': (self.now + timedelta(seconds=1)).isoformat()},
                       {'last_successful_review_at': (self.now + timedelta(seconds=1)).isoformat()}):
            report = copy.deepcopy(self.report)
            report['source_governance']['sources']['source.json'].update(change)
            with self.assertRaises(ValueError): self.prepared(report)
        report = copy.deepcopy(self.report); report['evaluation'] = 'hypothetical'
        with self.assertRaises(ValueError): self.prepared(report)

    def test_missing_source_membership_and_changed_metadata_rejected(self):
        report = copy.deepcopy(self.report); report['source_governance']['sources'] = {}
        with self.assertRaises(ValueError): self.prepared(report)
        report = copy.deepcopy(self.report); report['publication_artifact']['source_hashes'] = {}
        with self.assertRaises(ValueError): self.prepared(report)
        report = copy.deepcopy(self.report); report['publication_artifact']['source_metadata']['source.json']['policy_revision'] = 'wrong'
        with self.assertRaises(ValueError): self.prepared(report)
        cached = self.root / '.cache/source-reviews.json'; cached.write_text('{"receipts":{}}')
        with self.assertRaises(ValueError): self.prepared()

    def test_failure_preserves_lastgood_files(self):
        destination = self.root / 'docs/publication'; destination.mkdir(parents=True, exist_ok=True)
        (destination / 'current.json').write_bytes(b'lastgood')
        report = self.root / 'report.json'; report.write_text('{"status":"failed"}')
        with self.assertRaises(ValueError): export(self.root, self.facts, report)
        self.assertEqual((destination / 'current.json').read_bytes(), b'lastgood')

    def test_current_discovery_uses_same_strict_acquirer(self):
        output = self.root / 'discovered'
        with patch('fetch_runtime_release.PublicReader', return_value=self.reader), patch('builtins.print'):
            main(['--current', '--output', str(output)])
        self.assertEqual(acquired_input(output)[0]['artifact_revision'], self.report['runtime']['artifact_revision'])

    def test_discovery_changed_generation_rejected(self):
        calls = 0
        def reader(path):
            nonlocal calls
            raw, headers = self.reader(path)
            if path == '/public/api-contract/current':
                calls += 1
                if calls == 1:
                    current = json.loads(raw); current['generation'] -= 1; current['published_generation'] -= 1
                    return canonical(current), headers
            return raw, headers
        with patch('fetch_runtime_release.PublicReader', return_value=reader), self.assertRaises(SystemExit):
            main(['--current', '--output', str(self.root / 'changed')])
        self.assertFalse((self.root / 'changed').exists())

    def test_discovery_cannot_mix_with_explicit_pins(self):
        with self.assertRaises(SystemExit):
            main(['--current', '--artifact-revision', 'a' * 64, '--output', str(self.root / 'mixed')])
