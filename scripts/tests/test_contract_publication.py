import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import subprocess
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

    def publish_report(self, now=None):
        path = self.root / 'latest-report.json'
        path.write_bytes(canonical(self.report))
        return export(self.root, self.facts, path, now=now or self.now)

    def publication_bytes(self):
        return {name: (self.root / 'docs/publication' / name).read_bytes() for name in
                ('current.json', 'formal-contract-readiness.json', 'runtime-acquisition.json')}

    def advance_observations(self):
        later = self.now + timedelta(minutes=10)
        saved = json.loads((self.root / '.cache/source-reviews.json').read_text())
        self.report['source_governance'] = source_report(self.root, saved['receipts'], checked_at=later)
        self.report['publication_artifact']['published_ref'] = getattr(self, 'next_git_base', 'b' * 40)
        raw_path = self.facts / 'acquisition-receipt.json'
        receipt = json.loads(raw_path.read_bytes())
        receipt.update(started_at=(later - timedelta(seconds=2)).isoformat(), completed_at=later.isoformat())
        # Actual immutable Runtime and category content remain fixed, but the
        # category cache-construction time and acquisition clocks are new.
        category_path = self.facts / 'category.json'
        category = json.loads(category_path.read_bytes()); category['cached_at'] = int(later.timestamp())
        category_path.write_bytes(canonical(category))
        receipt.update(category_sha256=sha(category_path.read_bytes()), category_after_sha256=sha(category_path.read_bytes()))
        raw_path.write_bytes(canonical(receipt))
        self.report['runtime_acquisition_sha256'] = sha(raw_path.read_bytes())
        return later

    def test_same_c_observation_refresh_keeps_all_three_bytes_and_runs_prepare(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init'); git('config', 'user.name', 'Publication Test'); git('config', 'user.email', 'test@example.invalid')
        git('commit', '--allow-empty', '-m', 'previous assessed base')
        self.report['publication_artifact']['published_ref'] = git('rev-parse', 'HEAD')
        git('commit', '--allow-empty', '-m', 'publication commit')
        self.next_git_base = git('rev-parse', 'HEAD')
        old = self.publish_report(); before = self.publication_bytes()
        later = self.advance_observations()
        with patch('export_contract_publication.os.replace', side_effect=AssertionError('no-op wrote metadata')):
            self.assertEqual(self.publish_report(later), old)
        self.assertEqual(self.publication_bytes(), before)
        # A syntactically valid but nonexistent old base is not a Git proof.
        directory = self.root / 'docs/publication'
        altered = json.loads(before['formal-contract-readiness.json'])
        altered['publication_artifact']['published_ref'] = 'f' * 40
        raw = canonical(altered); (directory / 'formal-contract-readiness.json').write_bytes(raw)
        pointer = json.loads(before['current.json']); pointer['formal_readiness']['sha256'] = sha(raw)
        (directory / 'current.json').write_bytes(canonical(pointer))
        with patch('export_contract_publication.os.replace', wraps=__import__('os').replace) as replace:
            self.publish_report(later)
            self.assertEqual(replace.call_count, 3)
        before = self.publication_bytes()
        # Even the exact same C cannot bypass a newly failed formal gate.
        self.report['status'] = 'failed'
        with self.assertRaises(ValueError): self.publish_report(later)
        self.assertEqual(self.publication_bytes(), before)

    def test_changed_graph_and_authorization_are_not_hidden_by_noop(self):
        old = self.publish_report(); before = self.publication_bytes()
        later = self.advance_observations()
        saved_path = self.root / '.cache/source-reviews.json'
        saved = json.loads(saved_path.read_bytes())
        saved['receipts'][receipt_key(self.metadata)] = acquisition_receipt(self.metadata, later)
        saved_path.write_bytes(canonical(saved))
        self.report['source_governance'] = source_report(self.root, saved['receipts'], checked_at=later)
        new = self.publish_report(later)
        self.assertEqual(new['contract_release'], old['contract_release'])
        self.assertNotEqual(new['source_authorization_expires_at'], old['source_authorization_expires_at'])
        self.assertNotEqual(self.publication_bytes(), before)
        (self.root / 'openapi.yaml').write_text('openapi: 3.1.0\npaths: {}\ninfo: {version: next}\n')
        raw = (self.root / 'openapi.yaml').read_bytes()
        (self.root / SALES_CATALOG_PATH).write_bytes(sales_catalog_bytes({'openapi':'3.1.0','paths':{},'info':{'version':'next'}}, raw))
        self.report['publication_artifact'].update(files_sha256=publication_hashes(self.root), openapi_sha256=sha(raw))
        self.assertNotEqual(self.publish_report(later)['contract_release'], new['contract_release'])

    def test_same_expiry_but_different_authority_evidence_is_republished(self):
        old = self.publish_report(); before = self.publication_bytes()
        later = self.now + timedelta(minutes=10)
        path = self.root / '.cache/source-reviews.json'; saved = json.loads(path.read_bytes())
        saved['receipts'][receipt_key(self.metadata)]['evidence']['review_note'] = 'new attributed evidence'
        path.write_bytes(canonical(saved))
        self.report['source_governance'] = source_report(self.root, saved['receipts'], checked_at=later)
        new = self.publish_report(later)
        self.assertEqual(new['contract_release'], old['contract_release'])
        self.assertEqual(new['source_authorization_expires_at'], old['source_authorization_expires_at'])
        self.assertNotEqual(self.publication_bytes(), before)

    def test_invalid_previous_bundle_is_replaced_only_by_fresh_validated_bundle(self):
        old = self.publish_report(); clean = self.publication_bytes()
        directory = self.root / 'docs/publication'
        for mode in ('missing', 'raw-corruption', 'wrong-pointer', 'failed-report', 'future-acquisition', 'different-manifest', 'expired-authorization'):
            with self.subTest(mode=mode):
                for name, raw in clean.items(): (directory / name).write_bytes(raw)
                current = json.loads(clean['current.json']); report = json.loads(clean['formal-contract-readiness.json'])
                receipt = json.loads(clean['runtime-acquisition.json'])
                if mode == 'missing': (directory / 'runtime-acquisition.json').unlink()
                elif mode == 'raw-corruption': (directory / 'formal-contract-readiness.json').write_bytes(b'invalid JSON')
                elif mode == 'wrong-pointer': current['contract_release'] = '0' * 64
                elif mode == 'expired-authorization': current['source_authorization_expires_at'] = self.now.isoformat()
                elif mode == 'failed-report': report['status'] = 'failed'
                elif mode == 'future-acquisition': receipt['completed_at'] = (self.now + timedelta(days=1)).isoformat()
                elif mode == 'different-manifest': receipt['manifest_files'] = []
                if mode in ('future-acquisition', 'different-manifest'):
                    raw = canonical(receipt); (directory / 'runtime-acquisition.json').write_bytes(raw)
                    current['runtime_acquisition']['sha256'] = sha(raw); report['runtime_acquisition_sha256'] = sha(raw)
                if mode in ('failed-report', 'future-acquisition', 'different-manifest'):
                    raw = canonical(report); (directory / 'formal-contract-readiness.json').write_bytes(raw)
                    current['formal_readiness']['sha256'] = sha(raw)
                if mode not in ('missing', 'raw-corruption'): (directory / 'current.json').write_bytes(canonical(current))
                with patch('export_contract_publication.os.replace', wraps=__import__('os').replace) as replace:
                    self.assertEqual(self.publish_report(), old)
                    self.assertEqual(replace.call_count, 3)
                self.assertEqual(self.publication_bytes(), clean)

    def test_expired_current_source_fails_without_touching_lastgood(self):
        self.publish_report(); before = self.publication_bytes()
        expired = self.now + timedelta(days=90)
        saved = json.loads((self.root / '.cache/source-reviews.json').read_bytes())
        self.report['source_governance'] = source_report(self.root, saved['receipts'], checked_at=expired)
        with self.assertRaises(ValueError): self.publish_report(expired)
        self.assertEqual(self.publication_bytes(), before)

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
