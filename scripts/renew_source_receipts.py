#!/usr/bin/env python3
"""Renew due automatic observations against unchanged locked upstream bytes.

This does not update schemas or approve changed sources. Run before candidate
or publication assessment, after staging the complete graph. Scoped failures
retain the existing provider expiry; global failures still reject publication.
Validate with: python -m unittest discover -s scripts/tests -p test_renew_source_receipts.py
"""
import argparse
import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from import_upstream import import_source
from prepare_source_receipts import merge_evidence
from source_governance import (acquisition_receipt, policy_errors, receipt_key,
                               source_report, timestamp)


def renew(root, packet, *, fetch=None, checked_at=None, due_within_hours=1):
    if not 0 <= due_within_hours <= 6:
        raise ValueError('Automatic acquisition window must be between zero and six hours')
    root = Path(root)
    now = checked_at or datetime.now(timezone.utc)
    packet = merge_evidence(packet)
    before = source_report(root, packet['receipts'], now, packet['attempts'])
    report = {'checked_at': now.isoformat(), 'confirmed': {}, 'changed': {}, 'failed': {},
              'scope': 'unchanged automatic source observations only; no schema update or manual review'}
    selected = []
    for path in sorted((root / 'openapi/upstream').glob('*.json')):
        source = json.loads(path.read_text())['info']['x-aisa-source']
        if source.get('refresh_policy') != 'automatic':
            continue
        if policy_errors(source):
            report['failed'][path.name] = {'reason': 'invalid_source_policy'}
            continue
        row = before['sources'][path.name]
        due = timestamp(row.get('next_acquisition_due_at'))
        if row['freshness'] != 'fresh' or due is None or due <= now + timedelta(hours=due_within_hours):
            selected.append((path, source))

    def acquire(item):
        path, source = item
        try:
            document = (fetch or import_source)(path.stem, source['url'])
            actual = document['info']['x-aisa-source']
            if actual.get('kind') != source.get('kind') or actual.get('url') != source['url']:
                raise ValueError('Fetched source authority differs')
            if actual.get('content_hash') != source['content_hash']:
                return path.name, source, 'changed', {'source_hash': source['content_hash'],
                    'observed_source_hash': actual.get('content_hash'), 'reason': 'source_changed_requires_review'}
            return path.name, source, 'confirmed', {'source_hash': source['content_hash']}
        except Exception as exc:
            # Upstream response bodies and credentials are not diagnostic output.
            return path.name, source, 'failed', {'reason': 'official_acquisition_failed',
                                                'exception_type': type(exc).__name__}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for name, source, outcome, evidence in pool.map(acquire, selected):
            key = receipt_key(source)
            report[outcome][name] = evidence
            if outcome == 'confirmed':
                packet['receipts'][key] = acquisition_receipt(source, now)
                packet['attempts'][key] = {'checked_at': now.isoformat(), 'status': 'confirmed'}
            else:
                # A newer observed change or failure must not disappear behind
                # an older successful cache entry for these locked bytes.
                packet['attempts'][key] = {'checked_at': now.isoformat(), 'status': 'fetch_failed',
                                            'failure': evidence['reason']}
    # Apply the same isolation as source_governance/source_expiry, using the
    # newly staged graph. Never turn an expired provider receipt into a fresh
    # one, or let a missing initial review acquire a scoped exemption.
    scoped, global_failures = {}, []
    for name in sorted(set(report['failed']) | set(report['changed'])):
        row = before['sources'][name]
        owners = before['source_scope']['sources'][name]
        if owners and not row['policy_errors'] and row['review_due_at']:
            for provider in owners:
                scoped.setdefault(provider, []).append(name)
        else:
            global_failures.append(name)
    report['scoped_failures'] = scoped
    report['global_failures'] = global_failures
    report['status'] = 'failed' if global_failures else 'passed'
    return packet, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    packet, report = renew(args.root, json.loads(args.receipts.read_text()))
    temporary = args.receipts.with_suffix(args.receipts.suffix + '.tmp')
    temporary.write_text(json.dumps(packet, indent=2, sort_keys=True) + '\n')
    temporary.replace(args.receipts)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': report['status'], 'confirmed': len(report['confirmed']),
                      'changed': report['changed'], 'failed': report['failed'],
                      'scoped_failures': report['scoped_failures'],
                      'global_failures': report['global_failures']}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
