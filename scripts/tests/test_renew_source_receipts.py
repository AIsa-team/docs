import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import digest
from renew_source_receipts import renew
from source_governance import acquisition_receipt, initial_policy, receipt_key, source_report


class AutomaticReceiptRenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 26, 15, tzinfo=timezone.utc)
        self.document = {'openapi': '3.1.0', 'info': {'title': 'Provider', 'version': '1'}, 'paths': {}}
        self.source = initial_policy({'kind': 'provider_openapi', 'url': 'https://example.org/api.json',
            'converter': 'fixture', 'content_hash': digest(self.document)})
        self.document['info']['x-aisa-source'] = self.source
        self.path = self.root / 'openapi/upstream/provider.json'
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(self.document))
        self.original = self.path.read_bytes()
        self.key = receipt_key(self.source)
        self.old = acquisition_receipt(self.source, self.now - timedelta(hours=25))
        self.packet = {'schema_version': 1, 'receipts': {self.key: self.old}, 'attempts': {}}

    def run_renewal(self, fetch):
        return renew(self.root, self.packet, fetch=fetch, checked_at=self.now)

    def test_expired_receipt_is_renewed_only_after_unchanged_official_acquisition(self):
        calls = []
        def fetch(name, url):
            calls.append((name, url))
            return copy.deepcopy(self.document)
        packet, report = self.run_renewal(fetch)
        self.assertEqual(calls, [('provider', self.source['url'])])
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(packet['receipts'][self.key]['last_successful_review_at'], self.now.isoformat())
        self.assertEqual(source_report(self.root, packet['receipts'], self.now, packet['attempts'])['status'], 'passed')
        self.assertEqual(self.packet['receipts'][self.key], self.old)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_fresh_receipts_do_not_trigger_network_or_change_observations(self):
        self.packet['receipts'][self.key] = acquisition_receipt(self.source, self.now - timedelta(hours=1))
        with patch('builtins.print'):
            packet, report = self.run_renewal(lambda *args: self.fail('fresh source fetched'))
        self.assertEqual(packet, self.packet)
        self.assertEqual(report['status'], 'passed')

    def test_receipt_due_during_publication_is_acquired_before_it_expires(self):
        self.packet['receipts'][self.key] = acquisition_receipt(self.source, self.now - timedelta(hours=23, minutes=30))
        packet, report = self.run_renewal(lambda *args: copy.deepcopy(self.document))
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(packet['receipts'][self.key]['last_successful_review_at'], self.now.isoformat())

    def test_fetch_failure_preserves_prior_review_and_records_failed_attempt(self):
        def fail(*args):
            raise TimeoutError('fixture')
        packet, report = self.run_renewal(fail)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(packet['receipts'][self.key], self.old)
        self.assertEqual(packet['attempts'][self.key]['status'], 'fetch_failed')
        self.assertEqual(source_report(self.root, packet['receipts'], self.now, packet['attempts'])['status'], 'failed')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_changed_source_requires_review_without_renewing_locked_bytes(self):
        changed = copy.deepcopy(self.document)
        changed['info']['x-aisa-source']['content_hash'] = 'sha256:' + 'b' * 64
        packet, report = self.run_renewal(lambda *args: changed)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('provider.json', report['changed'])
        self.assertEqual(packet['receipts'][self.key], self.old)
        self.assertEqual(self.path.read_bytes(), self.original)

    def attribute_source(self):
        (self.root / 'openapi/coverage.json').write_text(json.dumps({'providers': {'provider': []}}))
        (self.root / 'openapi/provider.json').write_text(json.dumps({'openapi': '3.1.0',
            'info': {'title': 'Provider', 'version': '1'},
            'paths': {'/test': {'get': {'x-aisa-source': self.source}}}}))

    def test_changed_attributed_source_retains_its_existing_provider_expiry(self):
        self.attribute_source()
        changed = copy.deepcopy(self.document)
        changed['info']['x-aisa-source']['content_hash'] = 'sha256:' + 'b' * 64
        packet, report = self.run_renewal(lambda *args: changed)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['scoped_failures'], {'provider': ['provider.json']})
        self.assertEqual(packet['receipts'][self.key], self.old)
        observed = source_report(self.root, packet['receipts'], self.now, packet['attempts'])
        self.assertEqual(observed['status'], 'passed')
        self.assertEqual(observed['scoped_failures'], report['scoped_failures'])
        self.assertLess(datetime.fromisoformat(observed['sources']['provider.json']['next_acquisition_due_at']), self.now)

    def test_unreviewed_source_cannot_be_excused_by_provider_attribution(self):
        self.attribute_source()
        self.packet['receipts'] = {}
        changed = copy.deepcopy(self.document)
        changed['info']['x-aisa-source']['content_hash'] = 'sha256:' + 'b' * 64
        _, report = self.run_renewal(lambda *args: changed)
        self.assertEqual(report['status'], 'failed')

    def test_different_authority_cannot_renew_the_same_hash(self):
        changed = copy.deepcopy(self.document)
        changed['info']['x-aisa-source']['url'] = 'https://different.example/api.json'
        packet, report = self.run_renewal(lambda *args: changed)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(packet['receipts'][self.key], self.old)

    def test_new_actual_success_clears_a_newer_failed_attempt(self):
        self.packet['receipts'][self.key] = acquisition_receipt(self.source, self.now - timedelta(hours=1))
        self.packet['attempts'][self.key] = {'status': 'fetch_failed',
            'checked_at': (self.now - timedelta(minutes=5)).isoformat()}
        packet, report = self.run_renewal(lambda *args: copy.deepcopy(self.document))
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(source_report(self.root, packet['receipts'], self.now, packet['attempts'])['status'], 'passed')

    def test_manual_review_cannot_be_replaced_by_an_automatic_acquisition(self):
        source = initial_policy({**self.source, 'refresh_policy': 'manual'})
        self.document['info']['x-aisa-source'] = source
        self.path.write_text(json.dumps(self.document))
        packet, report = self.run_renewal(lambda *args: self.fail('manual source fetched'))
        self.assertEqual(packet, self.packet)
        self.assertEqual(report['status'], 'passed')

    def test_reviewed_mapping_with_automatic_policy_keeps_its_source_kind(self):
        self.source['kind'] = 'manual'
        self.path.write_text(json.dumps(self.document))
        packet, report = self.run_renewal(lambda *args: copy.deepcopy(self.document))
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(packet['receipts'][self.key]['last_successful_review_at'], self.now.isoformat())

    def test_publication_and_candidate_workflows_renew_before_assessment(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/pull-openapi.yml').read_text())
        steps = workflow['jobs']['compose']['steps']
        stage = next(i for i, step in enumerate(steps) if step.get('name') == 'Stage contracts')
        renewal = next(i for i, step in enumerate(steps) if 'renew_source_receipts.py' in step.get('run', ''))
        assessment = next(i for i, step in enumerate(steps) if step.get('name') == 'Check formal artifact readiness before publication')
        self.assertLess(stage, renewal)
        self.assertLess(renewal, assessment)
        self.assertNotIn('continue-on-error', steps[renewal])
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        steps = workflow['jobs']['artifact-contracts']['steps']
        assessment = next(i for i, step in enumerate(steps) if step.get('name') == 'Check actual candidate readiness')
        cache = next(i for i, step in enumerate(steps) if step.get('name') == 'Cache actual source renewal observations')
        self.assertLess(assessment, cache)
        self.assertIn('always()', steps[cache]['if'])


if __name__ == '__main__':
    unittest.main()
