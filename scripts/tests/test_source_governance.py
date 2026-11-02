import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.source_governance import (acquisition_receipt, initial_policy, observation,
    policy_errors, receipt_key, source_report, source_scope)
from scripts.refresh_upstream import refresh


class GovernanceTests(unittest.TestCase):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def source(self, mode='manual'):
        return initial_policy({'kind': 'manual' if mode != 'automatic' else 'provider_openapi',
            'url': 'https://official.example.invalid/reference', 'content_hash': 'sha256:fixture',
            'fetched_at': '2026-09-30T00:00:00+00:00', 'refresh_policy': mode,
            **({'refresh_reason': 'Reviewed fixed source revision', 'source_revision': 'a' * 40} if mode == 'pinned' else {})})

    def manual_receipt(self, source, at=None):
        return {'source_hash': source['content_hash'], 'policy_revision': source['policy_revision'],
            'last_successful_review_at': (at or self.now).isoformat(), 'result': 'confirmed',
            'reviewer': 'independent-reviewer', 'review_ref': 'b' * 40,
            'evidence': {'kind': 'official_documentation', 'url': source['url']}}

    def test_fetched_at_and_local_reread_cannot_establish_review(self):
        source = self.source()
        result = observation(source, {}, self.now)
        self.assertEqual('unknown', result['freshness'])
        self.assertIsNone(result['last_successful_review_at'])
        fake = acquisition_receipt(source, self.now)
        self.assertEqual('unknown', observation(source, {receipt_key(source): fake}, self.now)['freshness'])

    def test_old_manual_review_never_expires_while_source_bytes_are_unchanged(self):
        source = self.source()
        before = copy.deepcopy(source)
        receipts = {receipt_key(source): self.manual_receipt(source, self.now - timedelta(days=400))}
        old = observation(source, receipts, self.now)
        self.assertEqual(('manual_due', 'fresh'), (old['status'], old['freshness']))
        # The due time stays as an informational review hint.
        self.assertLess(old['review_due_at'], self.now.isoformat())
        self.assertEqual(before, source)

    def test_mismatched_hash_policy_future_or_missing_review_attribution_invalid(self):
        source = self.source('pinned')
        for change in ({'source_hash': 'other'}, {'policy_revision': 'other'}, {'reviewer': ''},
                       {'review_ref': 'main'}, {'last_successful_review_at': (self.now + timedelta(days=1)).isoformat()}):
            with self.subTest(change=change):
                receipt = {**self.manual_receipt(source), **change}
                self.assertEqual('unknown', observation(source, {receipt_key(source): receipt}, self.now)['freshness'])

    def test_policy_change_invalidates_previous_receipt(self):
        source = self.source()
        receipt = self.manual_receipt(source)
        source['review_period_days'] = 90
        self.assertIn('missing_or_stale_policy_revision', policy_errors(source))
        self.assertEqual('unknown', observation(source, {receipt_key(source): receipt}, self.now)['freshness'])

    def test_pinned_update_signal_blocks_until_reviewed(self):
        source = self.source('pinned')
        receipt = self.manual_receipt(source)
        receipts = {receipt_key(source): receipt}
        self.assertEqual('fresh', observation(source, receipts, self.now)['freshness'])
        receipt['latest_revision'] = {'source_hash': 'new-revision', 'url': source['url']}
        result = observation(source, receipts, self.now)
        self.assertEqual('pinned_update_available', result['status'])
        self.assertEqual('overdue', result['freshness'])

    def test_policy_cannot_extend_fixed_deadlines(self):
        source = self.source('automatic')
        source.update(review_period_days=31, refresh_interval_hours=25)
        self.assertIn('invalid_review_period', policy_errors(source))
        self.assertIn('invalid_refresh_interval', policy_errors(source))

    def test_automatic_unchanged_updates_only_receipt_not_mirror(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'openapi/upstream/p.json'
            path.parent.mkdir(parents=True)
            doc = {'info': {'x-aisa-source': self.source('automatic')}, 'paths': {}}
            path.write_text(json.dumps(doc))
            before = path.read_bytes()
            acquired = copy.deepcopy(doc)
            acquired['info']['x-aisa-source']['fetched_at'] = self.now.isoformat()
            changes, report = refresh(root, lambda *_: acquired, self.now)
            self.assertFalse(changes)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual('fresh', report['sources']['p.json']['freshness'])
            self.assertEqual('passed', report['status'])
            self.assertIn(receipt_key(doc['info']['x-aisa-source']), report['receipts'])

    def test_acquisition_failure_preserves_prior_receipt_and_immediately_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'openapi/upstream/p.json'
            path.parent.mkdir(parents=True)
            source = self.source('automatic')
            path.write_text(json.dumps({'info': {'x-aisa-source': source}, 'paths': {}}))
            before = path.read_bytes()
            receipts = {receipt_key(source): acquisition_receipt(source, self.now - timedelta(hours=1))}
            changes, report = refresh(root, Mock(side_effect=OSError('private URL should not be exposed')), self.now, receipts)
            self.assertFalse(changes)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(receipts, report['receipts'])
            self.assertEqual(('failed', 'fetch_failed'), (report['status'], report['sources']['p.json']['freshness']))
            self.assertNotIn('private URL', json.dumps(report))
            # Later formal assessment restores the cached last attempt too;
            # a still-young previous success must not conceal a newer failure.
            later = source_report(root, report['receipts'], self.now, report['attempts'])
            self.assertEqual('failed', later['status'])
            self.assertEqual('fetch_failed', later['sources']['p.json']['freshness'])

    def test_automatic_receipt_does_not_expire_after_acquisition_interval(self):
        source = self.source('automatic')
        receipt = acquisition_receipt(source, self.now - timedelta(days=60))
        result = observation(source, {receipt_key(source): receipt}, self.now)
        self.assertEqual(('unchanged', 'fresh'), (result['status'], result['freshness']))
        self.assertLess(result['next_acquisition_due_at'], self.now.isoformat())

    def test_inventory_policy_migration_needs_no_deployment_or_fabricated_review(self):
        from catalog_fixture import catalog_root
        root = catalog_root()
        paths = list((root / 'openapi/upstream').glob('*.json'))
        original = {path: path.read_bytes() for path in paths}
        # Code-only PRs retain the previous published source files. Exercise
        # the policy migration in a disposable input, not by requiring that
        # unapproved production artifacts be merged alongside the code.
        with tempfile.TemporaryDirectory() as temp:
            migrated = Path(temp)
            target = migrated / 'openapi/upstream'; target.mkdir(parents=True)
            for path in paths:
                document = json.loads(original[path])
                document['info']['x-aisa-source'] = initial_policy(document['info']['x-aisa-source'])
                (target / path.name).write_text(json.dumps(document))
            report = source_report(migrated, {}, self.now)
        self.assertEqual(original, {path: path.read_bytes() for path in paths})
        self.assertEqual(len(paths), len(report['sources']))
        self.assertTrue(report['sources'])
        self.assertTrue(all(not row['policy_errors'] for row in report['sources'].values()))
        self.assertTrue(all(row['freshness'] == 'unknown' for row in report['sources'].values()))
        self.assertEqual('not_assessed', report['status'])

    def scoped_root(self, temp, source, document):
        root = Path(temp)
        (root / 'openapi/upstream').mkdir(parents=True)
        (root / 'openapi/upstream/p.json').write_text(json.dumps({'info': {'x-aisa-source': source}}))
        (root / 'openapi/coverage.json').write_text(json.dumps({'providers': {'prov': []}}))
        (root / 'openapi/prov.json').write_text(json.dumps(document))
        return root

    def test_scoped_source_is_confined_only_with_a_real_due_time(self):
        source = self.source()
        operation = {'paths': {'/x': {'post': {'x-aisa-source': {'content_hash': source['content_hash']}}}}}
        with tempfile.TemporaryDirectory() as temp:
            root = self.scoped_root(temp, source, operation)
            self.assertEqual({'p.json': ['prov']}, source_scope(root, {'p.json': source['content_hash']})['sources'])
            overdue = {receipt_key(source): self.manual_receipt(source, self.now - timedelta(days=31))}
            # Elapsed time alone is no failure.
            self.assertEqual(('passed', {}), (lambda r: (r['status'], r['scoped_failures']))(source_report(root, overdue, self.now)))
            failed = {receipt_key(source): {'status': 'fetch_failed', 'checked_at': (self.now - timedelta(hours=1)).isoformat()}}
            report = source_report(root, overdue, self.now, failed)
            self.assertEqual(('passed', {'prov': ['p.json']}), (report['status'], report['scoped_failures']))
            # No valid receipt means no due time to bound the provider: global.
            report = source_report(root, {}, self.now)
            self.assertEqual(('not_assessed', {}), (report['status'], report['scoped_failures']))
            # Policy errors are always global failures.
            broken = dict(source, owner='')
            (root / 'openapi/upstream/p.json').write_text(json.dumps({'info': {'x-aisa-source': broken}}))
            self.assertEqual('failed', source_report(root, overdue, self.now)['status'])

    def test_unreadable_provenance_makes_every_source_global(self):
        source = self.source()
        operation = {'paths': {'/x': {'get': {'x-aisa-source': {'content_hash': source['content_hash'],
                     'provenance_ref': '#/info/x-aisa-source-provenance/' + 'f' * 64, 'provenance_sha256': 'f' * 64}}}}}
        with tempfile.TemporaryDirectory() as temp:
            root = self.scoped_root(temp, source, operation)
            self.assertEqual({'p.json': []}, source_scope(root, {'p.json': source['content_hash']})['sources'])
            overdue = {receipt_key(source): self.manual_receipt(source, self.now - timedelta(days=31))}
            failed = {receipt_key(source): {'status': 'fetch_failed', 'checked_at': (self.now - timedelta(hours=1)).isoformat()}}
            self.assertEqual('failed', source_report(root, overdue, self.now, failed)['status'])

    def test_new_source_without_owner_policy_fails_governance(self):
        errors = policy_errors({'kind': 'manual', 'url': 'https://official.example.invalid'})
        self.assertIn('missing_owner', errors)
        self.assertIn('missing_or_invalid_policy', errors)


if __name__ == '__main__':
    unittest.main()
